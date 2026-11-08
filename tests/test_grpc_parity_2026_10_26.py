"""Parity coverage for the 2026-10-26 serve sync.

Covers target_document_version, ResponseFormat through docling 2.142.1,
response_format_raw, and BaseVlmEngineOptions.trust_remote_code.
"""

import json
from types import SimpleNamespace

import grpc
import pytest

from docling.datamodel.base_models import OutputFormat
from docling.datamodel.pipeline_options_vlm_model import ResponseFormat
from docling.datamodel.vlm_engine_options import (
    AutoInlineVlmEngineOptions,
    MlxVlmEngineOptions,
    TransformersVlmEngineOptions,
    VllmVlmEngineOptions,
)
from docling.models.inference_engines.vlm.base import (
    BaseVlmEngineOptions,
    VlmEngineType,
)
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel

from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2,
    docling_serve_types_pb2,
)
from docling_serve.grpc.mapping import (
    _build_exports,
    _map_response_format,
    _to_base_vlm_engine_options,
    _to_vlm_model_api,
    _to_vlm_model_local,
    _to_vlm_model_spec,
    document_response_to_proto,
    validate_target_document_version,
)
from tests.test_grpc_service_fake import (
    FakeOrchestrator,
    _batch_request,
    _file_convert_request,
    _server_with,
)

pb = docling_serve_types_pb2


def test_response_format_enum_matches_docling():
    """Every docling ResponseFormat member has one proto tag, and no extras."""
    proto_names = {value.name for value in pb.ResponseFormat.DESCRIPTOR.values}
    expected = {"RESPONSE_FORMAT_UNSPECIFIED"} | {
        f"RESPONSE_FORMAT_{member.name}" for member in ResponseFormat
    }
    assert proto_names == expected
    for member in ResponseFormat:
        proto_value = getattr(pb, f"RESPONSE_FORMAT_{member.name}")
        assert _map_response_format(proto_value) is member
        local = _to_vlm_model_local(
            pb.VlmModelLocal(
                repo_id="org/model",
                inference_framework=pb.INFERENCE_FRAMEWORK_TRANSFORMERS,
                response_format=proto_value,
            )
        )
        assert local.response_format is member


def test_response_format_raw_round_trip_and_not_dropped():
    raw = "nemotron_parse_v3_5"
    spec = pb.VlmModelSpec(
        name="custom",
        default_repo_id="org/model",
        prompt="convert",
        response_format_raw=raw,
    )
    again = pb.VlmModelSpec()
    again.ParseFromString(spec.SerializeToString())
    assert again.response_format_raw == raw
    assert again.HasField("response_format_raw")
    mapped = _to_vlm_model_spec(again)
    assert mapped.response_format == ResponseFormat.NEMOTRON_PARSE_V3_5

    api = _to_vlm_model_api(
        pb.VlmModelApi(url="https://example.invalid/v1", response_format_raw=raw)
    )
    assert api.response_format == ResponseFormat.NEMOTRON_PARSE_V3_5


def test_response_format_raw_disagreement_and_unknown_are_rejected():
    with pytest.raises(ValueError, match="disagree"):
        _to_vlm_model_local(
            pb.VlmModelLocal(
                response_format=pb.RESPONSE_FORMAT_MARKDOWN,
                response_format_raw="html",
            )
        )
    unknown = pb.VlmModelLocal()
    unknown.response_format = 99
    with pytest.raises(ValueError, match="not a known format"):
        _to_vlm_model_local(unknown)
    with pytest.raises(ValueError, match="unspecified"):
        _to_vlm_model_spec(
            pb.VlmModelSpec(
                name="custom",
                default_repo_id="org/model",
                prompt="convert",
                response_format=pb.RESPONSE_FORMAT_UNSPECIFIED,
            )
        )
    with pytest.raises(ValueError, match="response_format"):
        _to_vlm_model_api(
            pb.VlmModelApi(
                url="https://example.invalid/v1",
                response_format_raw="not-a-format",
            )
        )


def test_trust_remote_code_inline_engines_and_api_rejection():
    cases = [
        (pb.VLM_ENGINE_TYPE_AUTO_INLINE, AutoInlineVlmEngineOptions),
        (pb.VLM_ENGINE_TYPE_TRANSFORMERS, TransformersVlmEngineOptions),
        (pb.VLM_ENGINE_TYPE_MLX, MlxVlmEngineOptions),
        (pb.VLM_ENGINE_TYPE_VLLM, VllmVlmEngineOptions),
    ]
    for engine, cls in cases:
        mapped = _to_base_vlm_engine_options(
            pb.BaseVlmEngineOptions(engine_type=engine, trust_remote_code=True)
        )
        assert type(mapped) is cls
        assert mapped.trust_remote_code is True
        unset = _to_base_vlm_engine_options(pb.BaseVlmEngineOptions(engine_type=engine))
        assert type(unset) is BaseVlmEngineOptions
        assert unset.engine_type == mapped.engine_type

    for engine in (
        pb.VLM_ENGINE_TYPE_API,
        pb.VLM_ENGINE_TYPE_API_OLLAMA,
        pb.VLM_ENGINE_TYPE_API_LMSTUDIO,
        pb.VLM_ENGINE_TYPE_API_OPENAI,
    ):
        with pytest.raises(ValueError, match="API"):
            _to_base_vlm_engine_options(
                pb.BaseVlmEngineOptions(engine_type=engine, trust_remote_code=True)
            )
        plain = _to_base_vlm_engine_options(pb.BaseVlmEngineOptions(engine_type=engine))
        assert type(plain) is BaseVlmEngineOptions
        assert VlmEngineType.is_api_variant(plain.engine_type)

    with pytest.raises(ValueError, match="known VLM engine_type"):
        _to_base_vlm_engine_options(pb.BaseVlmEngineOptions(trust_remote_code=True))


def test_target_document_version_validation():
    assert validate_target_document_version(None) is None
    assert validate_target_document_version("") is None
    assert validate_target_document_version("1.5.0") == "1.5.0"
    assert validate_target_document_version("2.0.0") == "2.0.0"
    with pytest.raises(ValueError, match="unparseable"):
        validate_target_document_version("1.5")
    with pytest.raises(ValueError, match="unparseable"):
        validate_target_document_version("12345678901.0.0")
    with pytest.raises(ValueError, match="oldest supported"):
        validate_target_document_version("1.4.9")


def test_target_document_version_proto_round_trip():
    request = pb.ConvertDocumentRequest(target_document_version="1.10.0")
    again = pb.ConvertDocumentRequest()
    again.ParseFromString(request.SerializeToString())
    assert again.target_document_version == "1.10.0"
    batch = pb.BatchConvertDocumentRequest(target_document_version="1.5.0")
    batch_again = pb.BatchConvertDocumentRequest()
    batch_again.ParseFromString(batch.SerializeToString())
    assert batch_again.target_document_version == "1.5.0"
    for message_name in ("HierarchicalChunkRequest", "HybridChunkRequest"):
        descriptor = pb.DESCRIPTOR.message_types_by_name[message_name]
        assert "target_document_version" not in descriptor.fields_by_name


def _sample_document() -> DoclingDocument:
    doc = DoclingDocument(name="sample")
    doc.add_text(label=DocItemLabel.TEXT, text="hello")
    return doc


def test_json_export_is_projected_and_typed_doc_stays_current():
    doc = _sample_document()
    payload = SimpleNamespace(filename="a.pdf", json_content=doc)
    message = document_response_to_proto(
        payload, {OutputFormat.JSON}, target_document_version="1.5.0"
    )
    projected = json.loads(message.exports.json)
    assert projected["version"] == "1.5.0"
    assert "meta" not in json.dumps(projected)
    assert projected["texts"][0]["text"] == "hello"
    assert message.doc.version == doc.version
    assert message.doc.version != "1.5.0"

    untouched = _build_exports(
        payload, {OutputFormat.JSON}, target_document_version=None
    )
    assert json.loads(untouched.json)["version"] == doc.version


@pytest.mark.asyncio
async def test_convert_rejects_bad_document_version():
    request = _file_convert_request()
    request.request.target_document_version = "1.0.0"
    async with _server_with(orchestrator=FakeOrchestrator()) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSource(request)
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "oldest supported" in exc_info.value.details()

    request.request.target_document_version = "nope"
    async with _server_with(orchestrator=FakeOrchestrator()) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSource(request)
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "unparseable" in exc_info.value.details()


@pytest.mark.asyncio
async def test_convert_and_batch_pass_version_and_project_json():
    orchestrator = FakeOrchestrator()
    request = _file_convert_request()
    request.request.target_document_version = "1.5.0"
    request.request.options.to_formats.append(pb.OUTPUT_FORMAT_JSON)
    async with _server_with(orchestrator=orchestrator) as stub:
        response = await stub.ConvertSource(request)
    assert orchestrator.enqueue_kwargs[0]["target_document_version"] == "1.5.0"
    task = next(iter(orchestrator.tasks.values()))
    assert task.target_document_version == "1.5.0"
    projected = json.loads(response.response.document.exports.json)
    assert projected["version"] == "1.5.0"
    assert response.response.document.doc.version != "1.5.0"

    batch_orchestrator = FakeOrchestrator()
    batch = _batch_request(target_document_version="1.5.0")
    async with _server_with(orchestrator=batch_orchestrator) as stub:
        await stub.ConvertSourceBatch(batch)
    assert batch_orchestrator.enqueue_kwargs[0]["target_document_version"] == "1.5.0"
    bad = _batch_request(target_document_version="0.1.0")
    async with _server_with(orchestrator=FakeOrchestrator()) as stub:
        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await stub.ConvertSourceBatch(bad)
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_get_convert_result_projects_from_task_version():
    orchestrator = FakeOrchestrator()
    request = docling_serve_pb2.ConvertSourceAsyncRequest(
        request=_file_convert_request().request
    )
    request.request.target_document_version = "1.5.0"
    request.request.options.to_formats.append(pb.OUTPUT_FORMAT_JSON)
    async with _server_with(orchestrator=orchestrator) as stub:
        status = await stub.ConvertSourceAsync(request)
        task_id = status.response.task_id
        response = await stub.GetConvertResult(
            docling_serve_pb2.GetConvertResultRequest(
                request=pb.TaskResultRequest(task_id=task_id)
            )
        )
    projected = json.loads(response.response.document.exports.json)
    assert projected["version"] == "1.5.0"
    assert response.response.document.doc.version != "1.5.0"
