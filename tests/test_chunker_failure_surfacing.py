"""A chunker or tokenizer load failure must surface as an error on REST and gRPC.

Before this, docling-jobkit logged the exception, counted the document as failed
and still returned a successful ChunkedDocumentResult with zero chunks (seen on
krick when an expired HF_TOKEN made the tokenizer download return 401). Both the
REST ChunkDocumentResponse and the gRPC ChunkDocumentResponse carried no sign of
it. These tests force the tokenizer load to fail and drive the real local
orchestrator through the REST app and an in-process gRPC server.

The source is a small Markdown file: it converts without any model download, so
the only moving part under test is the chunker.
"""

import asyncio
import base64
from unittest.mock import patch

import grpc
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from docling_serve.app import create_app
from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2,
    docling_serve_pb2_grpc,
    docling_serve_types_pb2,
)
from docling_serve.grpc.server import DoclingServeGrpcService
from docling_serve.orchestrator_factory import get_async_orchestrator
from docling_serve.settings import docling_serve_settings

pytestmark = pytest.mark.unit

TOKENIZER_FAILURE_MESSAGE = "Document chunking failed (RuntimeError)."
TOKENIZER_LOAD = "docling_jobkit.convert.chunking.HuggingFaceTokenizer.from_pretrained"
MARKDOWN = b"# Title\n\nFirst paragraph.\n\n## Section\n\nSecond paragraph.\n"


def _tokenizer_401() -> OSError:
    return OSError("401 Client Error: Unauthorized for url")


def _b64() -> str:
    return base64.b64encode(MARKDOWN).decode()


# --- REST ------------------------------------------------------------------


@pytest_asyncio.fixture
async def rest_client():
    get_async_orchestrator.cache_clear()
    app = create_app()
    async with LifespanManager(app) as manager:
        async with AsyncClient(
            transport=ASGITransport(app=manager.app), base_url="http://app.io"
        ) as client:
            yield client
    get_async_orchestrator.cache_clear()


def _rest_payload(chunker: str) -> dict:
    payload: dict = {
        "sources": [{"kind": "file", "base64_string": _b64(), "filename": "doc.md"}],
        "convert_options": {"to_formats": ["json"]},
        "include_converted_doc": False,
    }
    if chunker == "hybrid":
        payload["chunking_options"] = {}
    return payload


@pytest.mark.asyncio
async def test_rest_sync_hybrid_chunk_returns_500_when_tokenizer_cannot_load(
    rest_client,
):
    with patch(TOKENIZER_LOAD, side_effect=_tokenizer_401()) as from_pretrained:
        response = await rest_client.post(
            "/v1/chunk/hybrid/source", json=_rest_payload("hybrid")
        )
    assert from_pretrained.called
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == TOKENIZER_FAILURE_MESSAGE
    assert "chunks" not in body


@pytest.mark.asyncio
async def test_rest_async_hybrid_chunk_reports_failed_task_with_typed_failure(
    rest_client,
):
    with patch(TOKENIZER_LOAD, side_effect=_tokenizer_401()):
        submit = await rest_client.post(
            "/v1/chunk/hybrid/source/async", json=_rest_payload("hybrid")
        )
        assert submit.status_code == 200, submit.text
        task_id = submit.json()["task_id"]

        status: dict = {}
        for _ in range(60):
            poll = await rest_client.get(f"/v1/status/poll/{task_id}?wait=1")
            assert poll.status_code == 200, poll.text
            status = poll.json()
            if status["task_status"] in {"success", "failure"}:
                break
            await asyncio.sleep(0.5)

    assert status["task_status"] == "failure"
    assert status["error_message"] == TOKENIZER_FAILURE_MESSAGE
    assert status["failure"] == {
        "category": "backend_failure",
        "message": TOKENIZER_FAILURE_MESSAGE,
        "retryable": False,
        "phase": "execution",
        "details": {},
    }

    # The result endpoint reports a failed task as a TaskFailureResult, the same
    # body stored failure outcomes (RQ, Ray) produce. It used to answer 404
    # ("result not found") for the local orchestrator.
    result = await rest_client.get(f"/v1/result/{task_id}")
    assert result.status_code == 200
    body = result.json()
    assert body["kind"] == "TaskFailureResult"
    assert body["failure"] == status["failure"]
    assert "chunks" not in body


@pytest.mark.asyncio
async def test_rest_hierarchical_chunk_still_succeeds_without_a_tokenizer(
    rest_client,
):
    """Control: the same request through a chunker that needs no tokenizer works."""
    with patch(TOKENIZER_LOAD, side_effect=_tokenizer_401()) as from_pretrained:
        response = await rest_client.post(
            "/v1/chunk/hierarchical/source", json=_rest_payload("hierarchical")
        )
    assert not from_pretrained.called
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["chunks"]) > 0
    assert body["documents"][0]["status"] == "success"


class _FailedTaskOrchestrator:
    """Keeps no stored outcome and records the failure only as error_message."""

    def __init__(self, task):
        self.task = task

    async def task_status(self, *, task_id: str, wait: float | None = None):
        return self.task

    async def task_outcome(self, task_id: str):
        return None


@pytest.mark.asyncio
async def test_rest_result_for_failed_task_without_failure_info_is_typed_unknown():
    """task.failure unset (older orchestrators): UNKNOWN/EXECUTION, not a 404."""
    from docling_jobkit.datamodel.task import Task
    from docling_jobkit.datamodel.task_meta import TaskStatus, TaskType

    task = Task(
        task_id="failed-no-info",
        task_type=TaskType.CHUNK,
        task_status=TaskStatus.FAILURE,
        error_message="Document chunking failed (RuntimeError).",
    )
    app = create_app()
    app.dependency_overrides[get_async_orchestrator] = lambda: _FailedTaskOrchestrator(
        task
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.get("/v1/result/failed-no-info")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "TaskFailureResult"
    assert body["failure"]["category"] == "unknown"
    assert body["failure"]["phase"] == "execution"
    assert body["failure"]["message"] == "Document chunking failed (RuntimeError)."
    assert body["failure"]["retryable"] is False


@pytest.mark.asyncio
async def test_rest_result_for_unfinished_task_is_still_404():
    from docling_jobkit.datamodel.task import Task
    from docling_jobkit.datamodel.task_meta import TaskStatus, TaskType

    task = Task(
        task_id="running",
        task_type=TaskType.CHUNK,
        task_status=TaskStatus.STARTED,
    )
    app = create_app()
    app.dependency_overrides[get_async_orchestrator] = lambda: _FailedTaskOrchestrator(
        task
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.get("/v1/result/running")
    assert response.status_code == 404


# --- gRPC ------------------------------------------------------------------


@pytest_asyncio.fixture
async def grpc_stub():
    get_async_orchestrator.cache_clear()
    original_single_use = docling_serve_settings.single_use_results
    docling_serve_settings.single_use_results = False
    server = grpc.aio.server()
    service = DoclingServeGrpcService()
    await service.start()
    docling_serve_pb2_grpc.add_DoclingServeServiceServicer_to_server(service, server)
    port = server.add_insecure_port("[::]:0")
    await server.start()
    async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
        yield docling_serve_pb2_grpc.DoclingServeServiceStub(channel)
    await service.close()
    await server.stop(grace=1)
    docling_serve_settings.single_use_results = original_single_use
    get_async_orchestrator.cache_clear()


def _grpc_source() -> docling_serve_types_pb2.Source:
    return docling_serve_types_pb2.Source(
        file=docling_serve_types_pb2.FileSource(base64_string=_b64(), filename="doc.md")
    )


def _hybrid_request() -> docling_serve_pb2.ChunkHybridSourceRequest:
    return docling_serve_pb2.ChunkHybridSourceRequest(
        request=docling_serve_types_pb2.HybridChunkRequest(
            sources=[_grpc_source()],
            convert_options=docling_serve_types_pb2.ConvertDocumentOptions(
                to_formats=[docling_serve_types_pb2.OUTPUT_FORMAT_JSON]
            ),
            include_converted_doc=False,
            chunking_options=docling_serve_types_pb2.HybridChunkerOptions(),
        )
    )


def _assert_typed_chunker_failure(failure: docling_serve_types_pb2.TaskFailureResult):
    info = failure.failure
    assert info.category == docling_serve_types_pb2.FAILURE_CATEGORY_BACKEND_FAILURE
    assert info.phase == docling_serve_types_pb2.FAILURE_PHASE_EXECUTION
    assert info.retryable is False
    assert info.message == TOKENIZER_FAILURE_MESSAGE


@pytest.mark.asyncio
async def test_grpc_sync_hybrid_chunk_returns_typed_failure_when_tokenizer_cannot_load(
    grpc_stub,
):
    with patch(TOKENIZER_LOAD, side_effect=_tokenizer_401()) as from_pretrained:
        response = await grpc_stub.ChunkHybridSource(_hybrid_request())
    assert from_pretrained.called
    assert response.WhichOneof("result") == "failure"
    assert len(response.response.chunks) == 0
    _assert_typed_chunker_failure(response.failure)


@pytest.mark.asyncio
async def test_grpc_async_hybrid_chunk_reports_failed_task_and_typed_result(
    grpc_stub,
):
    with patch(TOKENIZER_LOAD, side_effect=_tokenizer_401()):
        submit = await grpc_stub.ChunkHybridSourceAsync(
            docling_serve_pb2.ChunkHybridSourceAsyncRequest(
                request=_hybrid_request().request
            )
        )
        task_id = submit.response.task_id
        status = None
        for _ in range(60):
            poll = await grpc_stub.PollTaskStatus(
                docling_serve_pb2.PollTaskStatusRequest(
                    request=docling_serve_types_pb2.TaskStatusPollRequest(
                        task_id=task_id, wait_time=1
                    )
                )
            )
            status = poll.response
            if status.task_status in (
                docling_serve_types_pb2.TASK_STATUS_SUCCESS,
                docling_serve_types_pb2.TASK_STATUS_FAILURE,
            ):
                break
            await asyncio.sleep(0.5)

    assert status is not None
    assert status.task_status == docling_serve_types_pb2.TASK_STATUS_FAILURE
    assert status.error_message == TOKENIZER_FAILURE_MESSAGE
    assert status.HasField("failure")
    _assert_typed_chunker_failure(
        docling_serve_types_pb2.TaskFailureResult(failure=status.failure)
    )

    result = await grpc_stub.GetChunkResult(
        docling_serve_pb2.GetChunkResultRequest(
            request=docling_serve_types_pb2.TaskResultRequest(task_id=task_id)
        )
    )
    assert result.WhichOneof("result") == "failure"
    _assert_typed_chunker_failure(result.failure)


@pytest.mark.asyncio
async def test_grpc_hierarchical_chunk_still_succeeds_without_a_tokenizer(grpc_stub):
    request = docling_serve_pb2.ChunkHierarchicalSourceRequest(
        request=docling_serve_types_pb2.HierarchicalChunkRequest(
            sources=[_grpc_source()],
            convert_options=docling_serve_types_pb2.ConvertDocumentOptions(
                to_formats=[docling_serve_types_pb2.OUTPUT_FORMAT_JSON]
            ),
            include_converted_doc=False,
            chunking_options=docling_serve_types_pb2.HierarchicalChunkerOptions(),
        )
    )
    with patch(TOKENIZER_LOAD, side_effect=_tokenizer_401()) as from_pretrained:
        response = await grpc_stub.ChunkHierarchicalSource(request)
    assert not from_pretrained.called
    assert response.WhichOneof("result") == "response"
    assert len(response.response.chunks) > 0
    assert response.response.documents[0].status == (
        docling_serve_types_pb2.CONVERSION_STATUS_SUCCESS
    )
