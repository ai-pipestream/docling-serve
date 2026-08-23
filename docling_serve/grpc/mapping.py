from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Optional

from docling.datamodel.base_models import InputFormat, OutputFormat
from docling.datamodel.pipeline_options import (
    CodeFormulaVlmOptions,
    HeadingHierarchyOptions,
    PdfBackend,
    PictureDescriptionVlmEngineOptions,
    ProcessingPipeline,
    TableFormerMode,
    VlmConvertOptions,
)
from docling.datamodel.pipeline_options_vlm_model import (
    InferenceFramework,
    ResponseFormat,
    TransformersModelType,
)
from docling.datamodel.service.options import (
    PictureDescriptionApi,
    PictureDescriptionLocal,
    VlmModelApi,
    VlmModelLocal,
)
from docling.datamodel.service.requests import (
    AzureBlobSourceRequest,
    FileSourceRequest,
    GenericSourceRequest,
    GoogleCloudStorageSourceRequest,
    GoogleDriveSourceRequest,
    HttpSourceRequest,
    S3SourceRequest,
)
from docling.datamodel.service.sources import (
    GoogleCloudStorageServiceAccountInfo,
    GoogleDriveCredentials,
)
from docling.datamodel.service.targets import (
    AzureBlobTarget,
    GoogleCloudStorageTarget,
    GoogleDriveTarget,
    InBodyTarget,
    PresignedUrlTarget,
    PutTarget,
    S3Target,
    ZipTarget,
)
from docling.datamodel.stage_model_specs import (
    ApiModelConfig,
    EngineModelConfig,
    VlmModelSpec,
)
from docling.datamodel.vlm_model_specs import VlmModelType
from docling.models.inference_engines.vlm.base import (
    BaseVlmEngineOptions,
    VlmEngineType,
)
from docling.utils.profiling import ProfilingItem
from docling_core.types.doc import ImageRefMode
from docling_core.types.doc.labels import PictureClassificationLabel
from docling_jobkit.datamodel.chunking import (
    HierarchicalChunkerOptions,
    HybridChunkerOptions,
)
from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus

from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions
from docling_serve.settings import docling_serve_settings

from .docling_document_converter import docling_document_to_proto
from docling_core.proto.gen.ai.docling.core.v1 import docling_document_pb2
from .gen.ai.docling.serve.v1 import docling_serve_types_pb2

_log = logging.getLogger(__name__)


# -------------------- Proto -> Python domain --------------------


def _enum_name(enum_cls, value: int) -> Optional[str]:
    if value == 0:
        return None
    try:
        return enum_cls.Name(value)
    except Exception:
        return None


def _map_input_format(value: int) -> Optional[InputFormat]:
    name = _enum_name(docling_serve_types_pb2.InputFormat, value)
    if not name:
        return None
    mapping = {
        "INPUT_FORMAT_ASCIIDOC": InputFormat.ASCIIDOC,
        "INPUT_FORMAT_AUDIO": InputFormat.AUDIO,
        "INPUT_FORMAT_CSV": InputFormat.CSV,
        "INPUT_FORMAT_DOCX": InputFormat.DOCX,
        "INPUT_FORMAT_HTML": InputFormat.HTML,
        "INPUT_FORMAT_IMAGE": InputFormat.IMAGE,
        "INPUT_FORMAT_JSON_DOCLING": InputFormat.JSON_DOCLING,
        "INPUT_FORMAT_MD": InputFormat.MD,
        "INPUT_FORMAT_METS_GBS": InputFormat.METS_GBS,
        "INPUT_FORMAT_PDF": InputFormat.PDF,
        "INPUT_FORMAT_PPTX": InputFormat.PPTX,
        "INPUT_FORMAT_XLSX": InputFormat.XLSX,
        "INPUT_FORMAT_XML_JATS": InputFormat.XML_JATS,
        "INPUT_FORMAT_XML_USPTO": InputFormat.XML_USPTO,
        "INPUT_FORMAT_LATEX": InputFormat.LATEX,
        "INPUT_FORMAT_VTT": InputFormat.VTT,
        "INPUT_FORMAT_XML_XBRL": InputFormat.XML_XBRL,
        "INPUT_FORMAT_DOC": InputFormat.DOC,
        "INPUT_FORMAT_PPT": InputFormat.PPT,
        "INPUT_FORMAT_XLS": InputFormat.XLS,
        "INPUT_FORMAT_ODT": InputFormat.ODT,
        "INPUT_FORMAT_ODS": InputFormat.ODS,
        "INPUT_FORMAT_ODP": InputFormat.ODP,
        "INPUT_FORMAT_XML_DOCLANG": InputFormat.XML_DOCLANG,
        "INPUT_FORMAT_DCLX": InputFormat.DCLX,
        "INPUT_FORMAT_EMAIL": InputFormat.EMAIL,
        "INPUT_FORMAT_EPUB": InputFormat.EPUB,
        "INPUT_FORMAT_VIDEO": InputFormat.VIDEO,
        "INPUT_FORMAT_BOXNOTE": InputFormat.BOXNOTE,
        "INPUT_FORMAT_IWORK_PAGES": InputFormat.IWORK_PAGES,
        "INPUT_FORMAT_EBCDIC": InputFormat.EBCDIC,
    }
    return mapping.get(name)


def _map_output_format(value: int) -> Optional[OutputFormat]:
    name = _enum_name(docling_serve_types_pb2.OutputFormat, value)
    if not name:
        return None
    mapping = {
        "OUTPUT_FORMAT_DOCTAGS": OutputFormat.DOCTAGS,
        "OUTPUT_FORMAT_HTML": OutputFormat.HTML,
        "OUTPUT_FORMAT_HTML_SPLIT_PAGE": OutputFormat.HTML_SPLIT_PAGE,
        "OUTPUT_FORMAT_JSON": OutputFormat.JSON,
        "OUTPUT_FORMAT_MARKDOWN": OutputFormat.MARKDOWN,
        "OUTPUT_FORMAT_TEXT": OutputFormat.TEXT,
        "OUTPUT_FORMAT_YAML": OutputFormat.YAML,
        "OUTPUT_FORMAT_VTT": OutputFormat.VTT,
        "OUTPUT_FORMAT_DOCLANG": OutputFormat.DOCLANG,
        "OUTPUT_FORMAT_DCLX": OutputFormat.DCLX,
        "OUTPUT_FORMAT_CHUNKS": OutputFormat.CHUNKS,
    }
    return mapping.get(name)


def _map_image_ref_mode(value: int) -> Optional[ImageRefMode]:
    name = _enum_name(docling_serve_types_pb2.ImageRefMode, value)
    if not name:
        return None
    mapping = {
        "IMAGE_REF_MODE_EMBEDDED": ImageRefMode.EMBEDDED,
        "IMAGE_REF_MODE_PLACEHOLDER": ImageRefMode.PLACEHOLDER,
        "IMAGE_REF_MODE_REFERENCED": ImageRefMode.REFERENCED,
    }
    return mapping.get(name)


def _map_ocr_engine(value: int) -> Optional[str]:
    name = _enum_name(docling_serve_types_pb2.OcrEngine, value)
    if not name:
        return None
    mapping = {
        "OCR_ENGINE_AUTO": "auto",
        "OCR_ENGINE_EASYOCR": "easyocr",
        "OCR_ENGINE_OCRMAC": "ocrmac",
        "OCR_ENGINE_RAPIDOCR": "rapidocr",
        "OCR_ENGINE_TESSEROCR": "tesserocr",
        "OCR_ENGINE_TESSERACT": "tesseract",
    }
    return mapping.get(name)


def _map_pdf_backend(value: int) -> Optional[PdfBackend]:
    name = _enum_name(docling_serve_types_pb2.PdfBackend, value)
    if not name:
        return None
    mapping = {
        "PDF_BACKEND_PYPDFIUM2": PdfBackend.PYPDFIUM2,
        "PDF_BACKEND_DOCLING_PARSE": PdfBackend.DOCLING_PARSE,
        "PDF_BACKEND_DLPARSE_V1": PdfBackend.DLPARSE_V1,
        "PDF_BACKEND_DLPARSE_V2": PdfBackend.DLPARSE_V2,
        "PDF_BACKEND_DLPARSE_V4": PdfBackend.DLPARSE_V4,
    }
    return mapping.get(name)


def _map_table_mode(value: int) -> Optional[TableFormerMode]:
    name = _enum_name(docling_serve_types_pb2.TableFormerMode, value)
    if not name:
        return None
    mapping = {
        "TABLE_FORMER_MODE_FAST": TableFormerMode.FAST,
        "TABLE_FORMER_MODE_ACCURATE": TableFormerMode.ACCURATE,
    }
    return mapping.get(name)


def _map_pipeline(value: int) -> Optional[ProcessingPipeline]:
    name = _enum_name(docling_serve_types_pb2.ProcessingPipeline, value)
    if not name:
        return None
    mapping = {
        "PROCESSING_PIPELINE_ASR": ProcessingPipeline.ASR,
        "PROCESSING_PIPELINE_LEGACY": ProcessingPipeline.LEGACY,
        "PROCESSING_PIPELINE_STANDARD": ProcessingPipeline.STANDARD,
        "PROCESSING_PIPELINE_VLM": ProcessingPipeline.VLM,
    }
    return mapping.get(name)


def _map_vlm_model_type(value: int) -> Optional[VlmModelType]:
    name = _enum_name(docling_serve_types_pb2.VlmModelType, value)
    if not name:
        return None
    mapping = {
        "VLM_MODEL_TYPE_SMOLDOCLING": VlmModelType.SMOLDOCLING,
        "VLM_MODEL_TYPE_SMOLDOCLING_VLLM": VlmModelType.SMOLDOCLING_VLLM,
        "VLM_MODEL_TYPE_GRANITE_VISION": VlmModelType.GRANITE_VISION,
        "VLM_MODEL_TYPE_GRANITE_VISION_VLLM": VlmModelType.GRANITE_VISION_VLLM,
        "VLM_MODEL_TYPE_GRANITE_VISION_OLLAMA": VlmModelType.GRANITE_VISION_OLLAMA,
        "VLM_MODEL_TYPE_GOT_OCR_2": VlmModelType.GOT_OCR_2,
        "VLM_MODEL_TYPE_GRANITEDOCLING": VlmModelType.GRANITEDOCLING,
        "VLM_MODEL_TYPE_GRANITEDOCLING_VLLM": VlmModelType.GRANITEDOCLING_VLLM,
        "VLM_MODEL_TYPE_DEEPSEEKOCR_OLLAMA": VlmModelType.DEEPSEEKOCR_OLLAMA,
        "VLM_MODEL_TYPE_NANONETS_OCR2": VlmModelType.NANONETS_OCR2,
        "VLM_MODEL_TYPE_NANONETS_OCR2_VLLM": VlmModelType.NANONETS_OCR2_VLLM,
        "VLM_MODEL_TYPE_NANONETS_OCR2_LMSTUDIO": VlmModelType.NANONETS_OCR2_LMSTUDIO,
        "VLM_MODEL_TYPE_GLMOCR": VlmModelType.GLMOCR,
        "VLM_MODEL_TYPE_GLMOCR_VLLM": VlmModelType.GLMOCR_VLLM,
        "VLM_MODEL_TYPE_LIGHTONOCR": VlmModelType.LIGHTONOCR,
        "VLM_MODEL_TYPE_LIGHTONOCR_VLLM": VlmModelType.LIGHTONOCR_VLLM,
    }
    return mapping.get(name)


def _map_response_format(value: int) -> Optional[ResponseFormat]:
    name = _enum_name(docling_serve_types_pb2.ResponseFormat, value)
    if not name:
        return None
    mapping = {
        "RESPONSE_FORMAT_DOCTAGS": ResponseFormat.DOCTAGS,
        "RESPONSE_FORMAT_MARKDOWN": ResponseFormat.MARKDOWN,
        "RESPONSE_FORMAT_HTML": ResponseFormat.HTML,
        "RESPONSE_FORMAT_OTSL": ResponseFormat.OTSL,
        "RESPONSE_FORMAT_PLAINTEXT": ResponseFormat.PLAINTEXT,
    }
    return mapping.get(name)


def _map_inference_framework(value: int) -> Optional[InferenceFramework]:
    name = _enum_name(docling_serve_types_pb2.InferenceFramework, value)
    if not name:
        return None
    mapping = {
        "INFERENCE_FRAMEWORK_MLX": InferenceFramework.MLX,
        "INFERENCE_FRAMEWORK_TRANSFORMERS": InferenceFramework.TRANSFORMERS,
        "INFERENCE_FRAMEWORK_VLLM": InferenceFramework.VLLM,
    }
    return mapping.get(name)


def _map_transformers_model_type(value: int) -> Optional[TransformersModelType]:
    name = _enum_name(docling_serve_types_pb2.TransformersModelType, value)
    if not name:
        return None
    mapping = {
        "TRANSFORMERS_MODEL_TYPE_AUTOMODEL": TransformersModelType.AUTOMODEL,
        "TRANSFORMERS_MODEL_TYPE_AUTOMODEL_IMAGETEXTTOTEXT": TransformersModelType.AUTOMODEL_IMAGETEXTTOTEXT,
        "TRANSFORMERS_MODEL_TYPE_AUTOMODEL_CAUSALLM": TransformersModelType.AUTOMODEL_CAUSALLM,
    }
    return mapping.get(name)


def _scalar_value_to_python(value: docling_serve_types_pb2.ScalarValue):
    """Decode a ScalarValue oneof to a Python scalar (no JSON)."""
    kind = value.WhichOneof("kind")
    if kind == "string_value":
        return value.string_value
    if kind == "int_value":
        return value.int_value
    if kind == "double_value":
        return value.double_value
    if kind == "bool_value":
        return value.bool_value
    return None


def _scalar_map_to_dict(proto_map) -> dict:
    return {k: _scalar_value_to_python(v) for k, v in proto_map.items()}


def _map_picture_classification_labels(values) -> list[PictureClassificationLabel]:
    out: list[PictureClassificationLabel] = []
    for value in values:
        name = _enum_name(docling_serve_types_pb2.PictureClassificationLabel, value)
        if not name or name.endswith("_UNSPECIFIED"):
            continue
        member = name.removeprefix("PICTURE_CLASSIFICATION_LABEL_")
        try:
            out.append(PictureClassificationLabel[member])
        except KeyError:
            continue
    return out


def _map_vlm_engine_type(value: int) -> Optional[VlmEngineType]:
    name = _enum_name(docling_serve_types_pb2.VlmEngineType, value)
    if not name:
        return None
    mapping = {
        "VLM_ENGINE_TYPE_TRANSFORMERS": VlmEngineType.TRANSFORMERS,
        "VLM_ENGINE_TYPE_MLX": VlmEngineType.MLX,
        "VLM_ENGINE_TYPE_VLLM": VlmEngineType.VLLM,
        "VLM_ENGINE_TYPE_API": VlmEngineType.API,
        "VLM_ENGINE_TYPE_API_OLLAMA": VlmEngineType.API_OLLAMA,
        "VLM_ENGINE_TYPE_API_LMSTUDIO": VlmEngineType.API_LMSTUDIO,
        "VLM_ENGINE_TYPE_API_OPENAI": VlmEngineType.API_OPENAI,
        "VLM_ENGINE_TYPE_AUTO_INLINE": VlmEngineType.AUTO_INLINE,
    }
    return mapping.get(name)


def _to_service_account_info(proto) -> GoogleCloudStorageServiceAccountInfo:
    data = {
        "project_id": proto.project_id,
        "private_key_id": proto.private_key_id,
        "private_key": proto.private_key,
        "client_email": proto.client_email,
        "client_id": proto.client_id,
        "auth_uri": proto.auth_uri,
        "token_uri": proto.token_uri,
        "auth_provider_x509_cert_url": proto.auth_provider_x509_cert_url,
        "client_x509_cert_url": proto.client_x509_cert_url,
    }
    if proto.HasField("universe_domain"):
        data["universe_domain"] = proto.universe_domain
    return GoogleCloudStorageServiceAccountInfo.model_validate(data)


def _to_google_drive_credentials(proto) -> GoogleDriveCredentials:
    return GoogleDriveCredentials.model_validate(
        {
            "client_id": proto.client_id,
            "project_id": proto.project_id,
            "auth_uri": proto.auth_uri,
            "token_uri": proto.token_uri,
            "auth_provider_x509_cert_url": proto.auth_provider_x509_cert_url,
            "client_secret": proto.client_secret,
            "redirect_uris": list(proto.redirect_uris),
        }
    )


def _to_engine_model_config(proto) -> EngineModelConfig:
    data: dict = {}
    if proto.HasField("repo_id"):
        data["repo_id"] = proto.repo_id
    if proto.HasField("revision"):
        data["revision"] = proto.revision
    if proto.HasField("torch_dtype"):
        data["torch_dtype"] = proto.torch_dtype
    if proto.extra_config:
        data["extra_config"] = _scalar_map_to_dict(proto.extra_config)
    return EngineModelConfig.model_validate(data)


def _to_api_model_config(proto) -> ApiModelConfig:
    data: dict = {}
    if proto.params:
        data["params"] = _scalar_map_to_dict(proto.params)
    return ApiModelConfig.model_validate(data)


def _to_vlm_model_spec(proto) -> VlmModelSpec:
    data: dict = {
        "name": proto.name,
        "default_repo_id": proto.default_repo_id,
    }
    if proto.HasField("revision"):
        data["revision"] = proto.revision
    if proto.HasField("prompt"):
        data["prompt"] = proto.prompt
    if proto.HasField("response_format"):
        val = _map_response_format(proto.response_format)
        if val is not None:
            data["response_format"] = val
    if proto.supported_engines:
        engines = [
            e for e in (_map_vlm_engine_type(v) for v in proto.supported_engines) if e
        ]
        if engines:
            data["supported_engines"] = set(engines)
    if proto.engine_overrides:
        data["engine_overrides"] = {
            eng: _to_engine_model_config(entry.config)
            for entry in proto.engine_overrides
            if (eng := _map_vlm_engine_type(entry.engine_type)) is not None
        }
    if proto.api_overrides:
        data["api_overrides"] = {
            eng: _to_api_model_config(entry.config)
            for entry in proto.api_overrides
            if (eng := _map_vlm_engine_type(entry.engine_type)) is not None
        }
    if proto.HasField("trust_remote_code"):
        data["trust_remote_code"] = proto.trust_remote_code
    if proto.stop_strings:
        data["stop_strings"] = list(proto.stop_strings)
    if proto.HasField("temperature"):
        data["temperature"] = proto.temperature
    if proto.HasField("max_new_tokens"):
        data["max_new_tokens"] = proto.max_new_tokens
    if proto.extra_generation_config:
        data["extra_generation_config"] = _scalar_map_to_dict(
            proto.extra_generation_config
        )
    return VlmModelSpec.model_validate(data)


def _to_base_vlm_engine_options(proto) -> BaseVlmEngineOptions:
    engine = _map_vlm_engine_type(proto.engine_type) or VlmEngineType.TRANSFORMERS
    return BaseVlmEngineOptions(engine_type=engine)


def _to_vlm_convert_options(proto) -> VlmConvertOptions:
    data: dict = {
        "engine_options": _to_base_vlm_engine_options(proto.engine_options),
        "model_spec": _to_vlm_model_spec(proto.model_spec),
    }
    if proto.HasField("scale"):
        data["scale"] = proto.scale
    if proto.HasField("max_size"):
        data["max_size"] = proto.max_size
    if proto.HasField("batch_size"):
        data["batch_size"] = proto.batch_size
    if proto.HasField("force_backend_text"):
        data["force_backend_text"] = proto.force_backend_text
    return VlmConvertOptions.model_validate(data)


def _to_picture_description_vlm_engine_options(
    proto,
) -> PictureDescriptionVlmEngineOptions:
    data: dict = {
        "engine_options": _to_base_vlm_engine_options(proto.engine_options),
        "model_spec": _to_vlm_model_spec(proto.model_spec),
    }
    if proto.HasField("batch_size"):
        data["batch_size"] = proto.batch_size
    if proto.HasField("scale"):
        data["scale"] = proto.scale
    if proto.HasField("picture_area_threshold"):
        data["picture_area_threshold"] = proto.picture_area_threshold
    if proto.classification_allow:
        data["classification_allow"] = _map_picture_classification_labels(
            proto.classification_allow
        )
    if proto.classification_deny:
        data["classification_deny"] = _map_picture_classification_labels(
            proto.classification_deny
        )
    if proto.HasField("classification_min_confidence"):
        data["classification_min_confidence"] = proto.classification_min_confidence
    if proto.HasField("prompt"):
        data["prompt"] = proto.prompt
    if proto.generation_config:
        data["generation_config"] = _scalar_map_to_dict(proto.generation_config)
    return PictureDescriptionVlmEngineOptions.model_validate(data)


def _to_code_formula_vlm_options(proto) -> CodeFormulaVlmOptions:
    data: dict = {
        "engine_options": _to_base_vlm_engine_options(proto.engine_options),
        "model_spec": _to_vlm_model_spec(proto.model_spec),
    }
    if proto.HasField("scale"):
        data["scale"] = proto.scale
    if proto.HasField("max_size"):
        data["max_size"] = proto.max_size
    if proto.HasField("extract_code"):
        data["extract_code"] = proto.extract_code
    if proto.HasField("extract_formulas"):
        data["extract_formulas"] = proto.extract_formulas
    return CodeFormulaVlmOptions.model_validate(data)


def _to_vlm_model_local(proto) -> VlmModelLocal:
    data: dict = {}
    if proto.HasField("repo_id"):
        data["repo_id"] = proto.repo_id
    if proto.HasField("prompt"):
        data["prompt"] = proto.prompt
    if proto.HasField("scale"):
        data["scale"] = proto.scale
    if proto.HasField("response_format"):
        val = _map_response_format(proto.response_format)
        if val is not None:
            data["response_format"] = val
    if proto.HasField("inference_framework"):
        val = _map_inference_framework(proto.inference_framework)
        if val is not None:
            data["inference_framework"] = val
    if proto.HasField("transformers_model_type"):
        val = _map_transformers_model_type(proto.transformers_model_type)
        if val is not None:
            data["transformers_model_type"] = val
    if proto.extra_generation_config:
        data["extra_generation_config"] = _scalar_map_to_dict(
            proto.extra_generation_config
        )
    if proto.HasField("temperature"):
        data["temperature"] = proto.temperature
    return VlmModelLocal.model_validate(data)


def _to_vlm_model_api(proto) -> VlmModelApi:
    data: dict = {}
    if proto.HasField("url"):
        data["url"] = proto.url
    if proto.headers:
        data["headers"] = dict(proto.headers)
    if proto.params:
        data["params"] = _scalar_map_to_dict(proto.params)
    if proto.HasField("timeout"):
        data["timeout"] = proto.timeout
    if proto.HasField("concurrency"):
        data["concurrency"] = proto.concurrency
    if proto.HasField("prompt"):
        data["prompt"] = proto.prompt
    if proto.HasField("scale"):
        data["scale"] = proto.scale
    if proto.HasField("response_format"):
        val = _map_response_format(proto.response_format)
        if val is not None:
            data["response_format"] = val
    if proto.HasField("temperature"):
        data["temperature"] = proto.temperature
    return VlmModelApi.model_validate(data)


def to_task_sources(proto_sources: Iterable[docling_serve_types_pb2.Source]):
    sources = []
    for i, source in enumerate(proto_sources):
        kind = source.WhichOneof("source")
        if kind == "file":
            file_src = source.file
            sources.append(
                FileSourceRequest(
                    base64_string=file_src.base64_string,
                    filename=file_src.filename,
                )
            )
        elif kind == "http":
            http_src = source.http
            sources.append(
                HttpSourceRequest(
                    url=http_src.url,
                    headers=dict(http_src.headers),
                )
            )
        elif kind == "s3":
            s3_src = source.s3
            data = {
                "endpoint": s3_src.endpoint,
                "access_key": s3_src.access_key,
                "secret_key": s3_src.secret_key,
                "bucket": s3_src.bucket,
                "key_prefix": s3_src.key_prefix
                if s3_src.HasField("key_prefix")
                else "",
                "verify_ssl": s3_src.verify_ssl,
            }
            if s3_src.HasField("max_num_elements"):
                data["max_num_elements"] = s3_src.max_num_elements
            sources.append(S3SourceRequest.model_validate(data))
        elif kind == "azure_blob":
            az = source.azure_blob
            data = {
                "account_name": az.account_name,
                "container": az.container,
                "connection_string": az.connection_string,
            }
            if az.HasField("blob_prefix"):
                data["blob_prefix"] = az.blob_prefix
            if az.HasField("max_num_elements"):
                data["max_num_elements"] = az.max_num_elements
            sources.append(AzureBlobSourceRequest.model_validate(data))
        elif kind == "google_cloud_storage":
            gcs = source.google_cloud_storage
            data = {"bucket": gcs.bucket}
            if gcs.HasField("key_prefix"):
                data["key_prefix"] = gcs.key_prefix
            if gcs.HasField("max_num_elements"):
                data["max_num_elements"] = gcs.max_num_elements
            if gcs.HasField("project"):
                data["project"] = gcs.project
            if gcs.HasField("service_account_key"):
                data["service_account_key"] = _to_service_account_info(
                    gcs.service_account_key
                )
            sources.append(GoogleCloudStorageSourceRequest.model_validate(data))
        elif kind == "google_drive":
            gd = source.google_drive
            data = {"path_id": gd.path_id}
            if gd.HasField("token_path"):
                data["token_path"] = gd.token_path
            if gd.HasField("refresh_token"):
                data["refresh_token"] = gd.refresh_token
            if gd.HasField("credentials_path"):
                data["credentials_path"] = gd.credentials_path
            if gd.HasField("credentials"):
                data["credentials"] = _to_google_drive_credentials(gd.credentials)
            sources.append(GoogleDriveSourceRequest.model_validate(data))
        elif kind == "generic":
            gen = source.generic
            payload = {"kind": gen.kind}
            payload.update(_scalar_map_to_dict(gen.attributes))
            sources.append(GenericSourceRequest.model_validate(payload))
        else:
            raise ValueError(
                f"Source at index {i} has no variant set "
                "(expected file, http, s3, azure_blob, google_cloud_storage, "
                "google_drive, or generic)."
            )
    return sources


def to_task_target(proto_target: Optional[docling_serve_types_pb2.Target]):
    if proto_target is None:
        return InBodyTarget()
    kind = proto_target.WhichOneof("target")
    if kind == "zip":
        return ZipTarget()
    if kind == "put":
        return PutTarget(url=proto_target.put.url)
    if kind == "s3":
        s3_tgt = proto_target.s3
        data = {
            "endpoint": s3_tgt.endpoint,
            "access_key": s3_tgt.access_key,
            "secret_key": s3_tgt.secret_key,
            "bucket": s3_tgt.bucket,
            "key_prefix": s3_tgt.key_prefix if s3_tgt.HasField("key_prefix") else "",
            "verify_ssl": s3_tgt.verify_ssl,
        }
        if s3_tgt.HasField("max_num_elements"):
            data["max_num_elements"] = s3_tgt.max_num_elements
        return S3Target.model_validate(data)
    if kind == "presigned_url":
        return PresignedUrlTarget()
    if kind == "azure_blob":
        az = proto_target.azure_blob
        data = {
            "account_name": az.account_name,
            "container": az.container,
            "connection_string": az.connection_string,
        }
        if az.HasField("blob_prefix"):
            data["blob_prefix"] = az.blob_prefix
        if az.HasField("max_num_elements"):
            data["max_num_elements"] = az.max_num_elements
        return AzureBlobTarget.model_validate(data)
    if kind == "google_cloud_storage":
        gcs = proto_target.google_cloud_storage
        data = {"bucket": gcs.bucket}
        if gcs.HasField("key_prefix"):
            data["key_prefix"] = gcs.key_prefix
        if gcs.HasField("max_num_elements"):
            data["max_num_elements"] = gcs.max_num_elements
        if gcs.HasField("project"):
            data["project"] = gcs.project
        if gcs.HasField("service_account_key"):
            data["service_account_key"] = _to_service_account_info(
                gcs.service_account_key
            )
        return GoogleCloudStorageTarget.model_validate(data)
    if kind == "google_drive":
        gd = proto_target.google_drive
        data = {"path_id": gd.path_id}
        if gd.HasField("token_path"):
            data["token_path"] = gd.token_path
        if gd.HasField("refresh_token"):
            data["refresh_token"] = gd.refresh_token
        if gd.HasField("credentials_path"):
            data["credentials_path"] = gd.credentials_path
        if gd.HasField("credentials"):
            data["credentials"] = _to_google_drive_credentials(gd.credentials)
        return GoogleDriveTarget.model_validate(data)
    return InBodyTarget()


def requested_output_formats(
    proto_options: Optional[docling_serve_types_pb2.ConvertDocumentOptions],
) -> set[OutputFormat]:
    if not proto_options or not proto_options.to_formats:
        return set()
    values = [
        v
        for v in (_map_output_format(v) for v in proto_options.to_formats)
        if v is not None
    ]
    return set(values) if values else set()


def to_convert_options(
    proto_options: Optional[docling_serve_types_pb2.ConvertDocumentOptions],
) -> ConvertDocumentsRequestOptions:
    data: dict[str, object] = {}
    if not proto_options:
        return ConvertDocumentsRequestOptions()

    if proto_options.from_formats:
        values = [
            v
            for v in (_map_input_format(v) for v in proto_options.from_formats)
            if v is not None
        ]
        if values:
            data["from_formats"] = values

    if proto_options.to_formats:
        values = [
            v
            for v in (_map_output_format(v) for v in proto_options.to_formats)
            if v is not None
        ]
        if values:
            data["to_formats"] = values

    if proto_options.HasField("image_export_mode"):
        val = _map_image_ref_mode(proto_options.image_export_mode)
        if val is not None:
            data["image_export_mode"] = val

    if proto_options.HasField("do_ocr"):
        data["do_ocr"] = proto_options.do_ocr

    if proto_options.HasField("force_ocr"):
        data["force_ocr"] = proto_options.force_ocr

    if proto_options.HasField("ocr_engine"):
        val = _map_ocr_engine(proto_options.ocr_engine)
        if val is not None:
            data["ocr_engine"] = val

    if proto_options.ocr_lang:
        data["ocr_lang"] = list(proto_options.ocr_lang)

    if proto_options.HasField("pdf_backend"):
        val = _map_pdf_backend(proto_options.pdf_backend)
        if val is not None:
            data["pdf_backend"] = val

    if proto_options.HasField("table_mode"):
        val = _map_table_mode(proto_options.table_mode)
        if val is not None:
            data["table_mode"] = val

    if proto_options.HasField("table_cell_matching"):
        data["table_cell_matching"] = proto_options.table_cell_matching

    if proto_options.HasField("pipeline"):
        val = _map_pipeline(proto_options.pipeline)
        if val is not None:
            data["pipeline"] = val

    if proto_options.HasField("page_range"):
        span = proto_options.page_range
        data["page_range"] = (span.start, span.end)

    if proto_options.HasField("document_timeout"):
        data["document_timeout"] = proto_options.document_timeout

    if proto_options.HasField("abort_on_error"):
        data["abort_on_error"] = proto_options.abort_on_error

    if proto_options.HasField("do_table_structure"):
        data["do_table_structure"] = proto_options.do_table_structure

    if proto_options.HasField("include_images"):
        data["include_images"] = proto_options.include_images

    if proto_options.HasField("images_scale"):
        data["images_scale"] = proto_options.images_scale

    if proto_options.HasField("md_page_break_placeholder"):
        data["md_page_break_placeholder"] = proto_options.md_page_break_placeholder

    if proto_options.HasField("do_code_enrichment"):
        data["do_code_enrichment"] = proto_options.do_code_enrichment

    if proto_options.HasField("do_formula_enrichment"):
        data["do_formula_enrichment"] = proto_options.do_formula_enrichment

    if proto_options.HasField("do_picture_classification"):
        data["do_picture_classification"] = proto_options.do_picture_classification

    if proto_options.HasField("do_picture_description"):
        data["do_picture_description"] = proto_options.do_picture_description

    if proto_options.HasField("picture_description_area_threshold"):
        data["picture_description_area_threshold"] = (
            proto_options.picture_description_area_threshold
        )

    if proto_options.HasField("picture_description_local"):
        local = proto_options.picture_description_local
        local_data = {"repo_id": local.repo_id}
        if local.HasField("prompt"):
            local_data["prompt"] = local.prompt
        if local.generation_config:
            local_data["generation_config"] = _scalar_map_to_dict(
                local.generation_config
            )
        if local.classification_allow:
            local_data["classification_allow"] = _map_picture_classification_labels(
                local.classification_allow
            )
        if local.classification_deny:
            local_data["classification_deny"] = _map_picture_classification_labels(
                local.classification_deny
            )
        if local.HasField("classification_min_confidence"):
            local_data["classification_min_confidence"] = (
                local.classification_min_confidence
            )
        data["picture_description_local"] = PictureDescriptionLocal.model_validate(
            local_data
        )

    if proto_options.HasField("picture_description_api"):
        api = proto_options.picture_description_api
        api_data = {"url": api.url}
        if api.headers:
            api_data["headers"] = dict(api.headers)
        if api.params:
            api_data["params"] = _scalar_map_to_dict(api.params)
        if api.HasField("timeout"):
            api_data["timeout"] = api.timeout
        if api.HasField("concurrency"):
            api_data["concurrency"] = api.concurrency
        if api.HasField("prompt"):
            api_data["prompt"] = api.prompt
        if api.classification_allow:
            api_data["classification_allow"] = _map_picture_classification_labels(
                api.classification_allow
            )
        if api.classification_deny:
            api_data["classification_deny"] = _map_picture_classification_labels(
                api.classification_deny
            )
        if api.HasField("classification_min_confidence"):
            api_data["classification_min_confidence"] = (
                api.classification_min_confidence
            )
        data["picture_description_api"] = PictureDescriptionApi.model_validate(api_data)

    if proto_options.HasField("vlm_pipeline_model"):
        val = _map_vlm_model_type(proto_options.vlm_pipeline_model)
        if val is not None:
            data["vlm_pipeline_model"] = val

    if proto_options.HasField("vlm_pipeline_model_local"):
        data["vlm_pipeline_model_local"] = _to_vlm_model_local(
            proto_options.vlm_pipeline_model_local
        )

    if proto_options.HasField("vlm_pipeline_model_api"):
        data["vlm_pipeline_model_api"] = _to_vlm_model_api(
            proto_options.vlm_pipeline_model_api
        )

    if proto_options.HasField("do_chart_extraction"):
        data["do_chart_extraction"] = proto_options.do_chart_extraction

    if proto_options.HasField("vlm_pipeline_preset"):
        data["vlm_pipeline_preset"] = proto_options.vlm_pipeline_preset

    if proto_options.HasField("picture_description_preset"):
        data["picture_description_preset"] = proto_options.picture_description_preset

    if proto_options.HasField("code_formula_preset"):
        data["code_formula_preset"] = proto_options.code_formula_preset

    if proto_options.HasField("vlm_pipeline_custom_config"):
        data["vlm_pipeline_custom_config"] = _to_vlm_convert_options(
            proto_options.vlm_pipeline_custom_config
        )

    if proto_options.HasField("picture_description_custom_config"):
        data["picture_description_custom_config"] = (
            _to_picture_description_vlm_engine_options(
                proto_options.picture_description_custom_config
            )
        )

    if proto_options.HasField("code_formula_custom_config"):
        data["code_formula_custom_config"] = _to_code_formula_vlm_options(
            proto_options.code_formula_custom_config
        )

    if proto_options.table_structure_custom_config:
        data["table_structure_custom_config"] = _scalar_map_to_dict(
            proto_options.table_structure_custom_config
        )

    if proto_options.layout_custom_config:
        data["layout_custom_config"] = _scalar_map_to_dict(
            proto_options.layout_custom_config
        )

    if proto_options.HasField("ocr_preset"):
        data["ocr_preset"] = proto_options.ocr_preset

    if proto_options.ocr_custom_config:
        data["ocr_custom_config"] = _scalar_map_to_dict(proto_options.ocr_custom_config)

    if proto_options.HasField("table_structure_preset"):
        data["table_structure_preset"] = proto_options.table_structure_preset

    if proto_options.HasField("layout_preset"):
        data["layout_preset"] = proto_options.layout_preset

    if proto_options.HasField("picture_classification_preset"):
        data["picture_classification_preset"] = (
            proto_options.picture_classification_preset
        )

    if proto_options.picture_classification_custom_config:
        data["picture_classification_custom_config"] = _scalar_map_to_dict(
            proto_options.picture_classification_custom_config
        )

    if proto_options.HasField("include_page_images"):
        data["include_page_images"] = proto_options.include_page_images

    if proto_options.HasField("do_pdf_heading_hierarchy"):
        data["do_pdf_heading_hierarchy"] = proto_options.do_pdf_heading_hierarchy

    if proto_options.HasField("pdf_heading_hierarchy_options"):
        data["pdf_heading_hierarchy_options"] = _to_heading_hierarchy_options(
            proto_options.pdf_heading_hierarchy_options
        )

    return ConvertDocumentsRequestOptions.model_validate(data)


def _to_heading_hierarchy_options(
    proto: docling_serve_types_pb2.HeadingHierarchyOptions,
) -> HeadingHierarchyOptions:
    data: dict[str, object] = {}
    if proto.HasField("enabled"):
        data["enabled"] = proto.enabled
    if proto.HasField("use_bookmarks"):
        data["use_bookmarks"] = proto.use_bookmarks
    if proto.HasField("use_numbering"):
        data["use_numbering"] = proto.use_numbering
    if proto.HasField("use_style"):
        data["use_style"] = proto.use_style
    if proto.numbering_schemes:
        data["numbering_schemes"] = list(proto.numbering_schemes)
    if proto.HasField("max_level"):
        data["max_level"] = proto.max_level
    if proto.HasField("bookmark_match_threshold"):
        data["bookmark_match_threshold"] = proto.bookmark_match_threshold
    if proto.HasField("use_font_style"):
        data["use_font_style"] = proto.use_font_style
    if proto.HasField("style_size_tolerance"):
        data["style_size_tolerance"] = proto.style_size_tolerance
    # Only pass fields the installed Pydantic model knows (2.118 vs 2.120+).
    known = set(HeadingHierarchyOptions.model_fields)
    return HeadingHierarchyOptions.model_validate(
        {key: value for key, value in data.items() if key in known}
    )


def to_hierarchical_chunk_options(
    proto_options: Optional[docling_serve_types_pb2.HierarchicalChunkerOptions],
) -> HierarchicalChunkerOptions:
    if not proto_options:
        return HierarchicalChunkerOptions()
    data: dict[str, object] = {
        "use_markdown_tables": proto_options.use_markdown_tables,
        "include_raw_text": proto_options.include_raw_text,
    }
    if proto_options.HasField("use_markdown_images"):
        data["use_markdown_images"] = proto_options.use_markdown_images
    if proto_options.HasField("image_placeholder"):
        data["image_placeholder"] = proto_options.image_placeholder
    return HierarchicalChunkerOptions(**data)


def to_hybrid_chunk_options(
    proto_options: Optional[docling_serve_types_pb2.HybridChunkerOptions],
) -> HybridChunkerOptions:
    if not proto_options:
        return HybridChunkerOptions()
    data: dict[str, object] = {
        "use_markdown_tables": proto_options.use_markdown_tables,
        "include_raw_text": proto_options.include_raw_text,
    }
    if proto_options.HasField("max_tokens"):
        data["max_tokens"] = proto_options.max_tokens
    if proto_options.HasField("tokenizer"):
        data["tokenizer"] = proto_options.tokenizer
    if proto_options.HasField("merge_peers"):
        data["merge_peers"] = proto_options.merge_peers
    if proto_options.HasField("use_markdown_images"):
        data["use_markdown_images"] = proto_options.use_markdown_images
    if proto_options.HasField("image_placeholder"):
        data["image_placeholder"] = proto_options.image_placeholder
    return HybridChunkerOptions(**data)


# -------------------- Python domain -> Proto --------------------


def _docling_document_to_proto(doc) -> docling_document_pb2.DoclingDocument:
    return docling_document_to_proto(doc)


_COMPONENT_TYPE_TO_PROTO = {
    "document_backend": (
        docling_serve_types_pb2.DoclingComponentType.DOCLING_COMPONENT_TYPE_DOCUMENT_BACKEND
    ),
    "model": docling_serve_types_pb2.DoclingComponentType.DOCLING_COMPONENT_TYPE_MODEL,
    "doc_assembler": (
        docling_serve_types_pb2.DoclingComponentType.DOCLING_COMPONENT_TYPE_DOC_ASSEMBLER
    ),
    "user_input": (
        docling_serve_types_pb2.DoclingComponentType.DOCLING_COMPONENT_TYPE_USER_INPUT
    ),
    "pipeline": (
        docling_serve_types_pb2.DoclingComponentType.DOCLING_COMPONENT_TYPE_PIPELINE
    ),
}

_CONVERSION_STATUS_TO_PROTO = {
    "pending": docling_serve_types_pb2.ConversionStatus.CONVERSION_STATUS_PENDING,
    "started": docling_serve_types_pb2.ConversionStatus.CONVERSION_STATUS_STARTED,
    "failure": docling_serve_types_pb2.ConversionStatus.CONVERSION_STATUS_FAILURE,
    "success": docling_serve_types_pb2.ConversionStatus.CONVERSION_STATUS_SUCCESS,
    "partial_success": (
        docling_serve_types_pb2.ConversionStatus.CONVERSION_STATUS_PARTIAL_SUCCESS
    ),
    "skipped": docling_serve_types_pb2.ConversionStatus.CONVERSION_STATUS_SKIPPED,
}


def _conversion_status_enum_and_raw(status) -> tuple[int, Optional[str]]:
    """Map a docling ConversionStatus (or string) to proto enum + raw fallback.

    Follows the *_raw discriminator contract: a recognized value sets only the
    enum tag; an unrecognized value sets UNSPECIFIED and carries the original
    string in the raw companion.
    """
    value = getattr(status, "value", status)
    value = str(value)
    enum_val = _CONVERSION_STATUS_TO_PROTO.get(value)
    if enum_val is None:
        return (
            docling_serve_types_pb2.ConversionStatus.CONVERSION_STATUS_UNSPECIFIED,
            value,
        )
    return enum_val, None


def _error_item_to_proto(error) -> docling_serve_types_pb2.ErrorItem:
    component = getattr(error.component_type, "value", error.component_type)
    component = str(component)
    message = docling_serve_types_pb2.ErrorItem(
        error_message=error.error_message,
        module_name=error.module_name,
    )
    enum_val = _COMPONENT_TYPE_TO_PROTO.get(component)
    if enum_val is None:
        message.component_type_raw = component
    else:
        message.component_type = enum_val
    return message


def _timings_to_proto(timings: dict[str, ProfilingItem]) -> dict[str, float]:
    return {key: item.total() for key, item in timings.items()}


def _build_exports(
    doc,
    requested_formats: Optional[set[OutputFormat]],
) -> Optional[docling_serve_types_pb2.DocumentExports]:
    def wants(fmt: OutputFormat) -> bool:
        return requested_formats is None or fmt in requested_formats

    exports = docling_serve_types_pb2.DocumentExports()
    has_any = False

    if wants(OutputFormat.JSON) and doc.json_content is not None:
        exports.json = doc.json_content.model_dump_json()
        has_any = True
    if wants(OutputFormat.MARKDOWN) and doc.md_content is not None:
        exports.md = doc.md_content
        has_any = True
    if wants(OutputFormat.HTML) and doc.html_content is not None:
        exports.html = doc.html_content
        has_any = True
    if wants(OutputFormat.TEXT) and doc.text_content is not None:
        exports.text = doc.text_content
        has_any = True
    if wants(OutputFormat.DOCTAGS) and doc.doctags_content is not None:
        exports.doctags = doc.doctags_content
        has_any = True

    return exports if has_any else None


def export_document_to_proto(
    doc, requested_formats: Optional[set[OutputFormat]] = None
) -> docling_serve_types_pb2.ExportDocumentResponse:
    message = docling_serve_types_pb2.ExportDocumentResponse(filename=doc.filename)
    # doc.json_content is the live Pydantic DoclingDocument object (not a JSON string).
    # It's named "json_content" in docling_jobkit because REST serializes it as JSON.
    # For gRPC, we convert it field-by-field into the native protobuf representation.
    if doc.json_content is not None:
        message.doc.CopyFrom(_docling_document_to_proto(doc.json_content))
    exports = _build_exports(doc, requested_formats)
    if exports is not None:
        message.exports.CopyFrom(exports)
    return message


def document_response_to_proto(
    doc, requested_formats: Optional[set[OutputFormat]] = None
) -> docling_serve_types_pb2.DocumentResponse:
    message = docling_serve_types_pb2.DocumentResponse(filename=doc.filename)
    # See export_document_to_proto for why this field is called json_content.
    if doc.json_content is not None:
        message.doc.CopyFrom(_docling_document_to_proto(doc.json_content))
    exports = _build_exports(doc, requested_formats)
    if exports is not None:
        message.exports.CopyFrom(exports)
    return message


def convert_result_to_proto(
    result,
    processing_time: float,
    requested_formats: Optional[set[OutputFormat]] = None,
) -> docling_serve_types_pb2.ConvertDocumentResponse:
    status_enum, status_raw = _conversion_status_enum_and_raw(result.status)
    response = docling_serve_types_pb2.ConvertDocumentResponse(
        document=document_response_to_proto(result.content, requested_formats),
        errors=[_error_item_to_proto(err) for err in result.errors],
        processing_time=processing_time,
        status=status_enum,
        timings=_timings_to_proto(result.timings),
    )
    if status_raw is not None:
        response.status_raw = status_raw
    return response


def chunk_result_to_proto(
    result,
    processing_time: float,
    requested_formats: Optional[set[OutputFormat]] = None,
) -> docling_serve_types_pb2.ChunkDocumentResponse:
    chunks = []
    for chunk in result.chunks:
        message = docling_serve_types_pb2.Chunk(
            filename=chunk.filename,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            headings=chunk.headings or [],
            captions=chunk.captions or [],
            doc_items=chunk.doc_items or [],
            page_numbers=chunk.page_numbers or [],
            metadata={k: str(v) for k, v in (chunk.metadata or {}).items()},
        )
        if chunk.raw_text is not None:
            message.raw_text = chunk.raw_text
        if chunk.num_tokens is not None:
            message.num_tokens = chunk.num_tokens
        chunks.append(message)

    documents = []
    for doc in result.documents:
        status_enum, status_raw = _conversion_status_enum_and_raw(doc.status)
        document = docling_serve_types_pb2.Document(
            kind=doc.kind,
            content=export_document_to_proto(doc.content, requested_formats),
            status=status_enum,
            errors=[_error_item_to_proto(err) for err in doc.errors],
        )
        if status_raw is not None:
            document.status_raw = status_raw
        documents.append(document)

    return docling_serve_types_pb2.ChunkDocumentResponse(
        chunks=chunks,
        documents=documents,
        processing_time=processing_time,
    )


def task_status_to_proto(
    task: Task, position: Optional[int]
) -> docling_serve_types_pb2.TaskStatusPollResponse:
    task_meta = None
    if task.processing_meta is not None:
        meta = task.processing_meta
        if hasattr(meta, "model_dump"):
            meta = meta.model_dump()
        task_meta = docling_serve_types_pb2.TaskStatusMetadata(
            num_docs=meta.get("num_docs", 0),
            num_processed=meta.get("num_processed", 0),
            num_succeeded=meta.get("num_succeeded", 0),
            num_failed=meta.get("num_failed", 0),
        )
    task_type = task.task_type
    if hasattr(task_type, "value"):
        task_type = task_type.value
    response = docling_serve_types_pb2.TaskStatusPollResponse(
        task_id=task.task_id,
        task_type=str(task_type) if task_type is not None else "",
        task_status=_task_status_enum(task.task_status),
        task_meta=task_meta,
    )
    if position is not None:
        response.task_position = position
    return response


def _task_status_enum(status: TaskStatus | str) -> int:
    if isinstance(status, str):
        try:
            status = TaskStatus(status)
        except Exception:
            return docling_serve_types_pb2.TaskStatus.TASK_STATUS_UNSPECIFIED
    mapping = {
        TaskStatus.PENDING: docling_serve_types_pb2.TaskStatus.TASK_STATUS_PENDING,
        TaskStatus.STARTED: docling_serve_types_pb2.TaskStatus.TASK_STATUS_STARTED,
        TaskStatus.SUCCESS: docling_serve_types_pb2.TaskStatus.TASK_STATUS_SUCCESS,
        TaskStatus.FAILURE: docling_serve_types_pb2.TaskStatus.TASK_STATUS_FAILURE,
    }
    return mapping.get(
        status, docling_serve_types_pb2.TaskStatus.TASK_STATUS_UNSPECIFIED
    )


def clear_response_to_proto(
    status: str = "ok",
) -> docling_serve_types_pb2.ClearResponse:
    return docling_serve_types_pb2.ClearResponse(status=status)


def with_single_use_cleanup(orchestrator, task_id: str) -> None:
    if not docling_serve_settings.single_use_results:
        return

    import asyncio

    async def _remove_task_impl():
        await asyncio.sleep(docling_serve_settings.result_removal_delay)
        await orchestrator.delete_task(task_id=task_id)

    asyncio.create_task(_remove_task_impl())
