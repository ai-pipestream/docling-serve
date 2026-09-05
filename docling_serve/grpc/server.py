from __future__ import annotations

import asyncio
import importlib.metadata
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Optional

import grpc
from fastapi import HTTPException

from docling.datamodel.base_models import OutputFormat
from docling.datamodel.service.responses import (
    FailureCategory,
    FailurePhase,
    PublicFailureInfo,
)
from docling_jobkit.connectors.errors import (
    SourceConnectorConfigError,
    TargetConnectorConfigError,
)
from docling_jobkit.datamodel.chunking import ChunkingExportOptions
from docling_jobkit.datamodel.result import DoclingTaskResult
from docling_jobkit.datamodel.stored_outcome import (
    StoredFailureOutcome,
    StoredSuccessOutcome,
)
from docling_jobkit.datamodel.task_meta import TaskStatus, TaskType
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
    RedisBackpressureError,
    TaskNotFoundError,
)

from docling_serve.orchestrator_factory import get_async_orchestrator
from docling_serve.policy import (
    ServicePolicy,
    build_service_policy,
    normalize_request,
    resolve_default_target,
    validate_batch_convert_request,
)
from docling_serve.public_errors import build_public_http_detail
from docling_serve.settings import docling_serve_settings

from .gen.ai.docling.serve.v1 import (
    docling_serve_pb2,
    docling_serve_pb2_grpc,
    docling_serve_types_pb2,
)
from .mapping import (
    UnexpectedResultType,
    clear_response_to_proto,
    requested_output_formats,
    set_chunk_result,
    set_convert_result,
    task_failure_to_proto,
    task_status_to_proto,
    to_batch_convert_request,
    to_callbacks,
    to_convert_options,
    to_hierarchical_chunk_options,
    to_hybrid_chunk_options,
    to_task_sources,
    to_task_target,
    with_single_use_cleanup,
)
from .policy_enforcement import normalize_options, validate_request

_log = logging.getLogger(__name__)

# REST maps queue backpressure to 503 + Retry-After; the gRPC equivalent for
# "capacity exhausted, retry shortly" is RESOURCE_EXHAUSTED.
_BACKPRESSURE_MESSAGE = "Server is busy, please try again shortly."


class RequestRejected(ValueError):
    """A request failed parsing or policy; the message is client-safe."""


@dataclass
class _PreparedRequest:
    """Validated, policy-normalized parts of a convert or chunk request."""

    sources: list
    options: object
    target: object
    callbacks: list
    requested_formats: set[OutputFormat]
    chunking_options: object = None
    chunking_export_options: ChunkingExportOptions = field(
        default_factory=ChunkingExportOptions
    )


class DoclingServeGrpcService(docling_serve_pb2_grpc.DoclingServeServiceServicer):
    def __init__(
        self,
        orchestrator: Optional[BaseOrchestrator] = None,
        policy: Optional[ServicePolicy] = None,
    ) -> None:
        self._orchestrator = orchestrator or get_async_orchestrator()
        self._policy = policy or build_service_policy(docling_serve_settings)
        self._queue_task: Optional[asyncio.Task] = None
        self._queue_lock = asyncio.Lock()
        self._requested_formats: dict[str, set[OutputFormat]] = {}

    async def start(self) -> None:
        await self._ensure_queue_started()

    async def close(self) -> None:
        if self._queue_task is None:
            return
        self._queue_task.cancel()
        try:
            await self._queue_task
        except asyncio.CancelledError:
            _log.info("Queue processor cancelled.")
        self._queue_task = None

    # -------------------- helpers --------------------

    @staticmethod
    async def _check_api_key(context: grpc.aio.ServicerContext) -> None:
        if not docling_serve_settings.api_key:
            return
        metadata = {k.lower(): v for k, v in context.invocation_metadata()}
        api_key = (
            metadata.get("api-key")
            or metadata.get("x-api-key")
            or metadata.get("api_key")
        )
        if api_key != docling_serve_settings.api_key:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "API key required")

    async def _abort(
        self,
        context: grpc.aio.ServicerContext,
        code: grpc.StatusCode,
        message: str,
    ) -> None:
        await context.abort(code, message)

    @staticmethod
    def _parse_sources(request_sources) -> list:
        """Parse proto sources; RequestRejected on bad or empty input."""
        try:
            sources = to_task_sources(request_sources)
        except ValueError as exc:
            raise RequestRejected(str(exc)) from exc
        if not sources:
            raise RequestRejected("At least one source is required.")
        return sources

    @staticmethod
    def _parse_options(proto_options):
        """Map proto convert options; RequestRejected on bad input.

        Covers both explicit mapping rejections (a pipeline tag the installed
        engine lacks) and Pydantic validation errors from the options model.
        """
        try:
            return to_convert_options(proto_options)
        except ValueError as exc:
            raise RequestRejected(str(exc)) from exc

    def _parse_target(self, request_body):
        if request_body.HasField("target"):
            return to_task_target(request_body.target)
        return resolve_default_target(self._policy)

    @staticmethod
    def _parse_callbacks(proto_callbacks) -> list:
        """Map CallbackSpec entries; RequestRejected on bad input."""
        try:
            return to_callbacks(proto_callbacks)
        except ValueError as exc:
            raise RequestRejected(str(exc)) from exc

    def _enforce_policy(
        self,
        sources: list,
        options,
        target,
        *,
        chunk: bool = False,
        callbacks: Optional[list] = None,
    ):
        """Normalize options and enforce the service policy (same rules as REST).

        Returns the normalized options; RequestRejected when the request
        violates policy.
        """
        options = normalize_options(options, self._policy)
        detail = validate_request(
            sources, options, target, self._policy, chunk=chunk, callbacks=callbacks
        )
        if detail is not None:
            raise RequestRejected(detail)
        return options

    def build_convert(
        self, body: docling_serve_types_pb2.ConvertDocumentRequest
    ) -> _PreparedRequest:
        """Validate a convert body into enqueue parts; RequestRejected on error."""
        options_proto = body.options if body.HasField("options") else None
        requested_formats = requested_output_formats(options_proto)
        sources = self._parse_sources(body.sources)
        options = self._parse_options(options_proto)
        callbacks = self._parse_callbacks(body.callbacks)
        self._ensure_doc_format(options, requested_formats)
        target = self._parse_target(body)
        options = self._enforce_policy(sources, options, target, callbacks=callbacks)
        return _PreparedRequest(
            sources=sources,
            options=options,
            target=target,
            callbacks=callbacks,
            requested_formats=requested_formats,
        )

    def build_chunk(self, body, *, hybrid: bool) -> _PreparedRequest:
        """Validate a chunk body into enqueue parts; RequestRejected on error."""
        options_proto = (
            body.convert_options if body.HasField("convert_options") else None
        )
        requested_formats = requested_output_formats(options_proto)
        sources = self._parse_sources(body.sources)
        options = self._parse_options(options_proto)
        callbacks = self._parse_callbacks(body.callbacks)
        self._ensure_doc_format(options, requested_formats)
        target = self._parse_target(body)
        chunking_proto = (
            body.chunking_options if body.HasField("chunking_options") else None
        )
        chunking_options = (
            to_hybrid_chunk_options(chunking_proto)
            if hybrid
            else to_hierarchical_chunk_options(chunking_proto)
        )
        export_options = ChunkingExportOptions(
            include_converted_doc=body.include_converted_doc
        )
        options = self._enforce_policy(
            sources, options, target, chunk=True, callbacks=callbacks
        )
        return _PreparedRequest(
            sources=sources,
            options=options,
            target=target,
            callbacks=callbacks,
            requested_formats=requested_formats,
            chunking_options=chunking_options,
            chunking_export_options=export_options,
        )

    async def _prepare_convert(
        self,
        body: docling_serve_types_pb2.ConvertDocumentRequest,
        context: grpc.aio.ServicerContext,
    ) -> Optional[_PreparedRequest]:
        try:
            return self.build_convert(body)
        except RequestRejected as exc:
            await self._abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return None

    async def _prepare_chunk(
        self,
        body,
        context: grpc.aio.ServicerContext,
        *,
        hybrid: bool,
    ) -> Optional[_PreparedRequest]:
        try:
            return self.build_chunk(body, hybrid=hybrid)
        except RequestRejected as exc:
            await self._abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return None

    async def _enqueue(self, prepared: _PreparedRequest, task_type: TaskType):
        kwargs: dict = {
            "task_type": task_type,
            "sources": prepared.sources,
            "convert_options": prepared.options,
            "target": prepared.target,
        }
        if prepared.callbacks:
            kwargs["callbacks"] = prepared.callbacks
        if task_type == TaskType.CHUNK:
            kwargs["chunking_options"] = prepared.chunking_options
            kwargs["chunking_export_options"] = prepared.chunking_export_options
        return await self._orchestrator.enqueue(**kwargs)

    async def _wait_task_complete(self, task_id: str) -> bool:
        start = asyncio.get_running_loop().time()
        while True:
            task = await self._orchestrator.task_status(task_id=task_id)
            if task.is_completed():
                return True
            await asyncio.sleep(docling_serve_settings.sync_poll_interval)
            elapsed = asyncio.get_running_loop().time() - start
            if docling_serve_settings.max_sync_wait and (
                elapsed > docling_serve_settings.max_sync_wait
            ):
                return False

    async def _ensure_queue_started(self) -> None:
        if self._queue_task is not None and not self._queue_task.done():
            return
        async with self._queue_lock:
            if self._queue_task is not None and not self._queue_task.done():
                return
            if docling_serve_settings.load_models_at_boot:
                await self._orchestrator.warm_up_caches()
            self._queue_task = asyncio.create_task(self._orchestrator.process_queue())

    async def _poll_status_stream(
        self,
        task_id: str,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_types_pb2.TaskStatusPollResponse]:
        while not context.done():
            task = await self._orchestrator.task_status(task_id=task_id)
            position = await self._orchestrator.get_queue_position(task_id=task_id)
            yield task_status_to_proto(task, position)
            if task.is_completed():
                return
            await asyncio.sleep(docling_serve_settings.sync_poll_interval)

    @staticmethod
    def _ensure_doc_format(options, requested_formats: set = frozenset()) -> None:
        if options is None:
            return
        # When no exports were requested, only generate JSON (for the proto
        # doc field).  The upstream default is [MARKDOWN] which would waste
        # cycles producing Markdown that is never returned.
        if not requested_formats:
            options.to_formats = [OutputFormat.JSON]
        elif OutputFormat.JSON not in options.to_formats:
            options.to_formats.append(OutputFormat.JSON)

    async def _task_outcome(
        self, task_id: str, context: grpc.aio.ServicerContext
    ) -> Optional[DoclingTaskResult | StoredFailureOutcome]:
        """Fetch a finished task's outcome (success result or task-scope failure).

        Mirrors GET /v1/result: ``task_outcome`` may return a stored outcome
        envelope or a bare DoclingTaskResult depending on the orchestrator.
        Orchestrators that do not persist failure outcomes still record the
        task-scope ``PublicFailureInfo`` on the task itself; that is surfaced
        as the ``failure`` arm so callers never get NOT_FOUND for a task that
        has actually finished. Aborts NOT_FOUND when nothing is stored yet.
        """
        outcome = await self._orchestrator.task_outcome(task_id=task_id)
        if outcome is None:
            outcome = await self._failure_from_task_status(task_id)
        if outcome is None:
            await self._abort(
                context, grpc.StatusCode.NOT_FOUND, "Task result not found."
            )
            return None
        if isinstance(outcome, StoredSuccessOutcome):
            return outcome.result
        return outcome

    async def _failure_from_task_status(
        self, task_id: str
    ) -> Optional[StoredFailureOutcome]:
        try:
            task = await self._orchestrator.task_status(task_id=task_id)
        except TaskNotFoundError:
            return None
        if task.task_status != TaskStatus.FAILURE:
            return None
        failure = task.failure
        if failure is None:
            failure = PublicFailureInfo(
                category=FailureCategory.UNKNOWN,
                message=task.error_message or "Task failed.",
                retryable=False,
                phase=FailurePhase.UNKNOWN,
            )
        return StoredFailureOutcome(failure=failure)

    async def _fill_convert_result(
        self,
        message,
        outcome: DoclingTaskResult | StoredFailureOutcome,
        requested_formats: set[OutputFormat],
        context: grpc.aio.ServicerContext,
    ) -> bool:
        """Populate the convert result oneof; False after aborting on a bad arm."""
        if isinstance(outcome, StoredFailureOutcome):
            message.failure.CopyFrom(task_failure_to_proto(outcome.failure))
            return True
        try:
            set_convert_result(message, outcome, requested_formats)
        except UnexpectedResultType as exc:
            await self._abort(context, grpc.StatusCode.FAILED_PRECONDITION, str(exc))
            return False
        return True

    async def _fill_chunk_result(
        self,
        message,
        outcome: DoclingTaskResult | StoredFailureOutcome,
        requested_formats: set[OutputFormat],
        context: grpc.aio.ServicerContext,
    ) -> bool:
        """Populate the chunk result oneof; False after aborting on a bad arm."""
        if isinstance(outcome, StoredFailureOutcome):
            message.failure.CopyFrom(task_failure_to_proto(outcome.failure))
            return True
        try:
            set_chunk_result(message, outcome, requested_formats)
        except UnexpectedResultType as exc:
            await self._abort(context, grpc.StatusCode.FAILED_PRECONDITION, str(exc))
            return False
        return True

    async def _run_sync(
        self,
        prepared: _PreparedRequest,
        task_type: TaskType,
        context: grpc.aio.ServicerContext,
        timeout_message: str,
    ):
        """Enqueue, wait, and return (task_id, outcome); None after aborting."""
        task = await self._enqueue(prepared, task_type)
        completed = await self._wait_task_complete(task.task_id)
        if not completed:
            await self._abort(
                context, grpc.StatusCode.DEADLINE_EXCEEDED, timeout_message
            )
            return None
        outcome = await self._task_outcome(task.task_id, context)
        if outcome is None:
            return None
        return task.task_id, outcome

    async def _submit_async(
        self,
        prepared: _PreparedRequest,
        task_type: TaskType,
    ) -> docling_serve_types_pb2.TaskStatusPollResponse:
        task = await self._enqueue(prepared, task_type)
        position = await self._orchestrator.get_queue_position(task_id=task.task_id)
        self._requested_formats[task.task_id] = prepared.requested_formats
        return task_status_to_proto(task, position)

    # -------------------- RPCs --------------------

    async def Health(
        self,
        request: docling_serve_pb2.HealthRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.HealthResponse:
        await self._check_api_key(context)
        try:
            version = importlib.metadata.version("docling-serve")
        except importlib.metadata.PackageNotFoundError:
            version = "0.0.0"
        return docling_serve_pb2.HealthResponse(status="ok", version=version)

    async def ConvertSource(
        self,
        request: docling_serve_pb2.ConvertSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ConvertSourceResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        response = docling_serve_pb2.ConvertSourceResponse()
        prepared = await self._prepare_convert(request.request, context)
        if prepared is None:
            return response
        run = await self._run_sync(
            prepared,
            TaskType.CONVERT,
            context,
            "Conversion is taking too long. Increase DOCLING_SERVE_MAX_SYNC_WAIT.",
        )
        if run is None:
            return response
        task_id, outcome = run
        if not await self._fill_convert_result(
            response, outcome, prepared.requested_formats, context
        ):
            return response
        with_single_use_cleanup(self._orchestrator, task_id)
        return response

    async def ConvertSourceAsync(
        self,
        request: docling_serve_pb2.ConvertSourceAsyncRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ConvertSourceAsyncResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        prepared = await self._prepare_convert(request.request, context)
        if prepared is None:
            return docling_serve_pb2.ConvertSourceAsyncResponse()
        status = await self._submit_async(prepared, TaskType.CONVERT)
        return docling_serve_pb2.ConvertSourceAsyncResponse(response=status)

    async def ConvertSourceBatch(
        self,
        request: docling_serve_pb2.ConvertSourceBatchRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ConvertSourceBatchResponse:
        """Mirror POST /v1/convert/source/batch.

        Batch goes through the REST Pydantic request model and the same policy
        helpers (``normalize_request`` + ``validate_batch_convert_request``), then
        the registry-normalized enqueue the REST handler performs.
        """
        await self._check_api_key(context)
        await self._ensure_queue_started()

        empty = docling_serve_pb2.ConvertSourceBatchResponse()
        try:
            batch = to_batch_convert_request(request.request)
        except ValueError as exc:
            await self._abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return empty

        try:
            batch = normalize_request(batch, self._policy)
            validate_batch_convert_request(batch, self._policy)
        except HTTPException as exc:
            await self._abort(
                context, grpc.StatusCode.INVALID_ARGUMENT, str(exc.detail)
            )
            return empty

        try:
            sources = [
                self._policy.source_factory.validate_config(source)
                for source in batch.sources
            ]
            raw_targets = batch.targets or (
                [batch.target] if batch.target is not None else []
            )
            targets = [
                self._policy.target_factory.validate_config(t) for t in raw_targets
            ]
        except (SourceConnectorConfigError, TargetConnectorConfigError) as exc:
            await self._abort(context, grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return empty
        if not targets:
            await self._abort(
                context,
                grpc.StatusCode.INVALID_ARGUMENT,
                "Batch requests require a target or a non-empty targets list.",
            )
            return empty

        task = await self._orchestrator.enqueue(
            task_type=TaskType.CONVERT,
            sources=sources,
            convert_options=batch.options,
            targets=targets,
            callbacks=batch.callbacks,
        )
        position = await self._orchestrator.get_queue_position(task_id=task.task_id)
        self._requested_formats[task.task_id] = requested_output_formats(
            request.request.options if request.request.HasField("options") else None
        )
        return docling_serve_pb2.ConvertSourceBatchResponse(
            response=task_status_to_proto(task, position)
        )

    async def ChunkHierarchicalSource(
        self,
        request: docling_serve_pb2.ChunkHierarchicalSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ChunkHierarchicalSourceResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        response = docling_serve_pb2.ChunkHierarchicalSourceResponse()
        prepared = await self._prepare_chunk(request.request, context, hybrid=False)
        if prepared is None:
            return response
        run = await self._run_sync(
            prepared,
            TaskType.CHUNK,
            context,
            "Chunking is taking too long. Increase DOCLING_SERVE_MAX_SYNC_WAIT.",
        )
        if run is None:
            return response
        task_id, outcome = run
        if not await self._fill_chunk_result(
            response, outcome, prepared.requested_formats, context
        ):
            return response
        with_single_use_cleanup(self._orchestrator, task_id)
        return response

    async def ChunkHybridSource(
        self,
        request: docling_serve_pb2.ChunkHybridSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ChunkHybridSourceResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        response = docling_serve_pb2.ChunkHybridSourceResponse()
        prepared = await self._prepare_chunk(request.request, context, hybrid=True)
        if prepared is None:
            return response
        run = await self._run_sync(
            prepared,
            TaskType.CHUNK,
            context,
            "Chunking is taking too long. Increase DOCLING_SERVE_MAX_SYNC_WAIT.",
        )
        if run is None:
            return response
        task_id, outcome = run
        if not await self._fill_chunk_result(
            response, outcome, prepared.requested_formats, context
        ):
            return response
        with_single_use_cleanup(self._orchestrator, task_id)
        return response

    async def ChunkHierarchicalSourceAsync(
        self,
        request: docling_serve_pb2.ChunkHierarchicalSourceAsyncRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ChunkHierarchicalSourceAsyncResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        prepared = await self._prepare_chunk(request.request, context, hybrid=False)
        if prepared is None:
            return docling_serve_pb2.ChunkHierarchicalSourceAsyncResponse()
        status = await self._submit_async(prepared, TaskType.CHUNK)
        return docling_serve_pb2.ChunkHierarchicalSourceAsyncResponse(response=status)

    async def ChunkHybridSourceAsync(
        self,
        request: docling_serve_pb2.ChunkHybridSourceAsyncRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ChunkHybridSourceAsyncResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        prepared = await self._prepare_chunk(request.request, context, hybrid=True)
        if prepared is None:
            return docling_serve_pb2.ChunkHybridSourceAsyncResponse()
        status = await self._submit_async(prepared, TaskType.CHUNK)
        return docling_serve_pb2.ChunkHybridSourceAsyncResponse(response=status)

    async def PollTaskStatus(
        self,
        request: docling_serve_pb2.PollTaskStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.PollTaskStatusResponse:
        await self._check_api_key(context)

        try:
            task = await self._orchestrator.task_status(
                task_id=request.request.task_id,
                wait=request.request.wait_time,
            )
            position = await self._orchestrator.get_queue_position(
                task_id=request.request.task_id
            )
        except TaskNotFoundError:
            await self._abort(context, grpc.StatusCode.NOT_FOUND, "Task not found.")
            return docling_serve_pb2.PollTaskStatusResponse()

        response = task_status_to_proto(task, position)
        return docling_serve_pb2.PollTaskStatusResponse(response=response)

    async def GetConvertResult(
        self,
        request: docling_serve_pb2.GetConvertResultRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.GetConvertResultResponse:
        await self._check_api_key(context)

        response = docling_serve_pb2.GetConvertResultResponse()
        task_id = request.request.task_id
        outcome = await self._task_outcome(task_id, context)
        if outcome is None:
            return response
        requested_formats = self._requested_formats.pop(task_id, set())
        if not await self._fill_convert_result(
            response, outcome, requested_formats, context
        ):
            return response
        with_single_use_cleanup(self._orchestrator, task_id)
        return response

    async def GetChunkResult(
        self,
        request: docling_serve_pb2.GetChunkResultRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.GetChunkResultResponse:
        await self._check_api_key(context)

        response = docling_serve_pb2.GetChunkResultResponse()
        task_id = request.request.task_id
        outcome = await self._task_outcome(task_id, context)
        if outcome is None:
            return response
        requested_formats = self._requested_formats.pop(task_id, set())
        if not await self._fill_chunk_result(
            response, outcome, requested_formats, context
        ):
            return response
        with_single_use_cleanup(self._orchestrator, task_id)
        return response

    async def ClearConverters(
        self,
        request: docling_serve_pb2.ClearConvertersRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ClearConvertersResponse:
        await self._check_api_key(context)
        await self._orchestrator.clear_converters()
        return docling_serve_pb2.ClearConvertersResponse(
            response=clear_response_to_proto()
        )

    async def ClearResults(
        self,
        request: docling_serve_pb2.ClearResultsRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ClearResultsResponse:
        await self._check_api_key(context)
        older_than = request.older_than if request.HasField("older_than") else 3600
        await self._orchestrator.clear_results(older_than=older_than)
        return docling_serve_pb2.ClearResultsResponse(
            response=clear_response_to_proto()
        )

    async def ConvertSourceStream(
        self,
        request: docling_serve_pb2.ConvertSourceStreamRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_pb2.ConvertSourceStreamResponse]:
        await self._check_api_key(context)

        unary = await self.ConvertSource(
            docling_serve_pb2.ConvertSourceRequest(request=request.request),
            context,
        )
        response = docling_serve_pb2.ConvertSourceStreamResponse()
        arm = unary.WhichOneof("result")
        if arm is not None:
            getattr(response, arm).CopyFrom(getattr(unary, arm))
        yield response

    async def WatchConvertSource(
        self,
        request: docling_serve_pb2.WatchConvertSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_pb2.WatchConvertSourceResponse]:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        prepared = await self._prepare_convert(request.request, context)
        if prepared is None:
            return
        task = await self._enqueue(prepared, TaskType.CONVERT)
        async for status in self._poll_status_stream(task.task_id, context):
            yield docling_serve_pb2.WatchConvertSourceResponse(response=status)

    async def WatchChunkHierarchicalSource(
        self,
        request: docling_serve_pb2.WatchChunkHierarchicalSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_pb2.WatchChunkHierarchicalSourceResponse]:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        prepared = await self._prepare_chunk(request.request, context, hybrid=False)
        if prepared is None:
            return
        task = await self._enqueue(prepared, TaskType.CHUNK)
        async for status in self._poll_status_stream(task.task_id, context):
            yield docling_serve_pb2.WatchChunkHierarchicalSourceResponse(
                response=status
            )

    async def WatchChunkHybridSource(
        self,
        request: docling_serve_pb2.WatchChunkHybridSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_pb2.WatchChunkHybridSourceResponse]:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        prepared = await self._prepare_chunk(request.request, context, hybrid=True)
        if prepared is None:
            return
        task = await self._enqueue(prepared, TaskType.CHUNK)
        async for status in self._poll_status_stream(task.task_id, context):
            yield docling_serve_pb2.WatchChunkHybridSourceResponse(response=status)


class PublicErrorInterceptor(grpc.aio.ServerInterceptor):
    """Catch unhandled exceptions and sanitize details before they reach clients.

    Mirrors the REST layer's use of ``build_public_http_detail``: internal
    exception text is only exposed when ``debug_error_details`` is enabled;
    otherwise clients get a generic message while the full traceback is logged
    server-side. Explicit aborts (policy violations, validation errors) pass
    through untouched. Queue backpressure (REST 503 + Retry-After) maps to
    RESOURCE_EXHAUSTED so clients can back off without parsing text.
    """

    _FALLBACK = "Internal server error."

    async def intercept_service(self, continuation, handler_call_details):
        handler = await continuation(handler_call_details)
        if handler is None:
            return None
        method = handler_call_details.method

        if handler.unary_unary is not None:
            inner_unary = handler.unary_unary

            async def unary_unary(request, context):
                try:
                    return await inner_unary(request, context)
                except grpc.aio.AbortError:
                    raise
                except TaskNotFoundError:
                    await context.abort(grpc.StatusCode.NOT_FOUND, "Task not found.")
                except RedisBackpressureError:
                    await context.abort(
                        grpc.StatusCode.RESOURCE_EXHAUSTED, _BACKPRESSURE_MESSAGE
                    )
                except Exception as exc:
                    _log.exception("Unhandled error in %s", method)
                    await context.abort(
                        grpc.StatusCode.INTERNAL,
                        build_public_http_detail(
                            exc=exc,
                            debug_enabled=docling_serve_settings.debug_error_details,
                            fallback_message=self._FALLBACK,
                        ),
                    )

            return grpc.unary_unary_rpc_method_handler(
                unary_unary,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )

        if handler.unary_stream is not None:
            inner_stream = handler.unary_stream

            async def unary_stream(request, context):
                try:
                    async for item in inner_stream(request, context):
                        yield item
                except grpc.aio.AbortError:
                    raise
                except TaskNotFoundError:
                    await context.abort(grpc.StatusCode.NOT_FOUND, "Task not found.")
                except RedisBackpressureError:
                    await context.abort(
                        grpc.StatusCode.RESOURCE_EXHAUSTED, _BACKPRESSURE_MESSAGE
                    )
                except Exception as exc:
                    _log.exception("Unhandled error in %s", method)
                    await context.abort(
                        grpc.StatusCode.INTERNAL,
                        build_public_http_detail(
                            exc=exc,
                            debug_enabled=docling_serve_settings.debug_error_details,
                            fallback_message=self._FALLBACK,
                        ),
                    )

            return grpc.unary_stream_rpc_method_handler(
                unary_stream,
                request_deserializer=handler.request_deserializer,
                response_serializer=handler.response_serializer,
            )

        return handler


async def serve(host: str, port: int) -> None:
    from grpc_reflection.v1alpha import reflection

    from .schema_validator import (
        validate_docling_document_schema,
        validate_serve_types_schema,
    )

    validate_docling_document_schema()
    validate_serve_types_schema()

    options = [
        ("grpc.max_send_message_length", 2 * 1024 * 1024 * 1024 - 1),  # 2 GB
        ("grpc.max_receive_message_length", 2 * 1024 * 1024 * 1024 - 1),  # 2 GB
    ]
    server = grpc.aio.server(options=options, interceptors=[PublicErrorInterceptor()])
    service = DoclingServeGrpcService()
    await service.start()
    docling_serve_pb2_grpc.add_DoclingServeServiceServicer_to_server(service, server)

    from .gen.ai.docling.serve.v1 import (
        docling_serve_stream_pb2,
        docling_serve_stream_pb2_grpc,
    )
    from .streaming import DoclingStreamingGrpcService

    streaming = DoclingStreamingGrpcService(service)
    docling_serve_stream_pb2_grpc.add_DoclingStreamingServiceServicer_to_server(
        streaming, server
    )

    # Enable gRPC server reflection for grpcurl / client discovery.
    service_names = (
        docling_serve_pb2.DESCRIPTOR.services_by_name["DoclingServeService"].full_name,
        docling_serve_stream_pb2.DESCRIPTOR.services_by_name[
            "DoclingStreamingService"
        ].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)

    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    _log.info("gRPC server started on %s:%s", host, port)
    try:
        await server.wait_for_termination()
    finally:
        await service.close()
