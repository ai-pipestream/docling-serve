import pytest
from docling.datamodel.base_models import InputFormat, OutputFormat
from docling.datamodel.pipeline_options import (
    PdfBackend,
    ProcessingPipeline,
    TableFormerMode,
)
from docling.datamodel.pipeline_options_vlm_model import (
    InferenceFramework,
    ResponseFormat,
    TransformersModelType,
)
from docling.datamodel.vlm_model_specs import VlmModelType
from docling_core.types.doc import ImageRefMode
from docling_core.types.doc.labels import PictureClassificationLabel
from docling.datamodel.service.requests import (
    FileSourceRequest,
    HttpSourceRequest,
    S3SourceRequest,
)
from docling.datamodel.service.targets import (
    AzureBlobTarget,
    GoogleCloudStorageTarget,
    GoogleDriveTarget,
    InBodyTarget,
    PutTarget,
    S3Target,
    ZipTarget,
)
from docling_jobkit.datamodel.chunking import HybridChunkerOptions

from docling_serve.grpc.gen.ai.docling.core.v1 import docling_document_pb2
from docling_serve.grpc.gen.ai.docling.serve.v1 import docling_serve_types_pb2
from docling_serve.grpc.mapping import (
    _map_image_ref_mode,
    _map_inference_framework,
    _map_input_format,
    _map_ocr_engine,
    _map_output_format,
    _map_pdf_backend,
    _map_pipeline,
    _map_picture_classification_labels,
    _map_response_format,
    _map_table_mode,
    _map_transformers_model_type,
    _map_vlm_engine_type,
    _map_vlm_model_type,
    _scalar_map_to_dict,
    _scalar_value_to_python,
    _task_status_enum,
    requested_output_formats,
    to_convert_options,
    to_hybrid_chunk_options,
    to_task_sources,
    to_task_target,
)

pytestmark = pytest.mark.unit


def _scalar_map(**kwargs):
    out = {}
    for key, value in kwargs.items():
        msg = docling_serve_types_pb2.ScalarValue()
        if isinstance(value, bool):
            msg.bool_value = value
        elif isinstance(value, int):
            msg.int_value = value
        elif isinstance(value, float):
            msg.double_value = value
        else:
            msg.string_value = str(value)
        out[key] = msg
    return out


def _minimal_vlm_model_spec(name="spec", repo_id="repo/model"):
    return docling_serve_types_pb2.VlmModelSpec(
        name=name,
        default_repo_id=repo_id,
        prompt="p",
        response_format=docling_serve_types_pb2.RESPONSE_FORMAT_MARKDOWN,
    )


def _minimal_vlm_convert_options(repo_id="repo/model"):
    return docling_serve_types_pb2.VlmConvertOptions(
        engine_options=docling_serve_types_pb2.BaseVlmEngineOptions(
            engine_type=docling_serve_types_pb2.VLM_ENGINE_TYPE_TRANSFORMERS
        ),
        model_spec=_minimal_vlm_model_spec(repo_id=repo_id),
    )


def _minimal_picture_description_custom(url_prompt="describe"):
    return docling_serve_types_pb2.PictureDescriptionVlmEngineOptions(
        engine_options=docling_serve_types_pb2.BaseVlmEngineOptions(
            engine_type=docling_serve_types_pb2.VLM_ENGINE_TYPE_API
        ),
        model_spec=_minimal_vlm_model_spec(name="pd", repo_id="pd/model"),
        prompt=url_prompt,
    )


def _minimal_code_formula_custom(temperature=0.0):
    spec = _minimal_vlm_model_spec(name="cf", repo_id="cf/model")
    spec.temperature = temperature
    return docling_serve_types_pb2.CodeFormulaVlmOptions(
        engine_options=docling_serve_types_pb2.BaseVlmEngineOptions(
            engine_type=docling_serve_types_pb2.VLM_ENGINE_TYPE_TRANSFORMERS
        ),
        model_spec=spec,
    )


def test_enum_mappings():
    assert (
        _map_input_format(docling_serve_types_pb2.INPUT_FORMAT_PDF) == InputFormat.PDF
    )
    assert (
        _map_output_format(docling_serve_types_pb2.OUTPUT_FORMAT_MARKDOWN)
        == OutputFormat.MARKDOWN
    )
    assert (
        _map_image_ref_mode(docling_serve_types_pb2.IMAGE_REF_MODE_REFERENCED)
        == ImageRefMode.REFERENCED
    )
    assert _map_ocr_engine(docling_serve_types_pb2.OCR_ENGINE_TESSEROCR) == "tesserocr"
    assert _map_ocr_engine(docling_serve_types_pb2.OCR_ENGINE_TESSERACT) == "tesseract"
    assert (
        _map_pdf_backend(docling_serve_types_pb2.PDF_BACKEND_DLPARSE_V4)
        == PdfBackend.DLPARSE_V4
    )
    assert (
        _map_table_mode(docling_serve_types_pb2.TABLE_FORMER_MODE_FAST)
        == TableFormerMode.FAST
    )
    assert (
        _map_pipeline(docling_serve_types_pb2.PROCESSING_PIPELINE_VLM)
        == ProcessingPipeline.VLM
    )
    assert (
        _map_vlm_model_type(docling_serve_types_pb2.VLM_MODEL_TYPE_GOT_OCR_2)
        == VlmModelType.GOT_OCR_2
    )
    assert (
        _map_response_format(docling_serve_types_pb2.RESPONSE_FORMAT_PLAINTEXT)
        == ResponseFormat.PLAINTEXT
    )
    assert (
        _map_inference_framework(
            docling_serve_types_pb2.INFERENCE_FRAMEWORK_TRANSFORMERS
        )
        == InferenceFramework.TRANSFORMERS
    )
    assert (
        _map_transformers_model_type(
            docling_serve_types_pb2.TRANSFORMERS_MODEL_TYPE_AUTOMODEL_IMAGETEXTTOTEXT
        )
        == TransformersModelType.AUTOMODEL_IMAGETEXTTOTEXT
    )
    assert (
        _map_input_format(docling_serve_types_pb2.INPUT_FORMAT_LATEX)
        == InputFormat.LATEX
    )
    assert (
        _map_output_format(docling_serve_types_pb2.OUTPUT_FORMAT_YAML)
        == OutputFormat.YAML
    )
    assert (
        _map_output_format(docling_serve_types_pb2.OUTPUT_FORMAT_VTT)
        == OutputFormat.VTT
    )
    assert (
        _map_pdf_backend(docling_serve_types_pb2.PDF_BACKEND_DOCLING_PARSE)
        == PdfBackend.DOCLING_PARSE
    )
    assert (
        _map_pipeline(docling_serve_types_pb2.PROCESSING_PIPELINE_LEGACY)
        == ProcessingPipeline.LEGACY
    )
    assert (
        _map_vlm_model_type(docling_serve_types_pb2.VLM_MODEL_TYPE_GRANITEDOCLING)
        == VlmModelType.GRANITEDOCLING
    )
    assert (
        _map_vlm_model_type(docling_serve_types_pb2.VLM_MODEL_TYPE_GRANITEDOCLING_VLLM)
        == VlmModelType.GRANITEDOCLING_VLLM
    )
    assert (
        _map_vlm_model_type(docling_serve_types_pb2.VLM_MODEL_TYPE_DEEPSEEKOCR_OLLAMA)
        == VlmModelType.DEEPSEEKOCR_OLLAMA
    )
    # New VlmModelType values added upstream after the gRPC PR was opened.
    assert (
        _map_vlm_model_type(docling_serve_types_pb2.VLM_MODEL_TYPE_NANONETS_OCR2)
        == VlmModelType.NANONETS_OCR2
    )
    assert (
        _map_vlm_model_type(docling_serve_types_pb2.VLM_MODEL_TYPE_NANONETS_OCR2_VLLM)
        == VlmModelType.NANONETS_OCR2_VLLM
    )
    assert (
        _map_vlm_model_type(
            docling_serve_types_pb2.VLM_MODEL_TYPE_NANONETS_OCR2_LMSTUDIO
        )
        == VlmModelType.NANONETS_OCR2_LMSTUDIO
    )
    assert (
        _map_vlm_model_type(docling_serve_types_pb2.VLM_MODEL_TYPE_GLMOCR)
        == VlmModelType.GLMOCR
    )
    assert (
        _map_vlm_model_type(docling_serve_types_pb2.VLM_MODEL_TYPE_GLMOCR_VLLM)
        == VlmModelType.GLMOCR_VLLM
    )
    assert (
        _map_vlm_model_type(docling_serve_types_pb2.VLM_MODEL_TYPE_LIGHTONOCR)
        == VlmModelType.LIGHTONOCR
    )
    assert (
        _map_vlm_model_type(docling_serve_types_pb2.VLM_MODEL_TYPE_LIGHTONOCR_VLLM)
        == VlmModelType.LIGHTONOCR_VLLM
    )

    assert _map_input_format(0) is None
    assert _map_output_format(0) is None


def test_vlm_model_type_proto_covers_pydantic():
    """Guard against future drift: every Pydantic VlmModelType value must be reachable
    via _map_vlm_model_type from at least one proto enum tag."""
    reachable: set[VlmModelType] = set()
    for value in docling_serve_types_pb2.VlmModelType.DESCRIPTOR.values:
        if value.number == 0:
            continue
        mapped = _map_vlm_model_type(value.number)
        if mapped is not None:
            reachable.add(mapped)
    missing = set(VlmModelType) - reachable
    assert not missing, (
        f"Pydantic VlmModelType values not reachable from any proto tag: "
        f"{sorted(m.name for m in missing)}. "
        f"Add a proto tag in docling_serve_types.proto and a mapping entry."
    )


def test_output_format_proto_covers_pydantic():
    """Guard against future drift in OutputFormat (proto vs Pydantic)."""
    from docling.datamodel.base_models import OutputFormat as DoclingOutputFormat

    reachable: set[OutputFormat] = set()
    for value in docling_serve_types_pb2.OutputFormat.DESCRIPTOR.values:
        if value.number == 0:
            continue
        mapped = _map_output_format(value.number)
        if mapped is not None:
            reachable.add(mapped)
    pyd = {
        OutputFormat[member.name]
        for member in DoclingOutputFormat
        if member.name in OutputFormat.__members__
    }
    missing = pyd - reachable
    assert not missing, (
        f"OutputFormat values not reachable from any proto tag: "
        f"{sorted(m.name for m in missing)}"
    )


def test_to_task_sources_and_target():
    sources = to_task_sources(
        [
            docling_serve_types_pb2.Source(
                file=docling_serve_types_pb2.FileSource(
                    base64_string="aGVsbG8=",
                    filename="test.pdf",
                )
            ),
            docling_serve_types_pb2.Source(
                http=docling_serve_types_pb2.HttpSource(
                    url="https://example.com/doc.pdf"
                )
            ),
            docling_serve_types_pb2.Source(
                s3=docling_serve_types_pb2.S3Source(
                    endpoint="s3.example.com",
                    access_key="a",
                    secret_key="b",
                    bucket="bucket",
                    key_prefix="prefix",
                    verify_ssl=True,
                )
            ),
        ]
    )

    assert isinstance(sources[0], FileSourceRequest)
    assert isinstance(sources[1], HttpSourceRequest)
    assert isinstance(sources[2], S3SourceRequest)

    assert isinstance(to_task_target(None), InBodyTarget)
    assert isinstance(
        to_task_target(
            docling_serve_types_pb2.Target(zip=docling_serve_types_pb2.ZipTarget())
        ),
        ZipTarget,
    )
    assert isinstance(
        to_task_target(
            docling_serve_types_pb2.Target(
                put=docling_serve_types_pb2.PutTarget(url="https://example.com")
            )
        ),
        PutTarget,
    )
    assert isinstance(
        to_task_target(
            docling_serve_types_pb2.Target(
                s3=docling_serve_types_pb2.S3Target(
                    endpoint="s3.example.com",
                    access_key="a",
                    secret_key="b",
                    bucket="bucket",
                    verify_ssl=True,
                )
            )
        ),
        S3Target,
    )
    presigned = to_task_target(
        docling_serve_types_pb2.Target(
            presigned_url=docling_serve_types_pb2.PreSignedUrlTarget()
        )
    )
    assert presigned.kind == "presigned_url"


def test_conversion_status_enum_and_raw():
    """Recognized statuses set only the enum; unknown values fall back to raw."""
    from docling.datamodel.base_models import ConversionStatus

    from docling_serve.grpc.mapping import _conversion_status_enum_and_raw

    enum_val, raw = _conversion_status_enum_and_raw(ConversionStatus.SUCCESS)
    assert enum_val == docling_serve_types_pb2.CONVERSION_STATUS_SUCCESS
    assert raw is None

    enum_val, raw = _conversion_status_enum_and_raw("partial_success")
    assert enum_val == docling_serve_types_pb2.CONVERSION_STATUS_PARTIAL_SUCCESS
    assert raw is None

    enum_val, raw = _conversion_status_enum_and_raw("some_future_status")
    assert enum_val == docling_serve_types_pb2.CONVERSION_STATUS_UNSPECIFIED
    assert raw == "some_future_status"


def test_error_item_component_type_enum_and_raw():
    """Known component types map to the enum; unknown ones use the raw fallback."""
    from docling.datamodel.base_models import ErrorItem

    from docling_serve.grpc.mapping import _error_item_to_proto

    known = _error_item_to_proto(
        ErrorItem(
            component_type="model",
            module_name="layout",
            error_message="boom",
        )
    )
    assert known.component_type == docling_serve_types_pb2.DOCLING_COMPONENT_TYPE_MODEL
    assert not known.HasField("component_type_raw")
    assert known.error_message == "boom"


def test_conversion_status_proto_covers_pydantic():
    """Guard against drift: every docling ConversionStatus maps to a proto tag."""
    from docling.datamodel.base_models import ConversionStatus

    from docling_serve.grpc.mapping import _conversion_status_enum_and_raw

    unspecified = docling_serve_types_pb2.CONVERSION_STATUS_UNSPECIFIED
    unmapped = []
    for member in ConversionStatus:
        enum_val, raw = _conversion_status_enum_and_raw(member)
        if enum_val == unspecified or raw is not None:
            unmapped.append(member.value)
    assert not unmapped, (
        f"ConversionStatus values falling back to raw (add proto tags): {unmapped}"
    )


def test_component_type_proto_covers_pydantic():
    """Guard against drift: every DoclingComponentType maps to a proto tag."""
    from docling.datamodel.base_models import DoclingComponentType, ErrorItem

    from docling_serve.grpc.mapping import _error_item_to_proto

    unmapped = []
    for member in DoclingComponentType:
        item = _error_item_to_proto(
            ErrorItem(
                component_type=member,
                module_name="m",
                error_message="e",
            )
        )
        if item.HasField("component_type_raw"):
            unmapped.append(member.value)
    assert not unmapped, (
        f"DoclingComponentType values falling back to raw (add proto tags): {unmapped}"
    )


def test_to_task_sources_empty_oneof_raises():
    """A Source with no variant set raises ValueError."""
    with pytest.raises(ValueError, match="no variant set"):
        to_task_sources([docling_serve_types_pb2.Source()])


def test_to_task_sources_mixed_with_empty_oneof_raises():
    """If any Source in the list has no variant, ValueError is raised."""
    with pytest.raises(ValueError, match="index 1"):
        to_task_sources(
            [
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string="aGVsbG8=", filename="a.pdf"
                    )
                ),
                docling_serve_types_pb2.Source(),  # no variant
            ]
        )


def test_to_convert_options_full():
    table_custom = _scalar_map(mode="accurate")
    layout_custom = _scalar_map(labels="title,table")

    options = docling_serve_types_pb2.ConvertDocumentOptions(
        from_formats=[docling_serve_types_pb2.INPUT_FORMAT_PDF],
        to_formats=[docling_serve_types_pb2.OUTPUT_FORMAT_TEXT],
        image_export_mode=docling_serve_types_pb2.IMAGE_REF_MODE_EMBEDDED,
        do_ocr=True,
        force_ocr=False,
        ocr_engine=docling_serve_types_pb2.OCR_ENGINE_EASYOCR,
        ocr_lang=["en"],
        pdf_backend=docling_serve_types_pb2.PDF_BACKEND_PYPDFIUM2,
        table_mode=docling_serve_types_pb2.TABLE_FORMER_MODE_ACCURATE,
        table_cell_matching=True,
        pipeline=docling_serve_types_pb2.PROCESSING_PIPELINE_STANDARD,
        page_range=docling_document_pb2.IntSpan(start=1, end=2),
        document_timeout=12.0,
        abort_on_error=True,
        do_table_structure=True,
        include_images=True,
        images_scale=0.75,
        md_page_break_placeholder="---",
        do_code_enrichment=True,
        do_formula_enrichment=True,
        do_picture_classification=True,
        do_picture_description=True,
        picture_description_area_threshold=0.2,
        picture_description_local=docling_serve_types_pb2.PictureDescriptionLocal(
            repo_id="repo",
            prompt="describe",
        ),
        vlm_pipeline_model_local=docling_serve_types_pb2.VlmModelLocal(
            repo_id="local-model",
            response_format=docling_serve_types_pb2.RESPONSE_FORMAT_DOCTAGS,
            inference_framework=docling_serve_types_pb2.INFERENCE_FRAMEWORK_TRANSFORMERS,
            transformers_model_type=docling_serve_types_pb2.TRANSFORMERS_MODEL_TYPE_AUTOMODEL,
        ),
        do_chart_extraction=True,
        table_structure_custom_config=table_custom,
        layout_custom_config=layout_custom,
    )

    mapped = to_convert_options(options)
    assert mapped.from_formats == [InputFormat.PDF]
    assert mapped.to_formats == [OutputFormat.TEXT]
    assert mapped.image_export_mode == ImageRefMode.EMBEDDED
    assert mapped.do_ocr is True
    assert mapped.force_ocr is False
    assert mapped.ocr_engine == "easyocr"
    assert mapped.ocr_lang == ["en"]
    assert mapped.pdf_backend == PdfBackend.PYPDFIUM2
    assert mapped.table_mode == TableFormerMode.ACCURATE
    assert mapped.table_cell_matching is True
    assert mapped.pipeline == ProcessingPipeline.STANDARD
    assert mapped.page_range == (1, 2)
    assert mapped.document_timeout == 12.0
    assert mapped.abort_on_error is True
    assert mapped.do_table_structure is True
    assert mapped.include_images is True
    assert mapped.images_scale == 0.75
    assert mapped.md_page_break_placeholder == "---"
    assert mapped.do_code_enrichment is True
    assert mapped.do_formula_enrichment is True
    assert mapped.do_picture_classification is True
    assert mapped.do_picture_description is True
    assert mapped.picture_description_area_threshold == 0.2
    data = mapped.model_dump(exclude_none=True)
    assert data["picture_description_local"]["repo_id"] == "repo"
    assert data["picture_description_local"]["prompt"] == "describe"
    assert data["vlm_pipeline_model_local"]["repo_id"] == "local-model"
    assert data["vlm_pipeline_model_local"]["response_format"] == ResponseFormat.DOCTAGS
    assert mapped.do_chart_extraction is True
    assert data["table_structure_custom_config"]["mode"] == "accurate"
    assert data["layout_custom_config"]["labels"] == "title,table"


def test_to_convert_options_new_presets():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        do_chart_extraction=True,
        vlm_pipeline_preset="vlm-default",
        picture_description_preset="pd-default",
        code_formula_preset="cf-default",
    )

    mapped = to_convert_options(options)
    assert mapped.do_chart_extraction is True
    assert mapped.vlm_pipeline_preset == "vlm-default"
    assert mapped.picture_description_preset == "pd-default"
    assert mapped.code_formula_preset == "cf-default"


def test_to_convert_options_new_custom_configs():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        vlm_pipeline_custom_config=_minimal_vlm_convert_options(
            "ibm-granite/granite-vision-3.2-2b"
        ),
        picture_description_custom_config=_minimal_picture_description_custom(),
        code_formula_custom_config=_minimal_code_formula_custom(0.0),
    )

    mapped = to_convert_options(options)
    data = mapped.model_dump(exclude_none=True)
    assert (
        data["vlm_pipeline_custom_config"]["model_spec"]["default_repo_id"]
        == "ibm-granite/granite-vision-3.2-2b"
    )
    assert data["picture_description_custom_config"]["prompt"] == "describe"
    assert data["code_formula_custom_config"]["model_spec"]["temperature"] == 0.0


def test_to_convert_options_new_pipeline_presets():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        ocr_preset="ocr-default",
        table_structure_preset="ts-default",
        layout_preset="layout-default",
        picture_classification_preset="pc-default",
    )

    mapped = to_convert_options(options)
    assert mapped.ocr_preset == "ocr-default"
    assert mapped.table_structure_preset == "ts-default"
    assert mapped.layout_preset == "layout-default"
    assert mapped.picture_classification_preset == "pc-default"


def test_to_convert_options_new_pipeline_custom_configs():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        ocr_custom_config=_scalar_map(lang="eng,deu"),
        picture_classification_custom_config=_scalar_map(threshold=0.5),
    )

    mapped = to_convert_options(options)
    data = mapped.model_dump(exclude_none=True)
    assert data["ocr_custom_config"]["lang"] == "eng,deu"
    assert data["picture_classification_custom_config"]["threshold"] == 0.5


def test_to_convert_options_picture_description_api():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        picture_description_api=docling_serve_types_pb2.PictureDescriptionApi(
            url="https://api.example.com",
            timeout=3.0,
            concurrency=2,
            prompt="describe",
        )
    )

    mapped = to_convert_options(options)
    data = mapped.model_dump(exclude_none=True)
    assert str(data["picture_description_api"]["url"]) == "https://api.example.com/"
    assert data["picture_description_api"]["timeout"] == 3.0
    assert data["picture_description_api"]["concurrency"] == 2
    assert data["picture_description_api"]["prompt"] == "describe"


def test_to_convert_options_new_enum_values():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        from_formats=[
            docling_serve_types_pb2.INPUT_FORMAT_LATEX,
            docling_serve_types_pb2.INPUT_FORMAT_VTT,
            docling_serve_types_pb2.INPUT_FORMAT_XML_XBRL,
        ],
        to_formats=[
            docling_serve_types_pb2.OUTPUT_FORMAT_YAML,
            docling_serve_types_pb2.OUTPUT_FORMAT_VTT,
        ],
        pdf_backend=docling_serve_types_pb2.PDF_BACKEND_DOCLING_PARSE,
        pipeline=docling_serve_types_pb2.PROCESSING_PIPELINE_LEGACY,
        vlm_pipeline_model=docling_serve_types_pb2.VLM_MODEL_TYPE_GRANITEDOCLING,
        ocr_engine=docling_serve_types_pb2.OCR_ENGINE_TESSEROCR,
    )
    mapped = to_convert_options(options)
    assert mapped.from_formats == [
        InputFormat.LATEX,
        InputFormat.VTT,
        InputFormat.XML_XBRL,
    ]
    assert mapped.to_formats == [OutputFormat.YAML, OutputFormat.VTT]
    assert mapped.pdf_backend == PdfBackend.DOCLING_PARSE
    assert mapped.pipeline == ProcessingPipeline.LEGACY
    assert mapped.vlm_pipeline_model == VlmModelType.GRANITEDOCLING
    assert mapped.ocr_engine == "tesserocr"


def test_requested_output_formats_default_and_custom():
    assert requested_output_formats(None) == set()
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        to_formats=[
            docling_serve_types_pb2.OUTPUT_FORMAT_TEXT,
            docling_serve_types_pb2.OUTPUT_FORMAT_MARKDOWN,
        ]
    )
    assert requested_output_formats(options) == {
        OutputFormat.TEXT,
        OutputFormat.MARKDOWN,
    }


def test_to_hybrid_chunk_options():
    options = docling_serve_types_pb2.HybridChunkerOptions(
        use_markdown_tables=True,
        include_raw_text=False,
        max_tokens=256,
        tokenizer="tok",
        merge_peers=True,
        use_markdown_images=True,
        image_placeholder="[img]",
    )

    mapped = to_hybrid_chunk_options(options)
    assert isinstance(mapped, HybridChunkerOptions)
    assert mapped.use_markdown_tables is True
    assert mapped.include_raw_text is False
    assert mapped.max_tokens == 256
    assert mapped.tokenizer == "tok"
    assert mapped.merge_peers is True
    assert mapped.use_markdown_images is True
    assert mapped.image_placeholder == "[img]"


def test_to_convert_options_heading_hierarchy():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        do_pdf_heading_hierarchy=True,
        pdf_heading_hierarchy_options=docling_serve_types_pb2.HeadingHierarchyOptions(
            enabled=True,
            use_bookmarks=True,
            use_numbering=False,
            use_style=True,
            numbering_schemes=["arabic", "alpha_l"],
            max_level=4,
            bookmark_match_threshold=0.9,
            use_font_style=False,
            style_size_tolerance=0.1,
        ),
    )

    mapped = to_convert_options(options)
    assert mapped.do_pdf_heading_hierarchy is True
    heading = mapped.pdf_heading_hierarchy_options
    assert heading.enabled is True
    assert heading.use_bookmarks is True
    assert heading.use_numbering is False
    assert heading.use_style is True
    assert heading.numbering_schemes == ["arabic", "alpha_l"]
    assert heading.max_level == 4
    assert heading.bookmark_match_threshold == 0.9
    # Docling >=2.120 fields; silently dropped on older installed models.
    if "use_font_style" in type(heading).model_fields:
        assert heading.use_font_style is False
    if "style_size_tolerance" in type(heading).model_fields:
        assert heading.style_size_tolerance == 0.1


def test_task_status_enum():
    assert (
        _task_status_enum("success")
        == docling_serve_types_pb2.TaskStatus.TASK_STATUS_SUCCESS
    )
    assert (
        _task_status_enum("unknown")
        == docling_serve_types_pb2.TaskStatus.TASK_STATUS_UNSPECIFIED
    )


def test_enum_mappings_unspecified_returns_none():
    """UNSPECIFIED (0) must map to None for every enum mapper."""
    assert _map_input_format(0) is None
    assert _map_output_format(0) is None
    assert _map_image_ref_mode(0) is None
    assert _map_ocr_engine(0) is None
    assert _map_pdf_backend(0) is None
    assert _map_table_mode(0) is None
    assert _map_pipeline(0) is None
    assert _map_vlm_model_type(0) is None
    assert _map_response_format(0) is None
    assert _map_inference_framework(0) is None
    assert _map_transformers_model_type(0) is None


def test_enum_mappings_bogus_values_return_none():
    """Out-of-range / future enum values must map to None, not crash."""
    bogus = 9999
    assert _map_input_format(bogus) is None
    assert _map_output_format(bogus) is None
    assert _map_image_ref_mode(bogus) is None
    assert _map_ocr_engine(bogus) is None
    assert _map_pdf_backend(bogus) is None
    assert _map_table_mode(bogus) is None
    assert _map_pipeline(bogus) is None
    assert _map_vlm_model_type(bogus) is None
    assert _map_response_format(bogus) is None
    assert _map_inference_framework(bogus) is None
    assert _map_transformers_model_type(bogus) is None


def test_task_status_enum_all_values():
    """Every known TaskStatus string maps to the correct proto enum."""
    assert (
        _task_status_enum("pending")
        == docling_serve_types_pb2.TaskStatus.TASK_STATUS_PENDING
    )
    assert (
        _task_status_enum("started")
        == docling_serve_types_pb2.TaskStatus.TASK_STATUS_STARTED
    )
    assert (
        _task_status_enum("failure")
        == docling_serve_types_pb2.TaskStatus.TASK_STATUS_FAILURE
    )


def test_to_task_sources_cloud_connectors():
    sources = to_task_sources(
        [
            docling_serve_types_pb2.Source(
                azure_blob=docling_serve_types_pb2.AzureBlobSource(
                    account_name="acct",
                    container="in",
                    connection_string="UseDevelopmentStorage=true",
                )
            ),
            docling_serve_types_pb2.Source(
                google_cloud_storage=docling_serve_types_pb2.GoogleCloudStorageSource(
                    bucket="b",
                    project="p",
                )
            ),
            docling_serve_types_pb2.Source(
                google_drive=docling_serve_types_pb2.GoogleDriveSource(
                    path_id="folder",
                    refresh_token="rtok",
                    credentials_path="/tmp/creds.json",
                )
            ),
            docling_serve_types_pb2.Source(
                generic=docling_serve_types_pb2.GenericSource(
                    kind="filenet",
                    attributes=_scalar_map(path="/x"),
                )
            ),
        ]
    )
    from docling.datamodel.service.requests import (
        AzureBlobSourceRequest,
        GenericSourceRequest,
        GoogleCloudStorageSourceRequest,
        GoogleDriveSourceRequest,
    )

    assert isinstance(sources[0], AzureBlobSourceRequest)
    assert isinstance(sources[1], GoogleCloudStorageSourceRequest)
    assert isinstance(sources[2], GoogleDriveSourceRequest)
    assert isinstance(sources[3], GenericSourceRequest)
    assert sources[3].kind == "filenet"


def test_scalar_value_preserves_python_scalar_kinds():
    """Open bags stay scalar-only: string|int|float|bool, never nested JSON."""
    s = docling_serve_types_pb2.ScalarValue(string_value="eng")
    i = docling_serve_types_pb2.ScalarValue(int_value=7)
    d = docling_serve_types_pb2.ScalarValue(double_value=0.25)
    b = docling_serve_types_pb2.ScalarValue(bool_value=True)
    empty = docling_serve_types_pb2.ScalarValue()

    assert _scalar_value_to_python(s) == "eng"
    assert _scalar_value_to_python(i) == 7
    assert isinstance(_scalar_value_to_python(i), int)
    assert _scalar_value_to_python(d) == pytest.approx(0.25)
    assert _scalar_value_to_python(b) is True
    assert _scalar_value_to_python(empty) is None

    decoded = _scalar_map_to_dict(
        {
            "lang": s,
            "batch": i,
            "threshold": d,
            "enabled": b,
            "unset": empty,
        }
    )
    assert decoded == {
        "lang": "eng",
        "batch": 7,
        "threshold": pytest.approx(0.25),
        "enabled": True,
        "unset": None,
    }


def test_ocr_engine_proto_enum_maps_to_upstream_string():
    """Wire vocab is OcrEngine; upstream ConvertDocumentsOptions.ocr_engine is str."""
    cases = [
        (docling_serve_types_pb2.OCR_ENGINE_AUTO, "auto"),
        (docling_serve_types_pb2.OCR_ENGINE_EASYOCR, "easyocr"),
        (docling_serve_types_pb2.OCR_ENGINE_OCRMAC, "ocrmac"),
        (docling_serve_types_pb2.OCR_ENGINE_RAPIDOCR, "rapidocr"),
        (docling_serve_types_pb2.OCR_ENGINE_TESSEROCR, "tesserocr"),
        (docling_serve_types_pb2.OCR_ENGINE_TESSERACT, "tesseract"),
    ]
    for proto_val, expected in cases:
        assert _map_ocr_engine(proto_val) == expected

    assert _map_ocr_engine(docling_serve_types_pb2.OCR_ENGINE_UNSPECIFIED) is None
    mapped = to_convert_options(
        docling_serve_types_pb2.ConvertDocumentOptions(
            ocr_engine=docling_serve_types_pb2.OCR_ENGINE_UNSPECIFIED
        )
    )
    assert mapped.ocr_engine != "unspecified"
    # Default pydantic value when unset / skipped
    assert isinstance(mapped.ocr_engine, str)


def test_picture_classification_labels_are_enums_not_strings():
    labels = _map_picture_classification_labels(
        [
            docling_serve_types_pb2.PICTURE_CLASSIFICATION_LABEL_UNSPECIFIED,
            docling_serve_types_pb2.PICTURE_CLASSIFICATION_LABEL_BAR_CHART,
            docling_serve_types_pb2.PICTURE_CLASSIFICATION_LABEL_TABLE,
            docling_serve_types_pb2.PICTURE_CLASSIFICATION_LABEL_QR_CODE,
            9999,  # unknown proto ordinal is skipped
        ]
    )
    assert labels == [
        PictureClassificationLabel.BAR_CHART,
        PictureClassificationLabel.TABLE,
        PictureClassificationLabel.QR_CODE,
    ]
    assert all(isinstance(x, PictureClassificationLabel) for x in labels)


def test_picture_description_local_classification_fields_typed():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        picture_description_local=docling_serve_types_pb2.PictureDescriptionLocal(
            repo_id="hf/pic",
            prompt="caption",
            generation_config=_scalar_map(max_new_tokens=64, do_sample=False),
            classification_allow=[
                docling_serve_types_pb2.PICTURE_CLASSIFICATION_LABEL_PHOTOGRAPH,
                docling_serve_types_pb2.PICTURE_CLASSIFICATION_LABEL_SCREENSHOT,
            ],
            classification_deny=[
                docling_serve_types_pb2.PICTURE_CLASSIFICATION_LABEL_LOGO,
            ],
            classification_min_confidence=0.7,
        )
    )
    mapped = to_convert_options(options)
    local = mapped.picture_description_local
    assert local is not None
    assert local.repo_id == "hf/pic"
    assert local.generation_config == {"max_new_tokens": 64, "do_sample": False}
    assert local.classification_allow == [
        PictureClassificationLabel.PHOTOGRAPH,
        PictureClassificationLabel.SCREENSHOT,
    ]
    assert local.classification_deny == [PictureClassificationLabel.LOGO]
    assert local.classification_min_confidence == pytest.approx(0.7)


def test_picture_description_api_params_stay_scalar_dict():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        picture_description_api=docling_serve_types_pb2.PictureDescriptionApi(
            url="https://vlm.example/v1",
            headers={"Authorization": "Bearer x"},
            params=_scalar_map(model="gpt", temperature=0.2, n=1, stream=False),
            classification_allow=[
                docling_serve_types_pb2.PICTURE_CLASSIFICATION_LABEL_TABLE,
            ],
        )
    )
    mapped = to_convert_options(options)
    api = mapped.picture_description_api
    assert api is not None
    assert api.params == {
        "model": "gpt",
        "temperature": pytest.approx(0.2),
        "n": 1,
        "stream": False,
    }
    assert api.classification_allow == [PictureClassificationLabel.TABLE]


def test_vlm_pipeline_model_api_typed_message_not_string():
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        vlm_pipeline_model_api=docling_serve_types_pb2.VlmModelApi(
            url="https://api.example/v1/chat",
            headers={"x-key": "k"},
            params=_scalar_map(model="granite", max_tokens=128),
            timeout=12.5,
            concurrency=3,
            prompt="convert",
            scale=2.0,
            response_format=docling_serve_types_pb2.RESPONSE_FORMAT_DOCTAGS,
            temperature=0.1,
        )
    )
    mapped = to_convert_options(options)
    api = mapped.vlm_pipeline_model_api
    assert api is not None
    assert str(api.url).startswith("https://api.example/v1/chat")
    assert api.headers == {"x-key": "k"}
    assert api.params == {"model": "granite", "max_tokens": 128}
    assert api.timeout == pytest.approx(12.5)
    assert api.concurrency == 3
    assert api.response_format == ResponseFormat.DOCTAGS
    assert api.temperature == pytest.approx(0.1)


def test_vlm_engine_type_vocab_covers_upstream():
    from docling.models.inference_engines.vlm.base import VlmEngineType

    cases = [
        (
            docling_serve_types_pb2.VLM_ENGINE_TYPE_TRANSFORMERS,
            VlmEngineType.TRANSFORMERS,
        ),
        (docling_serve_types_pb2.VLM_ENGINE_TYPE_MLX, VlmEngineType.MLX),
        (docling_serve_types_pb2.VLM_ENGINE_TYPE_VLLM, VlmEngineType.VLLM),
        (docling_serve_types_pb2.VLM_ENGINE_TYPE_API, VlmEngineType.API),
        (
            docling_serve_types_pb2.VLM_ENGINE_TYPE_API_OLLAMA,
            VlmEngineType.API_OLLAMA,
        ),
        (
            docling_serve_types_pb2.VLM_ENGINE_TYPE_AUTO_INLINE,
            VlmEngineType.AUTO_INLINE,
        ),
    ]
    for proto_val, expected in cases:
        assert _map_vlm_engine_type(proto_val) == expected
    assert (
        _map_vlm_engine_type(docling_serve_types_pb2.VLM_ENGINE_TYPE_UNSPECIFIED)
        is None
    )


def test_custom_config_scalar_maps_reject_nesting_by_construction():
    """Pure-dict custom configs only accept ScalarValue; types survive mapping."""
    options = docling_serve_types_pb2.ConvertDocumentOptions(
        ocr_custom_config=_scalar_map(
            lang="eng",
            bitmap_area_threshold=0.05,
            force_full_page=True,
            conf=1,
        ),
        table_structure_custom_config=_scalar_map(
            mode="accurate", do_cell_matching=True
        ),
        layout_custom_config=_scalar_map(create_orphan_clusters=False),
        picture_classification_custom_config=_scalar_map(threshold=0.42),
        include_page_images=True,
    )
    mapped = to_convert_options(options)
    assert mapped.ocr_custom_config == {
        "lang": "eng",
        "bitmap_area_threshold": pytest.approx(0.05),
        "force_full_page": True,
        "conf": 1,
    }
    assert mapped.table_structure_custom_config == {
        "mode": "accurate",
        "do_cell_matching": True,
    }
    assert mapped.layout_custom_config == {"create_orphan_clusters": False}
    assert mapped.picture_classification_custom_config == {
        "threshold": pytest.approx(0.42)
    }
    assert mapped.include_page_images is True


def test_generic_source_attributes_are_scalar_map_not_json():
    sources = to_task_sources(
        [
            docling_serve_types_pb2.Source(
                generic=docling_serve_types_pb2.GenericSource(
                    kind="filenet",
                    attributes=_scalar_map(
                        path="/docs",
                        page_limit=10,
                        recursive=True,
                        score=1.5,
                    ),
                )
            )
        ]
    )
    src = sources[0]
    dumped = src.model_dump(exclude_none=True)
    assert dumped["kind"] == "filenet"
    assert dumped["path"] == "/docs"
    assert dumped["page_limit"] == 10
    assert dumped["recursive"] is True
    assert dumped["score"] == pytest.approx(1.5)


def test_to_task_targets_cloud_connectors():
    azure = to_task_target(
        docling_serve_types_pb2.Target(
            azure_blob=docling_serve_types_pb2.AzureBlobTarget(
                account_name="acct",
                container="out",
                connection_string="UseDevelopmentStorage=true",
                blob_prefix="exports/",
                max_num_elements=50,
            )
        )
    )
    assert isinstance(azure, AzureBlobTarget)
    assert azure.blob_prefix == "exports/"
    assert azure.max_num_elements == 50

    gcs = to_task_target(
        docling_serve_types_pb2.Target(
            google_cloud_storage=docling_serve_types_pb2.GoogleCloudStorageTarget(
                bucket="out-bucket",
                key_prefix="k/",
                project="proj",
                max_num_elements=9,
            )
        )
    )
    assert isinstance(gcs, GoogleCloudStorageTarget)
    assert gcs.bucket == "out-bucket"
    assert gcs.max_num_elements == 9

    gdrive = to_task_target(
        docling_serve_types_pb2.Target(
            google_drive=docling_serve_types_pb2.GoogleDriveTarget(
                path_id="folder-1",
                refresh_token="rtok",
                credentials_path="/tmp/creds.json",
            )
        )
    )
    assert isinstance(gdrive, GoogleDriveTarget)
    assert gdrive.path_id == "folder-1"


def test_s3_source_and_target_max_num_elements():
    sources = to_task_sources(
        [
            docling_serve_types_pb2.Source(
                s3=docling_serve_types_pb2.S3Source(
                    endpoint="s3.example.com",
                    access_key="ak",
                    secret_key="sk",
                    bucket="in",
                    key_prefix="pdfs/",
                    max_num_elements=3,
                )
            )
        ]
    )
    assert isinstance(sources[0], S3SourceRequest)
    assert sources[0].max_num_elements == 3

    target = to_task_target(
        docling_serve_types_pb2.Target(
            s3=docling_serve_types_pb2.S3Target(
                endpoint="s3.example.com",
                access_key="ak",
                secret_key="sk",
                bucket="out",
                key_prefix="done/",
                verify_ssl=True,
                max_num_elements=4,
            )
        )
    )
    assert isinstance(target, S3Target)
    assert target.max_num_elements == 4


def test_page_range_intspan_maps_to_tuple():
    mapped = to_convert_options(
        docling_serve_types_pb2.ConvertDocumentOptions(
            page_range=docling_document_pb2.IntSpan(start=2, end=9)
        )
    )
    assert mapped.page_range == (2, 9)
    assert isinstance(mapped.page_range, tuple)
