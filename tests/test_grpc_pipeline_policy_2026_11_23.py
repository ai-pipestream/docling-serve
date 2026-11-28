"""gRPC parity for upstream #715 (server pipeline policy), #775 (jobkit 3.10.0),
docling 2.152.0 #4875 (optional request pipeline) and jobkit #283 (zip name).

Every request here is a protobuf message sent through the gRPC mapping or a
live in-process gRPC server. The REST check (``validate_convert_options``)
is the reference for the rejection text.
"""

from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from pathlib import PurePosixPath

import grpc
import pytest
from fastapi import HTTPException

from docling.datamodel.pipeline_options import ProcessingPipeline
from docling.datamodel.service.options import ConvertDocumentsOptions
from docling.datamodel.service.responses import ZipArchiveResult
from docling_jobkit.convert.manager import (
    SUPPORTED_PIPELINES,
    DoclingConverterManager,
    DoclingConverterManagerConfig,
)
from docling_jobkit.convert.results import single_document_zip_filename
from docling_jobkit.datamodel.result import DoclingTaskResult

from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2,
    docling_serve_pb2_grpc,
    docling_serve_types_pb2 as types_pb2,
)
from docling_serve.grpc.mapping import to_convert_options, zip_result_to_proto
from docling_serve.grpc.policy_enforcement import normalize_options, validate_request
from docling_serve.grpc.server import DoclingServeGrpcService
from docling_serve.policy import build_service_policy, validate_convert_options
from docling_serve.settings import DoclingServeSettings, docling_serve_settings
from tests.test_grpc_service_fake import FakeOrchestrator

PP = types_pb2.ProcessingPipeline


def _source() -> types_pb2.Source:
    return types_pb2.Source(
        file=types_pb2.FileSource(
            base64_string=base64.b64encode(b"%PDF-1.4 dummy").decode("ascii"),
            filename="report.pdf",
        )
    )


def _request(
    options: types_pb2.ConvertDocumentOptions,
) -> types_pb2.ConvertDocumentRequest:
    return types_pb2.ConvertDocumentRequest(sources=[_source()], options=options)


def _manager(**config) -> DoclingConverterManager:
    return DoclingConverterManager(DoclingConverterManagerConfig(**config))


def _rest_detail(options: ConvertDocumentsOptions, policy) -> str:
    with pytest.raises(HTTPException) as exc_info:
        validate_convert_options(options, policy)
    assert exc_info.value.status_code == 422
    return str(exc_info.value.detail)


# --- jobkit 3.10.0 / docling 2.152.0 floor ------------------------------------


def test_installed_stack_has_pipeline_policy_and_optional_pipeline():
    assert SUPPORTED_PIPELINES == (ProcessingPipeline.STANDARD, ProcessingPipeline.VLM)
    field = ConvertDocumentsOptions.model_fields["pipeline"]
    assert field.default is None
    assert ConvertDocumentsOptions().pipeline is None
    config = DoclingConverterManagerConfig()
    assert config.default_pipeline is ProcessingPipeline.STANDARD
    assert config.allowed_pipelines is None


def test_proto_pipeline_tag_is_11_and_optional():
    field = types_pb2.ConvertDocumentOptions.DESCRIPTOR.fields_by_name["pipeline"]
    assert field.number == 11
    assert field.has_presence
    assert field.enum_type.full_name == "ai.docling.serve.v1.ProcessingPipeline"
    assert {v.name: v.number for v in field.enum_type.values} == {
        "PROCESSING_PIPELINE_UNSPECIFIED": 0,
        "PROCESSING_PIPELINE_ASR": 1,
        "PROCESSING_PIPELINE_STANDARD": 2,
        "PROCESSING_PIPELINE_VLM": 3,
        "PROCESSING_PIPELINE_LEGACY": 4,
        "PROCESSING_PIPELINE_NATIVE": 5,
    }


# --- unset pipeline stays unset, resolves to server default -------------------


def test_unset_grpc_pipeline_stays_unset_in_mapped_model():
    proto = types_pb2.ConvertDocumentOptions()
    assert not proto.HasField("pipeline")
    mapped = to_convert_options(proto)
    assert mapped.pipeline is None
    assert "pipeline" not in mapped.model_fields_set
    normalized = normalize_options(mapped, build_service_policy(DoclingServeSettings()))
    assert normalized.pipeline is None


def test_explicit_unspecified_grpc_pipeline_maps_to_unset():
    proto = types_pb2.ConvertDocumentOptions(
        pipeline=PP.PROCESSING_PIPELINE_UNSPECIFIED
    )
    assert proto.HasField("pipeline")
    mapped = to_convert_options(proto)
    assert mapped.pipeline is None
    assert "pipeline" not in mapped.model_fields_set


@pytest.mark.parametrize(
    ("default", "expected"),
    [
        (ProcessingPipeline.STANDARD, ProcessingPipeline.STANDARD),
        (ProcessingPipeline.VLM, ProcessingPipeline.VLM),
    ],
)
def test_unset_grpc_pipeline_resolves_to_server_default(default, expected):
    mapped = to_convert_options(types_pb2.ConvertDocumentOptions())
    manager = _manager(default_pipeline=default)
    assert manager._resolve_pipeline(mapped) is expected


def test_server_default_reaches_converter_manager_config(monkeypatch):
    from docling_serve import orchestrator_factory

    settings = orchestrator_factory.docling_serve_settings
    monkeypatch.setattr(settings, "default_pipeline", "vlm")
    monkeypatch.setattr(settings, "allowed_pipelines", ["vlm"])
    config = orchestrator_factory._build_cm_config()
    assert config.default_pipeline is ProcessingPipeline.VLM
    assert config.allowed_pipelines == [ProcessingPipeline.VLM]

    mapped = to_convert_options(types_pb2.ConvertDocumentOptions())
    assert DoclingConverterManager(config)._resolve_pipeline(mapped) is (
        ProcessingPipeline.VLM
    )


# --- ASR, LEGACY, NATIVE rejected via the REST check ---------------------------


@pytest.mark.parametrize(
    ("proto_value", "value"),
    [
        (PP.PROCESSING_PIPELINE_ASR, "asr"),
        (PP.PROCESSING_PIPELINE_LEGACY, "legacy"),
        (PP.PROCESSING_PIPELINE_NATIVE, "native"),
    ],
)
def test_unsupported_grpc_pipeline_rejected_like_rest(proto_value, value):
    policy = build_service_policy(DoclingServeSettings())
    assert policy.allowed_pipelines == frozenset({"standard", "vlm"})

    mapped = to_convert_options(types_pb2.ConvertDocumentOptions(pipeline=proto_value))
    assert mapped.pipeline is ProcessingPipeline(value)

    rest = _rest_detail(ConvertDocumentsOptions(pipeline=value), policy)
    assert rest == (
        f"pipeline '{value}' is not allowed. Allowed values: ['standard', 'vlm']."
    )
    from docling.datamodel.service.targets import InBodyTarget

    grpc_detail = validate_request([], mapped, InBodyTarget(), policy)
    assert grpc_detail == rest

    with pytest.raises(ValueError, match=f"Pipeline '{value}' is not allowed"):
        _manager()._resolve_pipeline(mapped)


@pytest.mark.parametrize(
    ("proto_value", "value"),
    [
        (PP.PROCESSING_PIPELINE_STANDARD, "standard"),
        (PP.PROCESSING_PIPELINE_VLM, "vlm"),
    ],
)
def test_supported_grpc_pipeline_passes_rest_check(proto_value, value):
    policy = build_service_policy(DoclingServeSettings())
    mapped = to_convert_options(types_pb2.ConvertDocumentOptions(pipeline=proto_value))
    assert mapped.pipeline is ProcessingPipeline(value)
    validate_convert_options(mapped, policy)
    assert _manager()._resolve_pipeline(mapped) is ProcessingPipeline(value)


# --- live gRPC server with allowed_pipelines -----------------------------------


@asynccontextmanager
async def _serve(settings: DoclingServeSettings):
    original_single_use = docling_serve_settings.single_use_results
    docling_serve_settings.single_use_results = False
    orchestrator = FakeOrchestrator()
    service = DoclingServeGrpcService(
        orchestrator=orchestrator, policy=build_service_policy(settings)
    )
    await service.start()
    server = grpc.aio.server()
    docling_serve_pb2_grpc.add_DoclingServeServiceServicer_to_server(service, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            yield docling_serve_pb2_grpc.DoclingServeServiceStub(channel), orchestrator
    finally:
        await service.close()
        await server.stop(grace=1)
        docling_serve_settings.single_use_results = original_single_use


VLM_ONLY = DoclingServeSettings(allowed_pipelines=["vlm"], default_pipeline="vlm")


@pytest.mark.asyncio
@pytest.mark.parametrize("rpc", ["ConvertSource", "ConvertSourceAsync"])
async def test_grpc_allowed_pipelines_rejects_outside_set(rpc):
    async with _serve(VLM_ONLY) as (stub, orchestrator):
        opts = types_pb2.ConvertDocumentOptions(
            pipeline=PP.PROCESSING_PIPELINE_STANDARD
        )
        req_cls = getattr(docling_serve_pb2, f"{rpc}Request")
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await getattr(stub, rpc)(req_cls(request=_request(opts)))
        assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        assert exc_info.value.details() == (
            "pipeline 'standard' is not allowed. Allowed values: ['vlm']."
        )
        assert orchestrator.enqueue_kwargs == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "proto_value",
    [
        PP.PROCESSING_PIPELINE_ASR,
        PP.PROCESSING_PIPELINE_LEGACY,
        PP.PROCESSING_PIPELINE_NATIVE,
    ],
)
async def test_grpc_default_policy_rejects_unsupported_pipelines(proto_value):
    async with _serve(DoclingServeSettings()) as (stub, orchestrator):
        opts = types_pb2.ConvertDocumentOptions(pipeline=proto_value)
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSource(
                docling_serve_pb2.ConvertSourceRequest(request=_request(opts))
            )
        assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        value = ProcessingPipeline[
            PP.Name(proto_value).removeprefix("PROCESSING_PIPELINE_")
        ].value
        assert exc_info.value.details() == (
            f"pipeline '{value}' is not allowed. Allowed values: ['standard', 'vlm']."
        )
        assert orchestrator.enqueue_kwargs == []


@pytest.mark.asyncio
async def test_grpc_allowed_pipelines_accepts_allowed_and_unset():
    async with _serve(VLM_ONLY) as (stub, orchestrator):
        vlm = types_pb2.ConvertDocumentOptions(pipeline=PP.PROCESSING_PIPELINE_VLM)
        first = await stub.ConvertSourceAsync(
            docling_serve_pb2.ConvertSourceAsyncRequest(request=_request(vlm))
        )
        unset = await stub.ConvertSourceAsync(
            docling_serve_pb2.ConvertSourceAsyncRequest(
                request=_request(types_pb2.ConvertDocumentOptions())
            )
        )
        tasks = orchestrator.tasks
        assert tasks[first.response.task_id].convert_options.pipeline is (
            ProcessingPipeline.VLM
        )
        enqueued = tasks[unset.response.task_id].convert_options
        assert enqueued.pipeline is None
        assert "pipeline" not in enqueued.model_fields_set
        manager = _manager(
            default_pipeline=ProcessingPipeline.VLM,
            allowed_pipelines=[ProcessingPipeline.VLM],
        )
        assert manager._resolve_pipeline(enqueued) is ProcessingPipeline.VLM


def test_service_policy_has_pipeline_fields():
    policy = build_service_policy(VLM_ONLY)
    assert policy.allowed_pipelines == frozenset({"vlm"})
    assert policy.default_pipeline == "vlm"
    with pytest.raises(ValueError, match="default_pipeline 'standard'"):
        build_service_policy(DoclingServeSettings(allowed_pipelines=["vlm"]))
    with pytest.raises(ValueError, match="allowed_pipelines"):
        build_service_policy(
            DoclingServeSettings(allowed_pipelines=["asr"], default_pipeline="vlm")
        )


# --- zip filename from the jobkit 3.10.0 producer ------------------------------


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        ([PurePosixPath("/tmp/in/report.pdf")], "report.zip"),
        (['dir\\sub\\Quarterly: "Q3".docx'], "Quarterly_ _Q3_.zip"),
        ([PurePosixPath("a.pdf"), PurePosixPath("b.pdf")], None),
        ([], None),
        (["..."], None),
    ],
)
def test_zip_filename_from_jobkit_producer_maps_to_proto(sources, expected):
    name = single_document_zip_filename(sources)
    assert name == expected
    result = ZipArchiveResult(content=b"PK\x03\x04", filename=name)
    message = zip_result_to_proto(result)
    assert message.content == b"PK\x03\x04"
    if expected is None:
        assert not message.HasField("filename")
    else:
        assert message.HasField("filename")
        assert message.filename == expected
    assert types_pb2.ZipArchiveResult.FromString(message.SerializeToString()) == message


@pytest.mark.asyncio
async def test_grpc_get_convert_result_carries_producer_zip_filename():
    async with _serve(DoclingServeSettings()) as (stub, orchestrator):
        orchestrator.results["zip-named"] = DoclingTaskResult(
            result=ZipArchiveResult(
                content=b"PK\x03\x04",
                filename=single_document_zip_filename([PurePosixPath("report.pdf")]),
            ),
            processing_time=0.1,
            num_converted=1,
            num_succeeded=1,
            num_failed=0,
        )
        response = await stub.GetConvertResult(
            docling_serve_pb2.GetConvertResultRequest(
                request=types_pb2.TaskResultRequest(task_id="zip-named")
            )
        )
        assert response.WhichOneof("result") == "zip_archive"
        assert response.zip_archive.HasField("filename")
        assert response.zip_archive.filename == "report.zip"


@pytest.mark.parametrize(
    ("files", "expected"),
    [(["in/report.pdf"], "report.zip"), (["a.pdf", "b.pdf"], None)],
)
def test_jobkit_310_process_exportable_results_zip_name_reaches_grpc(
    tmp_path, files, expected
):
    from docling.datamodel.base_models import ConversionStatus
    from docling_core.types.doc.document import DoclingDocument
    from docling_jobkit.convert.results import process_exportable_results
    from docling_jobkit.datamodel.exportable_document import ExportableDocument
    from docling_jobkit.datamodel.task import Task
    from docling_jobkit.datamodel.task_meta import TaskType

    from docling_serve.grpc.mapping import (
        set_convert_result,
        to_task_sources,
        to_task_target,
    )

    options = to_convert_options(
        types_pb2.ConvertDocumentOptions(
            to_formats=[types_pb2.OutputFormat.OUTPUT_FORMAT_MARKDOWN]
        )
    )
    task = Task(
        task_id="zip-producer",
        task_type=TaskType.CONVERT,
        sources=to_task_sources(
            [
                types_pb2.Source(
                    file=types_pb2.FileSource(
                        base64_string="JVBERg==", filename=PurePosixPath(f).name
                    )
                )
                for f in files
            ]
        ),
        target=to_task_target(types_pb2.Target(zip=types_pb2.ZipTarget())),
        convert_options=options,
    )
    docs = [
        ExportableDocument(
            file=PurePosixPath(f),
            status=ConversionStatus.SUCCESS,
            document=DoclingDocument(name=PurePosixPath(f).stem),
        )
        for f in files
    ]
    task_result = process_exportable_results(
        task=task, exportable_documents=docs, work_dir=tmp_path
    )
    assert isinstance(task_result.result, ZipArchiveResult)
    assert task_result.result.filename == expected

    message = docling_serve_pb2.GetConvertResultResponse()
    set_convert_result(message, task_result, None)
    assert message.WhichOneof("result") == "zip_archive"
    assert message.zip_archive.content.startswith(b"PK")
    if expected is None:
        assert not message.zip_archive.HasField("filename")
    else:
        assert message.zip_archive.filename == expected


# --- chunker that cannot load its tokenizer ------------------------------------
# On krick test_grpc_serve.py::test_chunk_hybrid_source_sync failed because the
# HF tokenizer fetch returned 401 (rejected HF_TOKEN in the environment). Jobkit
# 3.10.0 logged the error and returned a ChunkedDocumentResult with no chunks
# and the document still SUCCESS, on REST and gRPC alike. The fork's jobkit now
# raises ChunkingError when no document could be chunked, so the task fails and
# gRPC carries the typed task failure. Per-document failures stay on the
# document. End-to-end REST and gRPC coverage is in
# test_chunker_failure_surfacing.py.


class _TokenizerUnavailableChunker:
    def chunk_document(self, *, document, filename, options):
        raise OSError("401 Client Error: tokenizer fetch rejected")


def test_hybrid_chunker_tokenizer_failure_maps_to_typed_grpc_failure(tmp_path):
    from docling.datamodel.base_models import ConversionStatus
    from docling.datamodel.service.responses import FailureCategory, FailurePhase
    from docling_core.types.doc.document import DoclingDocument
    from docling_jobkit.convert.chunking import process_chunkable_results
    from docling_jobkit.datamodel.exportable_document import ExportableDocument
    from docling_jobkit.datamodel.stored_outcome import StoredFailureOutcome
    from docling_jobkit.datamodel.task import Task
    from docling_jobkit.datamodel.task_meta import TaskType
    from docling_jobkit.public_errors import (
        ChunkingError,
        classify_public_task_failure,
    )

    from docling_serve.grpc.mapping import (
        task_failure_to_proto,
        to_task_sources,
        to_task_target,
    )

    task = Task(
        task_id="chunk-tokenizer-401",
        task_type=TaskType.CHUNK,
        sources=to_task_sources([_source()]),
        target=to_task_target(types_pb2.Target(inbody=types_pb2.InBodyTarget())),
        convert_options=to_convert_options(types_pb2.ConvertDocumentOptions()),
    )
    with pytest.raises(ChunkingError) as excinfo:
        process_chunkable_results(
            task=task,
            exportable_documents=[
                ExportableDocument(
                    file=PurePosixPath("report.pdf"),
                    status=ConversionStatus.SUCCESS,
                    document=DoclingDocument(name="report"),
                )
            ],
            work_dir=tmp_path,
            chunker_manager=_TokenizerUnavailableChunker(),
        )

    failure = classify_public_task_failure(
        excinfo.value, task_id=task.task_id, phase=FailurePhase.EXECUTION
    )
    outcome = StoredFailureOutcome(failure=failure)
    message = docling_serve_pb2.GetChunkResultResponse()
    message.failure.CopyFrom(task_failure_to_proto(outcome.failure))
    assert message.WhichOneof("result") == "failure"
    assert failure.category == FailureCategory.BACKEND_FAILURE
    assert message.failure.failure.category == (
        types_pb2.FailureCategory.FAILURE_CATEGORY_BACKEND_FAILURE
    )
    assert message.failure.failure.phase == (
        types_pb2.FailurePhase.FAILURE_PHASE_EXECUTION
    )
    assert message.failure.failure.message == "Document chunking failed (OSError)."
    assert message.failure.failure.retryable is False
    assert len(message.response.chunks) == 0
