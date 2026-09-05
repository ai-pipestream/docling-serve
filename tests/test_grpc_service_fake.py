import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import replace

import grpc
import pytest
import pytest_asyncio

from docling.datamodel.base_models import ConversionStatus, ErrorItem
from docling.datamodel.document import DoclingComponentType
from docling.datamodel.service.responses import (
    ArtifactRef,
    ConfidenceScores,
    DocumentArtifactItem,
    FailureCategory,
    FailurePhase,
    PresignedArtifactResult,
    PublicFailureInfo,
    QualityGrade,
    RemoteTargetResult,
    ZipArchiveResult,
)
from docling_core.types.doc.document import DoclingDocument
from docling_jobkit.datamodel.result import (
    ChunkedDocumentResult,
    ChunkedDocumentResultItem,
    DoclingTaskResult,
    ExportDocumentResponse,
    ExportResult,
)
from docling_jobkit.datamodel.stored_outcome import StoredFailureOutcome
from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskProcessingMeta, TaskStatus, TaskType
from docling_jobkit.orchestrators.base_orchestrator import (
    RedisBackpressureError,
    TaskNotFoundError,
)

from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2,
    docling_serve_pb2_grpc,
    docling_serve_stream_pb2,
    docling_serve_stream_pb2_grpc,
    docling_serve_types_pb2,
)
from docling_serve.grpc.server import DoclingServeGrpcService, PublicErrorInterceptor
from docling_serve.grpc.streaming import DoclingStreamingGrpcService
from docling_serve.policy import build_service_policy
from docling_serve.settings import docling_serve_settings

pytestmark = pytest.mark.unit


def _fake_docling_document() -> DoclingDocument:
    return DoclingDocument(name="doc")


class FakeOrchestrator:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.results: dict[str, DoclingTaskResult] = {}
        # Task-scope failures persisted as stored outcomes (Redis/RQ style).
        self.failures: dict[str, StoredFailureOutcome] = {}
        self.positions: dict[str, int] = {}
        self.enqueue_kwargs: list[dict] = []
        self.cleared_converters = False
        self.cleared_results: list[float] = []
        self.deleted_tasks: list[str] = []
        self._stop = asyncio.Event()
        self._counter = 0

    async def warm_up_caches(self) -> None:
        return

    async def process_queue(self) -> None:
        await self._stop.wait()

    async def enqueue(
        self,
        *,
        task_type,
        sources,
        convert_options,
        target=None,
        targets=None,
        callbacks=None,
        **kwargs,
    ) -> Task:
        self._counter += 1
        task_id = f"task-{self._counter}"
        self.enqueue_kwargs.append(
            {
                "task_type": task_type,
                "sources": sources,
                "target": target,
                "targets": targets,
                "callbacks": callbacks,
                **kwargs,
            }
        )
        task = Task(
            task_id=task_id,
            task_type=task_type,
            task_status=TaskStatus.SUCCESS,
            sources=sources,
            target=target,
            targets=targets,
            convert_options=convert_options,
            callbacks=callbacks or [],
        )
        self.tasks[task_id] = task
        self.positions[task_id] = 0
        if task_type == TaskType.CONVERT:
            export = ExportResult(
                content=ExportDocumentResponse(
                    filename="doc.md",
                    md_content="hello",
                    json_content=_fake_docling_document(),
                ),
                status=ConversionStatus.SUCCESS,
            )
            self.results[task_id] = DoclingTaskResult(
                result=export,
                processing_time=0.1,
                num_converted=1,
                num_succeeded=1,
                num_failed=0,
            )
        return task

    async def task_status(self, *, task_id: str, wait: float | None = None) -> Task:
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise TaskNotFoundError(task_id) from exc

    async def get_queue_position(self, *, task_id: str) -> int:
        return self.positions.get(task_id, 0)

    async def task_result(self, *, task_id: str):
        return self.results.get(task_id)

    async def task_outcome(self, *, task_id: str):
        if task_id in self.failures:
            return self.failures[task_id]
        return self.results.get(task_id)

    async def clear_converters(self) -> None:
        self.cleared_converters = True

    async def clear_results(self, *, older_than: float) -> None:
        self.cleared_results.append(older_than)

    async def delete_task(self, *, task_id: str) -> None:
        self.deleted_tasks.append(task_id)


@pytest_asyncio.fixture
async def grpc_server():
    original_single_use = docling_serve_settings.single_use_results
    docling_serve_settings.single_use_results = False
    options = [
        ("grpc.max_send_message_length", 50 * 1024 * 1024),
        ("grpc.max_receive_message_length", 50 * 1024 * 1024),
    ]
    server = grpc.aio.server(options=options)
    orchestrator = FakeOrchestrator()
    service = DoclingServeGrpcService(orchestrator=orchestrator)
    await service.start()
    docling_serve_pb2_grpc.add_DoclingServeServiceServicer_to_server(service, server)
    docling_serve_stream_pb2_grpc.add_DoclingStreamingServiceServicer_to_server(
        DoclingStreamingGrpcService(service), server
    )

    port = server.add_insecure_port("[::]:0")
    await server.start()

    yield {"address": f"localhost:{port}", "orchestrator": orchestrator}

    await service.close()
    docling_serve_settings.single_use_results = original_single_use
    await server.stop(grace=1)


@pytest_asyncio.fixture
async def grpc_channel(grpc_server):
    options = [
        ("grpc.max_send_message_length", 50 * 1024 * 1024),
        ("grpc.max_receive_message_length", 50 * 1024 * 1024),
    ]
    async with grpc.aio.insecure_channel(
        grpc_server["address"], options=options
    ) as channel:
        yield channel


@pytest_asyncio.fixture
async def grpc_stub(grpc_channel):
    return docling_serve_pb2_grpc.DoclingServeServiceStub(grpc_channel)


@pytest_asyncio.fixture
async def streaming_stub(grpc_channel):
    return docling_serve_stream_pb2_grpc.DoclingStreamingServiceStub(grpc_channel)


@pytest.fixture
def orchestrator(grpc_server):
    return grpc_server["orchestrator"]


@pytest.mark.asyncio
async def test_health_returns_version(grpc_stub):
    """Health RPC returns status and version."""
    response = await grpc_stub.Health(docling_serve_pb2.HealthRequest())
    assert response.status == "ok"
    assert response.HasField("version")
    # When installed via uv/pip, version is e.g. "1.12.0"; fallback is "0.0.0"
    assert isinstance(response.version, str) and len(response.version) > 0


@pytest.mark.asyncio
async def test_stream_document_emits_status_and_final(streaming_stub):
    """Phase-1 StreamDocument: status envelopes then final_document (no fake parts)."""
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_stream_pb2.StreamDocumentRequest(
        request_id="studio-poc-1",
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="stream.pdf",
                    )
                )
            ]
        ),
    )

    envelopes = []
    async for envelope in streaming_stub.StreamDocument(request):
        envelopes.append(envelope)

    assert envelopes, "expected at least one envelope"
    assert envelopes[0].request_id == "studio-poc-1"
    assert envelopes[0].sequence_number == 1
    assert envelopes[0].WhichOneof("payload") == "status"

    kinds = [e.WhichOneof("payload") for e in envelopes]
    assert "status" in kinds
    assert "source_result" in kinds
    assert "final_document" in kinds
    assert "part" not in kinds  # Phase 3 reserved — must not fake item yields

    finals = [e for e in envelopes if e.WhichOneof("payload") == "final_document"]
    assert len(finals) == 1
    assert finals[0].final_document.name == "doc"

    sequences = [e.sequence_number for e in envelopes]
    assert sequences == sorted(sequences)
    assert sequences == list(range(1, len(sequences) + 1))

    last = envelopes[-1]
    assert last.WhichOneof("payload") == "status"
    assert last.status.phase == docling_serve_stream_pb2.StreamStatus.PHASE_COMPLETED

    # Typed progress kinds mirror docling's ProgressCallbackRequest union.
    progress_kinds = [
        e.progress.WhichOneof("progress") for e in envelopes if e.HasField("progress")
    ]
    assert progress_kinds[0] == "set_num_docs"
    assert progress_kinds[-1] == "task_completed"
    set_num_docs = next(e for e in envelopes if e.HasField("progress")).progress
    assert set_num_docs.set_num_docs.num_docs == 1
    completed = [e for e in envelopes if e.HasField("progress")][-1].progress
    assert (
        completed.task_completed.task_status
        == docling_serve_types_pb2.TASK_STATUS_SUCCESS
    )
    assert not completed.task_completed.HasField("failure")
    assert "document_completed" not in progress_kinds  # Phase 2 reserved


@pytest.mark.asyncio
async def test_stream_document_invalid_request_yields_typed_error(streaming_stub):
    """Validation failures arrive as a StreamError envelope with an enum code."""
    request = docling_serve_stream_pb2.StreamDocumentRequest(
        request_id="bad-1",
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[docling_serve_types_pb2.Source()]
        ),
    )

    envelopes = [e async for e in streaming_stub.StreamDocument(request)]

    assert envelopes[0].WhichOneof("payload") == "status"
    last = envelopes[-1]
    assert last.WhichOneof("payload") == "error"
    assert (
        last.error.code == docling_serve_stream_pb2.STREAM_ERROR_CODE_INVALID_ARGUMENT
    )
    assert last.error.terminal is True
    assert "no variant set" in last.error.message
    assert not last.error.HasField("failure")


@pytest.mark.asyncio
async def test_stream_document_task_failure_yields_convert_failed():
    """A failed task ends the stream with CONVERT_FAILED + PublicFailureInfo."""
    request = docling_serve_stream_pb2.StreamDocumentRequest(
        request_id="fail-1", request=_dummy_convert_request()
    )
    async with _server_with(orchestrator=FailingTaskOrchestrator(), streaming=True) as (
        _,
        streaming_stub,
    ):
        envelopes = [e async for e in streaming_stub.StreamDocument(request)]

    last = envelopes[-1]
    assert last.WhichOneof("payload") == "error"
    assert last.error.code == docling_serve_stream_pb2.STREAM_ERROR_CODE_CONVERT_FAILED
    assert last.error.message == "onnxruntime is not installed."
    assert (
        last.error.failure.category
        == docling_serve_types_pb2.FAILURE_CATEGORY_BACKEND_FAILURE
    )
    completed = [e for e in envelopes if e.HasField("progress")][-1].progress
    assert (
        completed.task_completed.task_status
        == docling_serve_types_pb2.TASK_STATUS_FAILURE
    )
    assert completed.task_completed.failure.message == "onnxruntime is not installed."
    assert not any(e.HasField("final_document") for e in envelopes)


@pytest.mark.asyncio
async def test_convert_source_empty_sources_invalid_argument(grpc_stub):
    """ConvertSource with empty sources list fails with INVALID_ARGUMENT."""
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.ConvertSource(
            docling_serve_pb2.ConvertSourceRequest(
                request=docling_serve_types_pb2.ConvertDocumentRequest(sources=[])
            )
        )
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_get_convert_result(grpc_stub, orchestrator):
    task_id = "convert-1"
    export = ExportResult(
        content=ExportDocumentResponse(
            filename="doc.md",
            md_content="hello",
            json_content=_fake_docling_document(),
        ),
        status=ConversionStatus.SUCCESS,
    )
    orchestrator.results[task_id] = DoclingTaskResult(
        result=export,
        processing_time=0.5,
        num_converted=1,
        num_succeeded=1,
        num_failed=0,
    )

    response = await grpc_stub.GetConvertResult(
        docling_serve_pb2.GetConvertResultRequest(
            request=docling_serve_types_pb2.TaskResultRequest(task_id=task_id)
        )
    )

    assert not response.response.document.HasField("exports")
    assert response.response.document.doc.schema_name == "DoclingDocument"
    assert response.WhichOneof("result") == "response"


def _failure(message="boom") -> PublicFailureInfo:
    return PublicFailureInfo(
        category=FailureCategory.SOURCE_UNAVAILABLE,
        message=message,
        retryable=True,
        phase=FailurePhase.SOURCE_ENUMERATION,
        details={"source": "s3://bucket/key"},
    )


@pytest.mark.asyncio
async def test_get_convert_result_failure_arm(grpc_stub, orchestrator):
    """A stored task-scope failure is returned on the `failure` oneof arm."""
    orchestrator.failures["convert-failed"] = StoredFailureOutcome(failure=_failure())

    response = await grpc_stub.GetConvertResult(
        docling_serve_pb2.GetConvertResultRequest(
            request=docling_serve_types_pb2.TaskResultRequest(task_id="convert-failed")
        )
    )

    assert response.WhichOneof("result") == "failure"
    failure = response.failure.failure
    assert (
        failure.category == docling_serve_types_pb2.FAILURE_CATEGORY_SOURCE_UNAVAILABLE
    )
    assert failure.phase == docling_serve_types_pb2.FAILURE_PHASE_SOURCE_ENUMERATION
    assert failure.message == "boom"
    assert failure.retryable is True
    assert dict(failure.details) == {"source": "s3://bucket/key"}
    assert not failure.HasField("category_raw")


@pytest.mark.asyncio
async def test_get_convert_result_zip_arm(grpc_stub, orchestrator):
    orchestrator.results["zip-1"] = DoclingTaskResult(
        result=ZipArchiveResult(content=b"PK\x03\x04zip"),
        processing_time=0.3,
        num_converted=2,
        num_succeeded=2,
        num_failed=0,
    )

    response = await grpc_stub.GetConvertResult(
        docling_serve_pb2.GetConvertResultRequest(
            request=docling_serve_types_pb2.TaskResultRequest(task_id="zip-1")
        )
    )

    assert response.WhichOneof("result") == "zip_archive"
    assert response.zip_archive.content == b"PK\x03\x04zip"


@pytest.mark.asyncio
async def test_get_convert_result_remote_target_arm(grpc_stub, orchestrator):
    orchestrator.results["remote-1"] = DoclingTaskResult(
        result=RemoteTargetResult(),
        processing_time=1.5,
        num_converted=3,
        num_succeeded=1,
        num_partially_succeeded=1,
        num_failed=1,
    )

    response = await grpc_stub.GetConvertResult(
        docling_serve_pb2.GetConvertResultRequest(
            request=docling_serve_types_pb2.TaskResultRequest(task_id="remote-1")
        )
    )

    assert response.WhichOneof("result") == "remote_target"
    remote = response.remote_target
    assert remote.num_converted == 3
    assert remote.num_succeeded == 1
    assert remote.num_partially_succeeded == 1
    assert remote.num_failed == 1
    assert remote.processing_time == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_get_convert_result_presigned_artifacts_arm(grpc_stub, orchestrator):
    """Presigned results carry typed ArtifactRef / ConfidenceScores / ErrorItem."""
    from datetime import datetime, timezone

    expires = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    item = DocumentArtifactItem(
        source_index=0,
        source_uri="s3://in/doc.pdf",
        filename="doc.pdf",
        status=ConversionStatus.PARTIAL_SUCCESS,
        errors=[
            ErrorItem(
                component_type=DoclingComponentType.MODEL,
                module_name="ocr",
                error_message="page skipped",
                category=FailureCategory.INFERENCE_FAILURE,
                page_no=3,
            )
        ],
        artifacts=[
            ArtifactRef(
                artifact_type="json",
                mime_type="application/json",
                uri="https://example.com/doc.json?sig=abc",
                url_expires_at=expires,
            ),
            ArtifactRef(
                artifact_type="resource_bundle",
                mime_type="application/zip",
                uri="https://example.com/doc.zip",
            ),
        ],
        confidence=ConfidenceScores(
            parse_score=0.9,
            mean_score=0.8,
            low_score=0.4,
            mean_grade=QualityGrade.GOOD,
            low_grade=QualityGrade.POOR,
        ),
    )
    orchestrator.results["presigned-1"] = DoclingTaskResult(
        result=PresignedArtifactResult(documents=[item]),
        processing_time=2.0,
        num_converted=1,
        num_succeeded=0,
        num_partially_succeeded=1,
        num_failed=0,
    )

    response = await grpc_stub.GetConvertResult(
        docling_serve_pb2.GetConvertResultRequest(
            request=docling_serve_types_pb2.TaskResultRequest(task_id="presigned-1")
        )
    )

    assert response.WhichOneof("result") == "presigned_artifacts"
    result = response.presigned_artifacts
    assert result.num_partially_succeeded == 1
    [doc] = result.documents
    assert doc.source_uri == "s3://in/doc.pdf"
    assert doc.status == docling_serve_types_pb2.CONVERSION_STATUS_PARTIAL_SUCCESS

    [error] = doc.errors
    assert error.component_type == docling_serve_types_pb2.DOCLING_COMPONENT_TYPE_MODEL
    assert error.category == docling_serve_types_pb2.FAILURE_CATEGORY_INFERENCE_FAILURE
    assert error.page_no == 3

    json_ref, bundle_ref = doc.artifacts
    assert json_ref.artifact_type == docling_serve_types_pb2.ARTIFACT_TYPE_JSON
    assert json_ref.uri == "https://example.com/doc.json?sig=abc"
    assert json_ref.url_expires_at == expires.isoformat()
    assert (
        bundle_ref.artifact_type
        == docling_serve_types_pb2.ARTIFACT_TYPE_RESOURCE_BUNDLE
    )
    assert not bundle_ref.HasField("url_expires_at")

    assert doc.HasField("confidence")
    assert doc.confidence.parse_score == pytest.approx(0.9)
    assert not doc.confidence.HasField("ocr_score")
    assert doc.confidence.mean_grade == docling_serve_types_pb2.QUALITY_GRADE_GOOD
    assert doc.confidence.low_grade == docling_serve_types_pb2.QUALITY_GRADE_POOR


class FailingTaskOrchestrator(FakeOrchestrator):
    """Local-orchestrator style: failure lives on the task, no stored outcome."""

    async def enqueue(self, **kwargs) -> Task:
        task = await super().enqueue(**kwargs)
        self.results.pop(task.task_id, None)
        task.task_status = TaskStatus.FAILURE
        task.error_message = "onnxruntime is not installed."
        task.failure = PublicFailureInfo(
            category=FailureCategory.BACKEND_FAILURE,
            message="onnxruntime is not installed.",
            retryable=False,
            phase=FailurePhase.EXECUTION,
        )
        return task


@pytest.mark.asyncio
async def test_convert_source_sync_task_failure_uses_failure_arm():
    """Sync convert on a failed task returns `failure`, not NOT_FOUND."""
    async with _server_with(orchestrator=FailingTaskOrchestrator()) as stub:
        response = await stub.ConvertSource(_file_convert_request())

    assert response.WhichOneof("result") == "failure"
    failure = response.failure.failure
    assert failure.category == docling_serve_types_pb2.FAILURE_CATEGORY_BACKEND_FAILURE
    assert failure.phase == docling_serve_types_pb2.FAILURE_PHASE_EXECUTION
    assert failure.message == "onnxruntime is not installed."


@pytest.mark.asyncio
async def test_get_convert_result_not_found(grpc_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.GetConvertResult(
            docling_serve_pb2.GetConvertResultRequest(
                request=docling_serve_types_pb2.TaskResultRequest(task_id="missing")
            )
        )

    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_get_chunk_result(grpc_stub, orchestrator):
    task_id = "chunk-1"
    chunk = ChunkedDocumentResultItem(
        filename="doc.md",
        chunk_index=0,
        text="chunk text",
        doc_items=[],
    )
    doc_export = ExportResult(
        content=ExportDocumentResponse(
            filename="doc.md",
            md_content="hello",
            json_content=_fake_docling_document(),
        ),
        status=ConversionStatus.SUCCESS,
    )
    chunked = ChunkedDocumentResult(
        chunks=[chunk],
        documents=[doc_export],
    )
    orchestrator.results[task_id] = DoclingTaskResult(
        result=chunked,
        processing_time=0.2,
        num_converted=1,
        num_succeeded=1,
        num_failed=0,
    )

    response = await grpc_stub.GetChunkResult(
        docling_serve_pb2.GetChunkResultRequest(
            request=docling_serve_types_pb2.TaskResultRequest(task_id=task_id)
        )
    )

    assert len(response.response.chunks) == 1
    assert response.response.chunks[0].text == "chunk text"
    assert response.response.documents[0].content.doc.schema_name == "DoclingDocument"


@pytest.mark.asyncio
async def test_get_chunk_result_not_found(grpc_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.GetChunkResult(
            docling_serve_pb2.GetChunkResultRequest(
                request=docling_serve_types_pb2.TaskResultRequest(task_id="missing")
            )
        )

    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_poll_task_status(grpc_stub, orchestrator):
    task_id = "status-1"
    orchestrator.tasks[task_id] = Task(
        task_id=task_id,
        task_type=TaskType.CONVERT,
        task_status=TaskStatus.STARTED,
        sources=[],
        processing_meta=TaskProcessingMeta(num_docs=1),
    )

    response = await grpc_stub.PollTaskStatus(
        docling_serve_pb2.PollTaskStatusRequest(
            request=docling_serve_types_pb2.TaskStatusPollRequest(task_id=task_id)
        )
    )

    assert response.response.task_status == docling_serve_types_pb2.TASK_STATUS_STARTED
    assert response.response.task_meta.num_docs == 1
    assert response.response.task_type == docling_serve_types_pb2.TASK_TYPE_CONVERT
    assert not response.response.HasField("task_type_raw")
    assert not response.response.HasField("error_message")
    assert not response.response.HasField("failure")


@pytest.mark.asyncio
async def test_poll_task_status_failure_fields(grpc_stub, orchestrator):
    """Failed tasks surface error_message, typed failure and partial counters."""
    task_id = "status-failed"
    orchestrator.tasks[task_id] = Task(
        task_id=task_id,
        task_type=TaskType.CHUNK,
        task_status=TaskStatus.FAILURE,
        sources=[],
        processing_meta=TaskProcessingMeta(
            num_docs=4,
            num_processed=4,
            num_succeeded=1,
            num_partially_succeeded=2,
            num_failed=1,
        ),
        error_message="chunker exploded",
        failure=_failure("chunker exploded"),
    )

    response = await grpc_stub.PollTaskStatus(
        docling_serve_pb2.PollTaskStatusRequest(
            request=docling_serve_types_pb2.TaskStatusPollRequest(task_id=task_id)
        )
    )

    status = response.response
    assert status.task_status == docling_serve_types_pb2.TASK_STATUS_FAILURE
    assert status.task_type == docling_serve_types_pb2.TASK_TYPE_CHUNK
    assert status.error_message == "chunker exploded"
    assert status.task_meta.num_partially_succeeded == 2
    assert status.HasField("failure")
    assert (
        status.failure.category
        == docling_serve_types_pb2.FAILURE_CATEGORY_SOURCE_UNAVAILABLE
    )
    assert status.failure.message == "chunker exploded"


@pytest.mark.asyncio
async def test_get_chunk_result_metadata_is_typed_scalar_map(grpc_stub, orchestrator):
    """Chunk.metadata is flattened into map<string, ScalarValue>, not stringified."""
    task_id = "chunk-meta"
    chunk = ChunkedDocumentResultItem(
        filename="doc.md",
        chunk_index=0,
        text="chunk text",
        doc_items=[],
        metadata={
            "origin": {
                "filename": "doc.pdf",
                "binary_hash": 2**63 + 17,
                "mimetype": "application/pdf",
            },
            "is_table": False,
            "score": 0.75,
            "page": 2,
        },
    )
    orchestrator.results[task_id] = DoclingTaskResult(
        result=ChunkedDocumentResult(chunks=[chunk], documents=[]),
        processing_time=0.2,
        num_converted=1,
        num_succeeded=1,
        num_failed=0,
    )

    response = await grpc_stub.GetChunkResult(
        docling_serve_pb2.GetChunkResultRequest(
            request=docling_serve_types_pb2.TaskResultRequest(task_id=task_id)
        )
    )

    assert response.WhichOneof("result") == "response"
    [proto_chunk] = response.response.chunks
    meta = proto_chunk.metadata
    assert meta["origin.filename"].WhichOneof("kind") == "string_value"
    assert meta["origin.filename"].string_value == "doc.pdf"
    assert meta["origin.binary_hash"].WhichOneof("kind") == "uint_value"
    assert meta["origin.binary_hash"].uint_value == 2**63 + 17
    assert meta["is_table"].WhichOneof("kind") == "bool_value"
    assert meta["is_table"].bool_value is False
    assert meta["score"].WhichOneof("kind") == "double_value"
    assert meta["score"].double_value == pytest.approx(0.75)
    assert meta["page"].WhichOneof("kind") == "int_value"
    assert meta["page"].int_value == 2


@pytest.mark.asyncio
async def test_get_chunk_result_failure_arm(grpc_stub, orchestrator):
    orchestrator.failures["chunk-failed"] = StoredFailureOutcome(failure=_failure())

    response = await grpc_stub.GetChunkResult(
        docling_serve_pb2.GetChunkResultRequest(
            request=docling_serve_types_pb2.TaskResultRequest(task_id="chunk-failed")
        )
    )

    assert response.WhichOneof("result") == "failure"
    assert response.failure.failure.message == "boom"


@pytest.mark.asyncio
async def test_poll_task_status_not_found(grpc_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.PollTaskStatus(
            docling_serve_pb2.PollTaskStatusRequest(
                request=docling_serve_types_pb2.TaskStatusPollRequest(task_id="missing")
            )
        )
    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_poll_task_status_empty_task_id_not_found(grpc_stub):
    """PollTaskStatus with empty task_id returns NOT_FOUND."""
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.PollTaskStatus(
            docling_serve_pb2.PollTaskStatusRequest(
                request=docling_serve_types_pb2.TaskStatusPollRequest(task_id="")
            )
        )
    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_clear_results_and_converters(grpc_stub, orchestrator):
    response = await grpc_stub.ClearResults(
        docling_serve_pb2.ClearResultsRequest(older_than=12)
    )
    assert response.response.status == "ok"
    assert orchestrator.cleared_results == [12]

    response = await grpc_stub.ClearConverters(
        docling_serve_pb2.ClearConvertersRequest()
    )
    assert response.response.status == "ok"
    assert orchestrator.cleared_converters is True


@pytest.mark.asyncio
async def test_watch_convert_source(grpc_stub):
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_pb2.WatchConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    )
                )
            ]
        )
    )

    async for response in grpc_stub.WatchConvertSource(request):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break


@pytest.mark.asyncio
async def test_watch_chunk_hierarchical_source(grpc_stub):
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_pb2.WatchChunkHierarchicalSourceRequest(
        request=docling_serve_types_pb2.HierarchicalChunkRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    )
                )
            ],
            chunking_options=docling_serve_types_pb2.HierarchicalChunkerOptions(
                use_markdown_tables=True,
                include_raw_text=False,
            ),
        )
    )

    async for response in grpc_stub.WatchChunkHierarchicalSource(request):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break


@pytest.mark.asyncio
async def test_watch_chunk_hybrid_source(grpc_stub):
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_pb2.WatchChunkHybridSourceRequest(
        request=docling_serve_types_pb2.HybridChunkRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    )
                )
            ],
            chunking_options=docling_serve_types_pb2.HybridChunkerOptions(
                use_markdown_tables=True,
                include_raw_text=False,
                max_tokens=64,
            ),
        )
    )

    async for response in grpc_stub.WatchChunkHybridSource(request):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break


@pytest.mark.asyncio
async def test_convert_source_stream(grpc_stub):
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_pb2.ConvertSourceStreamRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    )
                )
            ]
        )
    )

    responses = [response async for response in grpc_stub.ConvertSourceStream(request)]
    assert len(responses) == 1
    assert responses[0].response.HasField("document")


# --------------- API key enforcement for streaming RPCs ---------------


@pytest_asyncio.fixture
async def api_key_server():
    """Server with API key required."""
    original_key = docling_serve_settings.api_key
    docling_serve_settings.api_key = "test-secret-key"
    original_single_use = docling_serve_settings.single_use_results
    docling_serve_settings.single_use_results = False

    options = [
        ("grpc.max_send_message_length", 50 * 1024 * 1024),
        ("grpc.max_receive_message_length", 50 * 1024 * 1024),
    ]
    server = grpc.aio.server(options=options)
    orchestrator = FakeOrchestrator()
    service = DoclingServeGrpcService(orchestrator=orchestrator)
    await service.start()
    docling_serve_pb2_grpc.add_DoclingServeServiceServicer_to_server(service, server)

    port = server.add_insecure_port("[::]:0")
    await server.start()

    yield f"localhost:{port}"

    await service.close()
    await server.stop(grace=1)
    docling_serve_settings.api_key = original_key
    docling_serve_settings.single_use_results = original_single_use


@pytest_asyncio.fixture
async def api_key_stub(api_key_server):
    options = [
        ("grpc.max_send_message_length", 50 * 1024 * 1024),
        ("grpc.max_receive_message_length", 50 * 1024 * 1024),
    ]
    async with grpc.aio.insecure_channel(api_key_server, options=options) as channel:
        yield docling_serve_pb2_grpc.DoclingServeServiceStub(channel)


def _dummy_convert_request():
    return docling_serve_types_pb2.ConvertDocumentRequest(
        sources=[
            docling_serve_types_pb2.Source(
                file=docling_serve_types_pb2.FileSource(
                    base64_string=base64.b64encode(b"dummy").decode("utf-8"),
                    filename="test.pdf",
                )
            )
        ]
    )


def _dummy_hierarchical_request():
    return docling_serve_types_pb2.HierarchicalChunkRequest(
        sources=[
            docling_serve_types_pb2.Source(
                file=docling_serve_types_pb2.FileSource(
                    base64_string=base64.b64encode(b"dummy").decode("utf-8"),
                    filename="test.pdf",
                )
            )
        ],
    )


def _dummy_hybrid_request():
    return docling_serve_types_pb2.HybridChunkRequest(
        sources=[
            docling_serve_types_pb2.Source(
                file=docling_serve_types_pb2.FileSource(
                    base64_string=base64.b64encode(b"dummy").decode("utf-8"),
                    filename="test.pdf",
                )
            )
        ],
    )


@pytest.mark.asyncio
async def test_api_key_health_rejected(api_key_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await api_key_stub.Health(docling_serve_pb2.HealthRequest())
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_api_key_health_accepted(api_key_stub):
    response = await api_key_stub.Health(
        docling_serve_pb2.HealthRequest(),
        metadata=(("x-api-key", "test-secret-key"),),
    )
    assert response.status == "ok"


@pytest.mark.asyncio
async def test_api_key_watch_convert_rejected(api_key_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        async for _ in api_key_stub.WatchConvertSource(
            docling_serve_pb2.WatchConvertSourceRequest(
                request=_dummy_convert_request()
            )
        ):
            pass
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_api_key_watch_chunk_hierarchical_rejected(api_key_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        async for _ in api_key_stub.WatchChunkHierarchicalSource(
            docling_serve_pb2.WatchChunkHierarchicalSourceRequest(
                request=_dummy_hierarchical_request()
            )
        ):
            pass
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_api_key_watch_chunk_hybrid_rejected(api_key_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        async for _ in api_key_stub.WatchChunkHybridSource(
            docling_serve_pb2.WatchChunkHybridSourceRequest(
                request=_dummy_hybrid_request()
            )
        ):
            pass
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_api_key_convert_source_stream_rejected(api_key_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        async for _ in api_key_stub.ConvertSourceStream(
            docling_serve_pb2.ConvertSourceStreamRequest(
                request=_dummy_convert_request()
            )
        ):
            pass
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_api_key_streaming_accepted_with_key(api_key_stub):
    """Streaming RPCs succeed when the correct API key is provided."""
    metadata = (("x-api-key", "test-secret-key"),)

    async for response in api_key_stub.WatchConvertSource(
        docling_serve_pb2.WatchConvertSourceRequest(request=_dummy_convert_request()),
        metadata=metadata,
    ):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break

    async for response in api_key_stub.WatchChunkHierarchicalSource(
        docling_serve_pb2.WatchChunkHierarchicalSourceRequest(
            request=_dummy_hierarchical_request()
        ),
        metadata=metadata,
    ):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break

    async for response in api_key_stub.WatchChunkHybridSource(
        docling_serve_pb2.WatchChunkHybridSourceRequest(
            request=_dummy_hybrid_request()
        ),
        metadata=metadata,
    ):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break


# ---------------------------------------------------------------------------
# Source validation and source-type coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_convert_source_no_variant_invalid_argument(grpc_stub):
    """A Source with no variant (file/http/s3) fails with INVALID_ARGUMENT."""
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.ConvertSource(
            docling_serve_pb2.ConvertSourceRequest(
                request=docling_serve_types_pb2.ConvertDocumentRequest(
                    sources=[docling_serve_types_pb2.Source()]
                )
            )
        )
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "no variant set" in exc_info.value.details()


@pytest.mark.asyncio
async def test_convert_source_mixed_with_empty_variant_invalid_argument(grpc_stub):
    """A mix of valid and empty-variant sources fails with INVALID_ARGUMENT."""
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.ConvertSource(
            docling_serve_pb2.ConvertSourceRequest(
                request=docling_serve_types_pb2.ConvertDocumentRequest(
                    sources=[
                        docling_serve_types_pb2.Source(
                            file=docling_serve_types_pb2.FileSource(
                                base64_string=base64.b64encode(b"dummy").decode(),
                                filename="a.pdf",
                            )
                        ),
                        docling_serve_types_pb2.Source(),  # no variant
                    ]
                )
            )
        )
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "index 1" in exc_info.value.details()


@pytest.mark.asyncio
async def test_convert_source_invalid_options_invalid_argument(grpc_stub):
    """Options the mapping layer rejects surface as INVALID_ARGUMENT, not INTERNAL.

    page_range with end < start fails Pydantic validation inside
    to_convert_options; the servicer must translate that to a client error.
    """
    from docling_core.proto.gen.ai.docling.core.v1 import docling_document_pb2

    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.ConvertSource(
            docling_serve_pb2.ConvertSourceRequest(
                request=docling_serve_types_pb2.ConvertDocumentRequest(
                    sources=[
                        docling_serve_types_pb2.Source(
                            http=docling_serve_types_pb2.HttpSource(
                                url="https://example.com/doc.pdf"
                            )
                        )
                    ],
                    options=docling_serve_types_pb2.ConvertDocumentOptions(
                        page_range=docling_document_pb2.IntSpan(start=5, end=1)
                    ),
                )
            )
        )
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "page_range" in exc_info.value.details()


@pytest.mark.asyncio
async def test_convert_source_http_source(grpc_stub):
    """ConvertSource with HttpSource succeeds end-to-end through fake orchestrator."""
    request = docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    http=docling_serve_types_pb2.HttpSource(
                        url="https://example.com/doc.pdf",
                        headers={"Authorization": "Bearer token"},
                    )
                )
            ]
        )
    )
    response = await grpc_stub.ConvertSource(request)
    assert response.response.document.doc.schema_name == "DoclingDocument"


@pytest.mark.asyncio
async def test_convert_source_s3_source():
    """ConvertSource with S3Source succeeds when policy allows S3 targets."""
    policy = build_service_policy(docling_serve_settings)
    request = docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    s3=docling_serve_types_pb2.S3Source(
                        endpoint="s3.example.com",
                        access_key="AKIA...",
                        secret_key="secret",
                        bucket="my-bucket",
                        key_prefix="docs/",
                        verify_ssl=True,
                    )
                )
            ],
            # Policy requires S3 sources to pair with an S3 target.
            target=docling_serve_types_pb2.Target(
                s3=docling_serve_types_pb2.S3Target(
                    endpoint="s3.example.com",
                    access_key="AKIA...",
                    secret_key="secret",
                    bucket="out-bucket",
                    key_prefix="results/",
                    verify_ssl=True,
                )
            ),
        )
    )
    async with _server_with(policy=policy) as stub:
        response = await stub.ConvertSource(request)
    assert response.response.document.doc.schema_name == "DoclingDocument"


@pytest.mark.asyncio
async def test_convert_source_mixed_file_and_http(grpc_stub):
    """ConvertSource with mixed file + http sources succeeds."""
    request = docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=base64.b64encode(b"dummy").decode(),
                        filename="test.pdf",
                    )
                ),
                docling_serve_types_pb2.Source(
                    http=docling_serve_types_pb2.HttpSource(
                        url="https://example.com/other.pdf",
                    )
                ),
            ]
        )
    )
    response = await grpc_stub.ConvertSource(request)
    assert response.response.document.doc.schema_name == "DoclingDocument"


@pytest.mark.asyncio
async def test_watch_convert_source_no_variant_invalid_argument(grpc_stub):
    """Streaming RPC also rejects sources with no variant."""
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        async for _ in grpc_stub.WatchConvertSource(
            docling_serve_pb2.WatchConvertSourceRequest(
                request=docling_serve_types_pb2.ConvertDocumentRequest(
                    sources=[docling_serve_types_pb2.Source()]
                )
            )
        ):
            pass
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_watch_convert_source_http_source(grpc_stub):
    """WatchConvertSource with HttpSource succeeds end-to-end."""
    request = docling_serve_pb2.WatchConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    http=docling_serve_types_pb2.HttpSource(
                        url="https://example.com/doc.pdf",
                    )
                )
            ]
        )
    )
    async for response in grpc_stub.WatchConvertSource(request):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break


# ---------------------------------------------------------------------------
# Review-driven regression tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_to_formats_yields_doc_without_exports(grpc_stub):
    """A request with no to_formats returns doc but no exports (gRPC-native default)."""
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    )
                )
            ],
            # No options → no to_formats
        )
    )
    response = await grpc_stub.ConvertSource(request)
    assert response.response.document.doc.schema_name == "DoclingDocument"
    assert not response.response.document.HasField("exports")


@pytest.mark.asyncio
async def test_explicit_json_export_matches_model_dump_json(grpc_stub):
    """When JSON export is requested, it equals the canonical Pydantic serializer output."""
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    )
                )
            ],
            options=docling_serve_types_pb2.ConvertDocumentOptions(
                to_formats=[docling_serve_types_pb2.OUTPUT_FORMAT_JSON],
            ),
        )
    )
    response = await grpc_stub.ConvertSource(request)
    assert response.response.document.HasField("exports")
    json_export = response.response.document.exports.json
    # The canonical serializer produces valid JSON with the schema_name field
    import json

    parsed = json.loads(json_export)
    assert parsed["name"] == "doc"
    assert "schema_name" in parsed


# ---------------------------------------------------------------------------
# Policy enforcement (mirrors REST ServicePolicy rules)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _server_with(
    policy=None, orchestrator=None, interceptors=None, streaming=False
):
    """Spin up a gRPC server with a custom policy/orchestrator/interceptors.

    Yields the convert stub, or ``(convert_stub, streaming_stub)`` when
    ``streaming`` is set.
    """
    original_single_use = docling_serve_settings.single_use_results
    docling_serve_settings.single_use_results = False
    server = grpc.aio.server(interceptors=list(interceptors or []))
    orchestrator = orchestrator or FakeOrchestrator()
    service = DoclingServeGrpcService(orchestrator=orchestrator, policy=policy)
    await service.start()
    docling_serve_pb2_grpc.add_DoclingServeServiceServicer_to_server(service, server)
    docling_serve_stream_pb2_grpc.add_DoclingStreamingServiceServicer_to_server(
        DoclingStreamingGrpcService(service), server
    )
    port = server.add_insecure_port("[::]:0")
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
            stub = docling_serve_pb2_grpc.DoclingServeServiceStub(channel)
            if streaming:
                yield (
                    stub,
                    docling_serve_stream_pb2_grpc.DoclingStreamingServiceStub(channel),
                )
            else:
                yield stub
    finally:
        await service.close()
        docling_serve_settings.single_use_results = original_single_use
        await server.stop(grace=1)


def _file_convert_request(num_sources=1, target=None):
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    return docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename=f"test_{i}.pdf",
                    )
                )
                for i in range(num_sources)
            ],
            target=target,
        )
    )


@pytest.mark.asyncio
async def test_s3_source_requires_storage_target(grpc_stub):
    """Expandable S3 sources require a storage/artifact target (not inbody)."""
    request = docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    s3=docling_serve_types_pb2.S3Source(
                        endpoint="s3.example.com",
                        access_key="AKIA...",
                        secret_key="secret",
                        bucket="my-bucket",
                        verify_ssl=True,
                    )
                )
            ]
        )
    )
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.ConvertSource(request)
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "require a storage target" in exc_info.value.details()


@pytest.mark.asyncio
async def test_s3_source_rejected_when_disallowed():
    """allowed_source_types can deny S3 even when connectors are installed."""
    policy = replace(
        build_service_policy(docling_serve_settings),
        allowed_source_types=frozenset({"file", "http"}),
    )
    request = docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    s3=docling_serve_types_pb2.S3Source(
                        endpoint="s3.example.com",
                        access_key="AKIA...",
                        secret_key="secret",
                        bucket="my-bucket",
                        verify_ssl=True,
                    )
                )
            ]
        )
    )
    async with _server_with(policy=policy) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSource(request)
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "source kind 's3' is not allowed" in exc_info.value.details()


@pytest.mark.asyncio
async def test_policy_rejects_disallowed_target_type():
    """allowed_target_types restricts which targets a request may use."""
    policy = replace(
        build_service_policy(docling_serve_settings),
        allowed_target_types=frozenset({"inbody"}),
    )
    request = _file_convert_request(
        target=docling_serve_types_pb2.Target(zip=docling_serve_types_pb2.ZipTarget())
    )
    async with _server_with(policy=policy) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSource(request)
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "not allowed" in exc_info.value.details()


@pytest.mark.asyncio
async def test_policy_rejects_too_many_sources():
    policy = replace(
        build_service_policy(docling_serve_settings),
        max_sources_per_request=1,
    )
    request = _file_convert_request(num_sources=2)
    async with _server_with(policy=policy) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSource(request)
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "Too many sources" in exc_info.value.details()


@pytest.mark.asyncio
async def test_omitted_target_prefers_presigned_when_artifacts_enabled():
    """Omitted gRPC targets follow REST's policy-aware default target."""
    policy = replace(
        build_service_policy(docling_serve_settings),
        artifact_storage_enabled=True,
    )
    orchestrator = FakeOrchestrator()
    async with _server_with(policy=policy, orchestrator=orchestrator) as stub:
        response = await stub.ConvertSource(_file_convert_request())

    assert response.response.document.doc.schema_name == "DoclingDocument"
    [task] = orchestrator.tasks.values()
    # jobkit Task now stores the resolved target on `targets` (singular `target`
    # is a deprecated convenience that may remain unset).
    resolved = task.targets or ([task.target] if task.target is not None else [])
    assert resolved and resolved[0].kind == "presigned_url"


@pytest.mark.asyncio
async def test_presigned_url_target_requires_artifact_storage():
    """presigned_url target is rejected when artifact storage is disabled."""
    policy = replace(
        build_service_policy(docling_serve_settings),
        artifact_storage_enabled=False,
    )
    request = _file_convert_request(
        target=docling_serve_types_pb2.Target(
            presigned_url=docling_serve_types_pb2.PreSignedUrlTarget()
        )
    )
    async with _server_with(policy=policy) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSource(request)
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "artifact storage" in exc_info.value.details()


@pytest.mark.asyncio
async def test_presigned_url_target_rejected_for_chunk():
    """presigned_url target is never allowed on chunk RPCs (REST parity)."""
    policy = replace(
        build_service_policy(docling_serve_settings),
        artifact_storage_enabled=True,
    )
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_pb2.ChunkHierarchicalSourceRequest(
        request=docling_serve_types_pb2.HierarchicalChunkRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    )
                )
            ],
            target=docling_serve_types_pb2.Target(
                presigned_url=docling_serve_types_pb2.PreSignedUrlTarget()
            ),
        )
    )
    async with _server_with(policy=policy) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ChunkHierarchicalSource(request)
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "not supported for chunk" in exc_info.value.details()


# ---------------------------------------------------------------------------
# Error detail sanitization (mirrors REST public_errors behavior)
# ---------------------------------------------------------------------------


class BrokenOrchestrator(FakeOrchestrator):
    async def enqueue(self, **kwargs):
        raise RuntimeError("sensitive internal detail: db password leaked")


@pytest.mark.asyncio
async def test_unhandled_error_sanitized_without_debug():
    """Unexpected exceptions yield a generic INTERNAL message by default."""
    original = docling_serve_settings.debug_error_details
    docling_serve_settings.debug_error_details = False
    try:
        async with _server_with(
            orchestrator=BrokenOrchestrator(),
            interceptors=[PublicErrorInterceptor()],
        ) as stub:
            with pytest.raises(grpc.aio.AioRpcError) as exc_info:
                await stub.ConvertSource(_file_convert_request())
        assert exc_info.value.code() == grpc.StatusCode.INTERNAL
        assert exc_info.value.details() == "Internal server error."
        assert "sensitive" not in exc_info.value.details()
    finally:
        docling_serve_settings.debug_error_details = original


@pytest.mark.asyncio
async def test_unhandled_error_detail_with_debug():
    """With debug_error_details enabled, the exception text is exposed."""
    original = docling_serve_settings.debug_error_details
    docling_serve_settings.debug_error_details = True
    try:
        async with _server_with(
            orchestrator=BrokenOrchestrator(),
            interceptors=[PublicErrorInterceptor()],
        ) as stub:
            with pytest.raises(grpc.aio.AioRpcError) as exc_info:
                await stub.ConvertSource(_file_convert_request())
        assert exc_info.value.code() == grpc.StatusCode.INTERNAL
        assert "sensitive internal detail" in exc_info.value.details()
    finally:
        docling_serve_settings.debug_error_details = original


class BackpressuredOrchestrator(FakeOrchestrator):
    async def enqueue(self, **kwargs):
        raise RedisBackpressureError("queue depth exceeded")


@pytest.mark.asyncio
async def test_backpressure_maps_to_resource_exhausted():
    """RedisBackpressureError (REST 503) becomes RESOURCE_EXHAUSTED on gRPC."""
    async with _server_with(
        orchestrator=BackpressuredOrchestrator(),
        interceptors=[PublicErrorInterceptor()],
        streaming=True,
    ) as (stub, streaming_stub):
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSource(_file_convert_request())
        assert exc_info.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
        assert "queue depth exceeded" not in exc_info.value.details()

        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            async for _ in stub.WatchConvertSource(
                docling_serve_pb2.WatchConvertSourceRequest(
                    request=_dummy_convert_request()
                )
            ):
                pass
        assert exc_info.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


# ---------------------------------------------------------------------------
# Callbacks (ConvertDocumentRequest.callbacks -> Task.callbacks)
# ---------------------------------------------------------------------------


def _callback_spec():
    return docling_serve_types_pb2.CallbackSpec(
        url="https://hooks.example.com/progress",
        headers={"Authorization": "Bearer t0k3n"},
        ca_cert="-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----",
    )


@pytest.mark.asyncio
async def test_convert_source_forwards_typed_callbacks():
    """CallbackSpec is mapped to the Pydantic model and passed to enqueue."""
    policy = replace(
        build_service_policy(docling_serve_settings), callbacks_enabled=True
    )
    orchestrator = FakeOrchestrator()
    request = _file_convert_request()
    request.request.callbacks.append(_callback_spec())

    async with _server_with(policy=policy, orchestrator=orchestrator) as stub:
        await stub.ConvertSource(request)

    [call] = orchestrator.enqueue_kwargs
    [spec] = call["callbacks"]
    assert str(spec.url) == "https://hooks.example.com/progress"
    assert spec.headers == {"Authorization": "Bearer t0k3n"}
    assert spec.ca_cert.startswith("-----BEGIN CERTIFICATE-----")


@pytest.mark.asyncio
async def test_convert_source_callbacks_rejected_when_disabled():
    policy = replace(
        build_service_policy(docling_serve_settings), callbacks_enabled=False
    )
    request = _file_convert_request()
    request.request.callbacks.append(_callback_spec())

    async with _server_with(policy=policy) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSource(request)
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "Callbacks are disabled" in exc_info.value.details()


@pytest.mark.asyncio
async def test_chunk_source_forwards_callbacks():
    policy = replace(
        build_service_policy(docling_serve_settings), callbacks_enabled=True
    )
    orchestrator = FakeOrchestrator()
    request = docling_serve_pb2.ChunkHybridSourceAsyncRequest(
        request=_dummy_hybrid_request()
    )
    request.request.callbacks.append(_callback_spec())

    async with _server_with(policy=policy, orchestrator=orchestrator) as stub:
        response = await stub.ChunkHybridSourceAsync(request)

    assert response.response.task_type == docling_serve_types_pb2.TASK_TYPE_CHUNK
    [call] = orchestrator.enqueue_kwargs
    assert call["task_type"] == TaskType.CHUNK
    assert len(call["callbacks"]) == 1


# ---------------------------------------------------------------------------
# ConvertSourceBatch (mirrors POST /v1/convert/source/batch)
# ---------------------------------------------------------------------------


def _s3_target(bucket="out-bucket"):
    return docling_serve_types_pb2.Target(
        s3=docling_serve_types_pb2.S3Target(
            endpoint="s3.example.com",
            access_key="AKIA...",
            secret_key="secret",
            bucket=bucket,
            key_prefix="results/",
            verify_ssl=True,
        )
    )


def _batch_request(**overrides):
    fields = {
        "sources": [
            docling_serve_types_pb2.Source(
                http=docling_serve_types_pb2.HttpSource(url="https://example.com/a.pdf")
            ),
            docling_serve_types_pb2.Source(
                http=docling_serve_types_pb2.HttpSource(url="https://example.com/b.pdf")
            ),
        ],
        "targets": [_s3_target("out-a"), _s3_target("out-b")],
    }
    fields.update(overrides)
    return docling_serve_pb2.ConvertSourceBatchRequest(
        request=docling_serve_types_pb2.BatchConvertDocumentRequest(**fields)
    )


@pytest.mark.asyncio
async def test_convert_source_batch_enqueues_targets_and_callbacks():
    policy = replace(
        build_service_policy(docling_serve_settings), callbacks_enabled=True
    )
    orchestrator = FakeOrchestrator()
    request = _batch_request(callbacks=[_callback_spec()])
    request.request.options.to_formats.append(
        docling_serve_types_pb2.OUTPUT_FORMAT_MARKDOWN
    )

    async with _server_with(policy=policy, orchestrator=orchestrator) as stub:
        response = await stub.ConvertSourceBatch(request)

    status = response.response
    assert status.task_type == docling_serve_types_pb2.TASK_TYPE_CONVERT
    assert status.task_status == docling_serve_types_pb2.TASK_STATUS_SUCCESS
    assert status.task_id in orchestrator.tasks

    [call] = orchestrator.enqueue_kwargs
    assert call["task_type"] == TaskType.CONVERT
    assert len(call["sources"]) == 2
    assert [t.kind for t in call["targets"]] == ["s3", "s3"]
    assert [t.bucket for t in call["targets"]] == ["out-a", "out-b"]
    assert call["target"] is None
    assert len(call["callbacks"]) == 1


@pytest.mark.asyncio
async def test_convert_source_batch_generic_target_round_trips_attributes():
    """GenericTarget mirrors GenericTargetRequest (kind + typed attribute bag)."""
    policy = build_service_policy(docling_serve_settings)
    orchestrator = FakeOrchestrator()
    generic = docling_serve_types_pb2.Target(
        generic=docling_serve_types_pb2.GenericTarget(
            kind="s3",
            attributes={
                "endpoint": docling_serve_types_pb2.ScalarValue(
                    string_value="s3.example.com"
                ),
                "access_key": docling_serve_types_pb2.ScalarValue(string_value="AKIA"),
                "secret_key": docling_serve_types_pb2.ScalarValue(string_value="sec"),
                "bucket": docling_serve_types_pb2.ScalarValue(string_value="generic"),
                "verify_ssl": docling_serve_types_pb2.ScalarValue(bool_value=False),
            },
        )
    )
    request = _batch_request(targets=[generic])

    async with _server_with(policy=policy, orchestrator=orchestrator) as stub:
        await stub.ConvertSourceBatch(request)

    [call] = orchestrator.enqueue_kwargs
    [target] = call["targets"]
    assert target.kind == "s3"
    assert target.bucket == "generic"
    assert target.verify_ssl is False


@pytest.mark.asyncio
async def test_convert_source_batch_requires_target():
    policy = build_service_policy(docling_serve_settings)
    async with _server_with(policy=policy) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSourceBatch(_batch_request(targets=[]))
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_convert_source_batch_rejects_inline_file_source():
    """Batch is storage-to-storage: inline file sources fail like REST 422."""
    policy = build_service_policy(docling_serve_settings)
    inline = docling_serve_types_pb2.Source(
        file=docling_serve_types_pb2.FileSource(
            base64_string=base64.b64encode(b"dummy").decode(), filename="x.pdf"
        )
    )
    async with _server_with(policy=policy) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSourceBatch(_batch_request(sources=[inline]))
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_convert_source_batch_honours_max_sources():
    policy = replace(
        build_service_policy(docling_serve_settings), max_sources_per_request=1
    )
    async with _server_with(policy=policy) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSourceBatch(_batch_request())
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "Too many sources" in exc_info.value.details()
