"""Fork-owned document streaming service (DocumentStreamEnvelope).

Phase 1 is honest: status + typed progress events around a real conversion,
then ``final_document`` payload(s). ``DocumentNode`` parts and
``document_completed`` progress are reserved until the pipeline / orchestrator
can emit per-source events — we do not fake them from a finished result.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Iterator

import grpc

from docling.datamodel.service.responses import (
    DocumentResultItem,
    PresignedArtifactResult,
    RemoteTargetResult,
    ZipArchiveResult,
)
from docling_jobkit.datamodel.stored_outcome import (
    StoredFailureOutcome,
    StoredSuccessOutcome,
)
from docling_jobkit.datamodel.task_meta import TaskStatus, TaskType

from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_stream_pb2,
    docling_serve_stream_pb2_grpc,
    docling_serve_types_pb2,
)
from docling_serve.grpc.mapping import (
    UnexpectedResultType,
    document_response_to_proto,
    progress_set_num_docs,
    progress_task_completed,
    progress_update_processed,
    public_failure_to_proto,
    with_single_use_cleanup,
)
from docling_serve.grpc.server import DoclingServeGrpcService, RequestRejected
from docling_serve.settings import docling_serve_settings

_log = logging.getLogger(__name__)

_Code = docling_serve_stream_pb2.StreamErrorCode


class DoclingStreamingGrpcService(
    docling_serve_stream_pb2_grpc.DoclingStreamingServiceServicer
):
    """Server-streaming convert feed owned by this fork."""

    def __init__(self, convert_service: DoclingServeGrpcService) -> None:
        self._convert = convert_service

    def _envelope(
        self,
        *,
        request_id: str | None,
        sequence: int,
        source_index: int | None = None,
        status: docling_serve_stream_pb2.StreamStatus | None = None,
        final_document=None,
        source_result: docling_serve_stream_pb2.StreamSourceResult | None = None,
        error: docling_serve_stream_pb2.StreamError | None = None,
        progress: docling_serve_types_pb2.TaskProgress | None = None,
    ) -> docling_serve_stream_pb2.StreamDocumentResponse:
        msg = docling_serve_stream_pb2.StreamDocumentResponse(
            sequence_number=sequence,
            timestamp_ms=int(time.time() * 1000),
        )
        if request_id:
            msg.request_id = request_id
        if source_index is not None:
            msg.source_index = source_index
        if status is not None:
            msg.status.CopyFrom(status)
        elif final_document is not None:
            msg.final_document.CopyFrom(final_document)
        elif source_result is not None:
            msg.source_result.CopyFrom(source_result)
        elif error is not None:
            msg.error.CopyFrom(error)
        elif progress is not None:
            msg.progress.CopyFrom(progress)
        return msg

    @staticmethod
    def _error(
        code: int, message: str, *, terminal: bool = True, failure=None
    ) -> docling_serve_stream_pb2.StreamError:
        err = docling_serve_stream_pb2.StreamError(
            code=code, message=message, terminal=terminal
        )
        if failure is not None:
            err.failure.CopyFrom(public_failure_to_proto(failure))
        return err

    def _result_envelopes(
        self,
        result,
        requested_formats,
        request_id: str | None,
        next_seq: Callable[[], int],
    ) -> Iterator[docling_serve_stream_pb2.StreamDocumentResponse]:
        """Yield the per-result payload envelopes for a successful task.

        Dispatches on the typed ``DoclingTaskResult.result`` union: in-body
        documents are streamed as source_result + final_document; presigned
        artifacts report per-source outcomes (ArtifactRefs are fetched via
        GetConvertResult); zip / remote targets carry no in-band payload.
        """
        if isinstance(result, DocumentResultItem):
            doc_proto = document_response_to_proto(result.document, requested_formats)
            has_doc = doc_proto.HasField("doc")
            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                source_index=0,
                source_result=docling_serve_stream_pb2.StreamSourceResult(
                    source_index=0,
                    filename=doc_proto.filename or "",
                    success=True,
                    document_name=doc_proto.doc.name if has_doc else "",
                ),
            )
            if has_doc:
                yield self._envelope(
                    request_id=request_id,
                    sequence=next_seq(),
                    source_index=0,
                    final_document=doc_proto.doc,
                )
        elif isinstance(result, PresignedArtifactResult):
            for item in result.documents:
                source_result = docling_serve_stream_pb2.StreamSourceResult(
                    source_index=item.source_index,
                    filename=item.filename,
                    success=not item.errors,
                )
                if item.errors:
                    source_result.error_message = item.errors[0].error_message
                yield self._envelope(
                    request_id=request_id,
                    sequence=next_seq(),
                    source_index=item.source_index,
                    source_result=source_result,
                )
        elif not isinstance(result, (ZipArchiveResult, RemoteTargetResult)):
            raise UnexpectedResultType(
                f"Unexpected result type {type(result).__name__}."
            )

    async def StreamDocument(
        self,
        request: docling_serve_stream_pb2.StreamDocumentRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_stream_pb2.StreamDocumentResponse]:
        await self._convert._check_api_key(context)
        await self._convert._ensure_queue_started()

        request_id = request.request_id if request.HasField("request_id") else None
        seq = 0

        def next_seq() -> int:
            nonlocal seq
            seq += 1
            return seq

        yield self._envelope(
            request_id=request_id,
            sequence=next_seq(),
            status=docling_serve_stream_pb2.StreamStatus(
                phase=docling_serve_stream_pb2.StreamStatus.PHASE_QUEUED,
                message="queued",
            ),
        )

        # Validation failures are reported on the stream (not as an abort) so
        # the envelope stays the single channel clients read.
        try:
            prepared = self._convert.build_convert(request.request)
        except RequestRejected as exc:
            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                error=self._error(_Code.STREAM_ERROR_CODE_INVALID_ARGUMENT, str(exc)),
            )
            return

        sources = prepared.sources
        yield self._envelope(
            request_id=request_id,
            sequence=next_seq(),
            status=docling_serve_stream_pb2.StreamStatus(
                phase=docling_serve_stream_pb2.StreamStatus.PHASE_STARTED,
                message="started",
                num_docs=len(sources),
            ),
        )
        yield self._envelope(
            request_id=request_id,
            sequence=next_seq(),
            progress=progress_set_num_docs(len(sources)),
        )

        task = await self._convert._enqueue(prepared, TaskType.CONVERT)

        # Phase 1: poll for status updates (same honesty as Watch*), emitting a
        # typed update_processed whenever the orchestrator counters move, then
        # the final payload(s). DocumentNode parts wait for pipeline hooks.
        last_meta = None
        task_status = None
        while not context.done():
            task_status = await self._convert._orchestrator.task_status(
                task_id=task.task_id
            )
            position = await self._convert._orchestrator.get_queue_position(
                task_id=task.task_id
            )
            meta = task_status.processing_meta
            status_kwargs: dict = {
                "phase": docling_serve_stream_pb2.StreamStatus.PHASE_PROCESSING,
                "message": task_status.task_status.value,
            }
            if position is not None:
                status_kwargs["queue_position"] = int(position)
            if meta is not None:
                status_kwargs.update(
                    num_docs=meta.num_docs,
                    num_processed=meta.num_processed,
                    num_succeeded=meta.num_succeeded,
                    num_partially_succeeded=meta.num_partially_succeeded,
                    num_failed=meta.num_failed,
                )
                if meta.num_docs > 0:
                    status_kwargs["progress_percentage"] = float(
                        meta.num_processed
                    ) / float(meta.num_docs)

            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                status=docling_serve_stream_pb2.StreamStatus(**status_kwargs),
            )
            if meta is not None and meta != last_meta:
                last_meta = meta.model_copy()
                yield self._envelope(
                    request_id=request_id,
                    sequence=next_seq(),
                    progress=progress_update_processed(meta),
                )

            if task_status.is_completed():
                break
            await asyncio.sleep(docling_serve_settings.sync_poll_interval)
        else:
            return

        outcome = await self._convert._orchestrator.task_outcome(task_id=task.task_id)
        if outcome is None:
            outcome = await self._convert._failure_from_task_status(task.task_id)
        if outcome is None:
            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                error=self._error(
                    _Code.STREAM_ERROR_CODE_NOT_FOUND, "Task result not found."
                ),
            )
            return
        if isinstance(outcome, StoredSuccessOutcome):
            outcome = outcome.result

        if isinstance(outcome, StoredFailureOutcome) or (
            task_status is not None and task_status.task_status == TaskStatus.FAILURE
        ):
            failure = (
                outcome.failure
                if isinstance(outcome, StoredFailureOutcome)
                else task_status.failure
            )
            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                progress=progress_task_completed(task_status),
            )
            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                error=self._error(
                    _Code.STREAM_ERROR_CODE_CONVERT_FAILED,
                    (failure.message if failure is not None else None)
                    or task_status.error_message
                    or "Conversion failed.",
                    failure=failure,
                ),
            )
            return

        try:
            for envelope in self._result_envelopes(
                outcome.result, prepared.requested_formats, request_id, next_seq
            ):
                yield envelope
        except UnexpectedResultType as exc:
            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                error=self._error(_Code.STREAM_ERROR_CODE_INTERNAL, str(exc)),
            )
            return

        yield self._envelope(
            request_id=request_id,
            sequence=next_seq(),
            progress=progress_task_completed(task_status),
        )
        yield self._envelope(
            request_id=request_id,
            sequence=next_seq(),
            status=docling_serve_stream_pb2.StreamStatus(
                phase=docling_serve_stream_pb2.StreamStatus.PHASE_COMPLETED,
                message="completed",
                progress_percentage=1.0,
                num_docs=len(sources),
                num_processed=outcome.num_converted,
                num_succeeded=outcome.num_succeeded,
                num_partially_succeeded=outcome.num_partially_succeeded,
                num_failed=outcome.num_failed,
            ),
        )

        with_single_use_cleanup(self._convert._orchestrator, task.task_id)
        _log.info(
            "StreamDocument finished request_id=%s sequences=%s",
            request_id,
            seq,
        )
