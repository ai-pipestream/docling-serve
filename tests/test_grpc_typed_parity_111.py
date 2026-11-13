"""Schema 1.11 and typed serve-surface parity against slim 2.150.0.

Enum completeness is compared to the installed registries. A skip is not a pass.
"""

from __future__ import annotations

import inspect
import re
from typing import get_args

import pytest

from docling.datamodel.base_models import InputFormat, QualityGrade
from docling.datamodel.chart_extraction_options import ChartExtractionVlmEngineOptions
from docling.datamodel.pipeline_options import (
    CodeFormulaVlmOptions,
    DocumentPictureClassifierOptions,
    LayoutObjectDetectionOptions,
    PictureDescriptionVlmEngineOptions,
    VlmConvertOptions,
)
from docling.datamodel.pipeline_options_vlm_model import ResponseFormat
from docling.datamodel.service.responses import ArtifactRef
from docling.models.factories import get_ocr_factory
from docling_core.types.doc.common.constants import CURRENT_VERSION
from docling_core.types.doc.document import DoclingDocument
from docling_jobkit.convert.manager import CHUNKING_PRESETS

from docling_serve.grpc.gen.ai.docling.serve.v1 import docling_serve_types_pb2 as pb
from docling_serve.grpc.mapping import (
    _map_input_format,
    _map_response_format,
    _to_vlm_convert_options,
    _to_vlm_model_spec,
    artifact_ref_to_proto,
    confidence_from_proto,
    to_convert_options,
    validate_target_document_version,
)

_NAMED_VLM_PRESETS = (
    "surya_ocr2_5",
    "minicpm_ocr",
    "unlimited_ocr2",
    "unlimited_ocr2_mlx",
)


def _proto_member(prefix: str, preset_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]", "_", preset_id).upper()
    if token[0].isdigit():
        token = "P_" + token
    return f"{prefix}{token}"


def _enum_names(enum_cls) -> set[str]:
    return {name for name, number in enum_cls.items() if number != 0}


def _assert_registry(enum_cls, prefix: str, preset_ids: list[str] | set[str]) -> None:
    expected = {_proto_member(prefix, preset_id) for preset_id in preset_ids}
    actual = _enum_names(enum_cls)
    assert actual == expected, sorted(actual ^ expected)
    # The name transform must not collapse two ids onto one member.
    assert len(expected) == len(set(preset_ids))


def _table_structure_builtin_ids() -> list[str]:
    from docling_jobkit.convert import manager

    source = inspect.getsource(manager)
    marker = "built_in_presets = "
    start = source.index(marker) + len(marker)
    depth = 0
    end = start
    for index, char in enumerate(source[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    block = source[start:end]
    return re.findall(r'^ +"([^"]+)": \{', block, re.MULTILINE)


def _vlm_options(**overrides):
    options = pb.VlmConvertOptions(
        engine_options=pb.BaseVlmEngineOptions(
            engine_type=pb.VLM_ENGINE_TYPE_TRANSFORMERS
        ),
        model_spec=pb.VlmModelSpec(
            name="spec",
            default_repo_id="org/model",
            prompt="convert",
            response_format=pb.RESPONSE_FORMAT_MARKDOWN,
        ),
    )
    for name, value in overrides.items():
        field = getattr(options, name)
        if hasattr(field, "CopyFrom"):
            field.CopyFrom(value)
        else:
            setattr(options, name, value)
    return options


def test_schema_current_version_is_1_11_and_both_minors_are_accepted():
    assert CURRENT_VERSION == "1.11.0"
    document = DoclingDocument(name="schema-check")
    assert document.version == "1.11.0"
    assert validate_target_document_version("1.11.0") == "1.11.0"
    assert validate_target_document_version("1.10.0") == "1.10.0"
    with pytest.raises(ValueError, match="unsupported"):
        validate_target_document_version("1.4.9")


def test_input_format_proto_matches_pydantic_including_calendar():
    proto_names = _enum_names(pb.InputFormat)
    expected = {f"INPUT_FORMAT_{member.name}" for member in InputFormat}
    assert proto_names == expected
    assert _map_input_format(pb.INPUT_FORMAT_CALENDAR) == InputFormat.CALENDAR


def test_response_format_new_members_round_trip():
    for member, tag in (
        (ResponseFormat.SURYA_HTML, pb.RESPONSE_FORMAT_SURYA_HTML),
        (ResponseFormat.LIGHTONOCR_MARKDOWN, pb.RESPONSE_FORMAT_LIGHTONOCR_MARKDOWN),
        (ResponseFormat.UNLIMITED_OCR2, pb.RESPONSE_FORMAT_UNLIMITED_OCR2),
    ):
        assert _map_response_format(tag) is member
        mapped = _to_vlm_model_spec(
            pb.VlmModelSpec(
                name="spec",
                default_repo_id="org/model",
                prompt="convert",
                response_format=tag,
            )
        )
        assert mapped.response_format is member

    unknown = pb.VlmModelSpec(
        name="spec",
        default_repo_id="org/model",
        prompt="convert",
        response_format_raw=ResponseFormat.HTML.value,
    )
    unknown.response_format = 99
    assert _to_vlm_model_spec(unknown).response_format is ResponseFormat.HTML

    bare = pb.VlmModelSpec(name="spec", default_repo_id="org/model", prompt="convert")
    bare.response_format = 99
    with pytest.raises(ValueError, match="not a known format"):
        _to_vlm_model_spec(bare)


def test_artifact_type_includes_chunks():
    literal = set(get_args(ArtifactRef.model_fields["artifact_type"].annotation))
    from docling_serve.grpc.mapping import _ARTIFACT_TYPE_TO_PROTO

    assert set(_ARTIFACT_TYPE_TO_PROTO) == literal
    ref = ArtifactRef(
        artifact_type="chunks",
        mime_type="application/json",
        uri="https://example.invalid/chunks",
    )
    proto = artifact_ref_to_proto(ref)
    assert proto.artifact_type == pb.ARTIFACT_TYPE_CHUNKS
    assert not proto.HasField("artifact_type_raw")


def test_preset_enums_match_installed_registries():
    _assert_registry(
        pb.VlmPipelinePreset,
        "VLM_PIPELINE_PRESET_",
        VlmConvertOptions.list_preset_ids(),
    )
    for preset_id in _NAMED_VLM_PRESETS:
        assert preset_id in VlmConvertOptions.list_preset_ids()
    _assert_registry(
        pb.PictureDescriptionPreset,
        "PICTURE_DESCRIPTION_PRESET_",
        PictureDescriptionVlmEngineOptions.list_preset_ids(),
    )
    _assert_registry(
        pb.CodeFormulaPreset,
        "CODE_FORMULA_PRESET_",
        CodeFormulaVlmOptions.list_preset_ids(),
    )
    _assert_registry(
        pb.OcrPreset,
        "OCR_PRESET_",
        get_ocr_factory(allow_external_plugins=False).registered_kind,
    )
    _assert_registry(
        pb.TableStructurePreset,
        "TABLE_STRUCTURE_PRESET_",
        _table_structure_builtin_ids(),
    )
    _assert_registry(
        pb.LayoutPreset,
        "LAYOUT_PRESET_",
        LayoutObjectDetectionOptions.list_preset_ids(),
    )
    _assert_registry(
        pb.PictureClassificationPreset,
        "PICTURE_CLASSIFICATION_PRESET_",
        DocumentPictureClassifierOptions.list_preset_ids(),
    )
    _assert_registry(
        pb.ChunkingPreset,
        "CHUNKING_PRESET_",
        list(CHUNKING_PRESETS),
    )
    _assert_registry(
        pb.ChartExtractionPreset,
        "CHART_EXTRACTION_PRESET_",
        ChartExtractionVlmEngineOptions.list_preset_ids(),
    )


def test_preset_enum_and_unknown_raw_round_trip():
    known = to_convert_options(
        pb.ConvertDocumentOptions(
            vlm_pipeline_preset=pb.VLM_PIPELINE_PRESET_SURYA_OCR2_5,
            picture_description_preset=pb.PICTURE_DESCRIPTION_PRESET_SMOLVLM,
            code_formula_preset=pb.CODE_FORMULA_PRESET_CODEFORMULAV2,
            ocr_preset=pb.OCR_PRESET_NEMOTRON_OCR,
            table_structure_preset=pb.TABLE_STRUCTURE_PRESET_TABLEFORMER_V2,
            layout_preset=pb.LAYOUT_PRESET_LAYOUT_HERON_101,
            picture_classification_preset=(
                pb.PICTURE_CLASSIFICATION_PRESET_DOCUMENT_FIGURE_CLASSIFIER_V2
            ),
            chunking_preset=pb.CHUNKING_PRESET_HIERARCHICAL,
            chart_extraction_preset=pb.CHART_EXTRACTION_PRESET_GRANITE_VISION_V4_MLX,
        )
    )
    assert known.vlm_pipeline_preset == "surya_ocr2_5"
    assert known.picture_description_preset == "smolvlm"
    assert known.code_formula_preset == "codeformulav2"
    assert known.ocr_preset == "nemotron-ocr"
    assert known.table_structure_preset == "tableformer_v2"
    assert known.layout_preset == "layout_heron_101"
    assert known.picture_classification_preset == "document_figure_classifier_v2"
    assert known.chunking_preset == "hierarchical"
    assert known.chart_extraction_preset == "granite_vision_v4_mlx"

    for preset_id in ("minicpm_ocr", "unlimited_ocr2", "unlimited_ocr2_mlx"):
        member = getattr(pb, _proto_member("VLM_PIPELINE_PRESET_", preset_id))
        mapped = to_convert_options(
            pb.ConvertDocumentOptions(vlm_pipeline_preset=member)
        )
        assert mapped.vlm_pipeline_preset == preset_id

    unknown = pb.ConvertDocumentOptions()
    unknown.vlm_pipeline_preset = 99
    unknown.vlm_pipeline_preset_raw = "future-preset"
    assert to_convert_options(unknown).vlm_pipeline_preset == "future-preset"

    missing_raw = pb.ConvertDocumentOptions()
    missing_raw.ocr_preset = 99
    with pytest.raises(ValueError, match="unknown"):
        to_convert_options(missing_raw)

    with pytest.raises(ValueError, match="disagree"):
        to_convert_options(
            pb.ConvertDocumentOptions(
                layout_preset=pb.LAYOUT_PRESET_LAYOUT_EGRET_MEDIUM,
                layout_preset_raw="layout_heron_default",
            )
        )

    alias = to_convert_options(pb.ConvertDocumentOptions(ocr_preset_raw="default"))
    assert alias.ocr_preset == "default"


def test_nemotron_parse_options_round_trip():
    mapped = _to_vlm_convert_options(
        _vlm_options(
            nemotron_parse=pb.NemotronParseOptions(
                passes=pb.NEMOTRON_PARSE_PASSES_TRIPLE,
                triple_regions=pb.NEMOTRON_PARSE_TRIPLE_REGIONS_DETECTOR,
                crop_batch_size=4,
            )
        )
    )
    assert mapped.nemotron_parse.passes == "triple"
    assert mapped.nemotron_parse.triple_regions == "detector"
    assert mapped.nemotron_parse.crop_batch_size == 4

    omitted = _to_vlm_convert_options(_vlm_options())
    assert omitted.nemotron_parse.passes == "single"
    assert omitted.nemotron_parse.triple_regions == "union"
    assert omitted.nemotron_parse.crop_batch_size == 8

    raw = pb.NemotronParseOptions()
    raw.passes = 99
    raw.passes_raw = "double"
    mapped_raw = _to_vlm_convert_options(_vlm_options(nemotron_parse=raw))
    assert mapped_raw.nemotron_parse.passes == "double"

    bare = pb.NemotronParseOptions()
    bare.triple_regions = 99
    with pytest.raises(ValueError, match="unknown"):
        _to_vlm_convert_options(_vlm_options(nemotron_parse=bare))


def test_torch_dtype_enum_and_raw():
    from docling_serve.grpc.mapping import _to_engine_model_config

    mapped = _to_engine_model_config(
        pb.EngineModelConfig(torch_dtype=pb.TORCH_DTYPE_BFLOAT16)
    )
    assert mapped.torch_dtype == "bfloat16"

    unknown = pb.EngineModelConfig()
    unknown.torch_dtype = 9
    unknown.torch_dtype_raw = "float64"
    assert _to_engine_model_config(unknown).torch_dtype == "float64"

    bare = pb.EngineModelConfig()
    bare.torch_dtype = 9
    with pytest.raises(ValueError, match="unknown"):
        _to_engine_model_config(bare)


def test_numbering_schemes_enum_and_raw():
    mapped = to_convert_options(
        pb.ConvertDocumentOptions(
            pdf_heading_hierarchy_options=pb.HeadingHierarchyOptions(
                numbering_schemes=[
                    pb.NUMBERING_SCHEME_ARABIC,
                    pb.NUMBERING_SCHEME_ALPHA_L,
                ]
            )
        )
    )
    assert mapped.pdf_heading_hierarchy_options.numbering_schemes == [
        "arabic",
        "alpha_l",
    ]

    raw_only = to_convert_options(
        pb.ConvertDocumentOptions(
            pdf_heading_hierarchy_options=pb.HeadingHierarchyOptions(
                numbering_schemes_raw=["dotted"]
            )
        )
    )
    assert raw_only.pdf_heading_hierarchy_options.numbering_schemes == ["dotted"]

    mixed = pb.HeadingHierarchyOptions()
    mixed.numbering_schemes.append(99)
    mixed.numbering_schemes_raw.append("custom_scheme")
    mapped_mixed = to_convert_options(
        pb.ConvertDocumentOptions(pdf_heading_hierarchy_options=mixed)
    )
    assert mapped_mixed.pdf_heading_hierarchy_options.numbering_schemes == [
        "custom_scheme"
    ]


def test_quality_grade_unknown_tag_preserves_raw():
    known = pb.ConfidenceScores()
    known.mean_grade = 99
    known.mean_grade_raw = QualityGrade.GOOD.value
    assert confidence_from_proto(known).mean_grade is QualityGrade.GOOD

    missing = pb.ConfidenceScores()
    missing.low_grade = 99
    with pytest.raises(ValueError, match="unknown") as missing_exc:
        confidence_from_proto(missing)
    assert "KeyError" not in type(missing_exc.value).__name__

    invalid = pb.ConfidenceScores()
    invalid.mean_grade = 99
    invalid.mean_grade_raw = "not-a-grade"
    with pytest.raises(ValueError, match="not-a-grade"):
        confidence_from_proto(invalid)
