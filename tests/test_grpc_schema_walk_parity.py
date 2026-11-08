"""Schema walk: every ConvertDocumentsOptions and DoclingDocument pydantic field
maps to a proto field, or is named in an explicit documented skip list.

Fail hard on an unlisted gap. Proto-only companions (*_raw, ocr_options oneof)
are listed as expected proto extras, not as failures.
"""

from __future__ import annotations

import logging

import pytest
from docling.datamodel.service.options import ConvertDocumentsOptions
from docling_core.types.doc.document import DoclingDocument

from docling_serve.grpc.gen.ai.docling.serve.v1 import docling_serve_types_pb2 as serve_pb2
from docling_serve.grpc.schema_validator import (
    _PROTO_ONLY_FIELD_NAMES,
    _RAW_FALLBACK_SUFFIXES,
    validate_docling_document_schema,
    validate_serve_types_schema,
)

pytestmark = pytest.mark.unit

# Pydantic fields that intentionally have no proto slot. Keep this short and
# reason every entry. An empty set means full coverage is required.
CONVERT_OPTIONS_DOCUMENTED_SKIP: dict[str, str] = {
    # No pydantic-only gaps today. Add a name here with a reason when a field
    # is intentionally absent from the proto.
}

# Proto field names on ConvertDocumentOptions that enrich the pydantic model
# without a same-named pydantic field. Validated separately for presence.
CONVERT_OPTIONS_PROTO_EXTRAS: dict[str, str] = {
    # oneof arm fields (ocr_options is the oneof name, not a field)
    "ocr_auto": "ocr_options oneof arm",
    "easyocr": "ocr_options oneof arm",
    "tesseract": "ocr_options oneof arm",
    "tesseract_cli": "ocr_options oneof arm",
    "rapidocr": "ocr_options oneof arm",
    "ocrmac": "ocr_options oneof arm",
    "nemotron_ocr": "ocr_options oneof arm",
    "kserve_v2_ocr": "ocr_options oneof arm",
    "hierarchical_chunking": "chunking_options oneof arm",
    "hybrid_chunking": "chunking_options oneof arm",
    "caption_placement": "docling-core MarkdownParams; applied at markdown re-export",
}

OCR_ONEOF_ARMS = (
    "ocr_auto",
    "easyocr",
    "tesseract",
    "tesseract_cli",
    "rapidocr",
    "ocrmac",
    "nemotron_ocr",
    "kserve_v2_ocr",
)

OCR_ENUM_RAW_PAIRS = (
    ("OcrMode", "mode_raw", "OcrOptionsBase"),
    ("RapidOcrBackend", "backend_raw", "RapidOcrOptions"),
    ("RapidOcrModelSize", "model_size_raw", "RapidOcrOptions"),
    ("NemotronOcrMergeLevel", "merge_level_raw", "NemotronOcrOptions"),
    ("KserveV2Transport", "transport_raw", "KserveV2OcrOptions"),
)


def test_serve_and_document_schema_validators_pass(caplog):
    with caplog.at_level(logging.WARNING):
        validate_serve_types_schema()
        validate_docling_document_schema()
    assert "Fields in Pydantic but not in proto" not in caplog.text
    assert "Serve fields in Pydantic but not in proto" not in caplog.text


def test_convert_options_every_pydantic_field_is_on_proto_or_skipped():
    proto_fields = {
        f.name for f in serve_pb2.ConvertDocumentOptions.DESCRIPTOR.fields
    }
    # oneof members appear as fields on the descriptor too
    missing = []
    for name in ConvertDocumentsOptions.model_fields:
        if name in CONVERT_OPTIONS_DOCUMENTED_SKIP:
            continue
        if name in proto_fields:
            continue
        # chunking_options is the pydantic union; wire uses the oneof arms
        if name == "chunking_options":
            assert "hierarchical_chunking" in proto_fields
            assert "hybrid_chunking" in proto_fields
            continue
        missing.append(name)
    assert missing == [], (
        "ConvertDocumentsOptions fields with no proto slot and no skip entry: "
        + ", ".join(missing)
    )


def test_convert_options_documented_skips_still_exist_on_pydantic():
    for name in CONVERT_OPTIONS_DOCUMENTED_SKIP:
        assert name in ConvertDocumentsOptions.model_fields, name
    # Empty skip list is fine; the companion field-coverage test is the gate.
    assert isinstance(CONVERT_OPTIONS_DOCUMENTED_SKIP, dict)


def test_convert_options_proto_extras_are_present_and_listed():
    proto_fields = {
        f.name for f in serve_pb2.ConvertDocumentOptions.DESCRIPTOR.fields
    }
    for name in CONVERT_OPTIONS_PROTO_EXTRAS:
        assert name in proto_fields, name
    # Every OCR arm must be listed as a proto extra
    for arm in OCR_ONEOF_ARMS:
        assert arm in CONVERT_OPTIONS_PROTO_EXTRAS, arm
        assert arm in proto_fields, arm


def test_ocr_oneof_arms_match_descriptor():
    oneof = serve_pb2.ConvertDocumentOptions.DESCRIPTOR.oneofs_by_name["ocr_options"]
    arms = tuple(field.name for field in oneof.fields)
    assert arms == OCR_ONEOF_ARMS


def test_ocr_enums_have_raw_companions_on_their_messages():
    for enum_name, raw_name, message_name in OCR_ENUM_RAW_PAIRS:
        assert enum_name in serve_pb2.DESCRIPTOR.enum_types_by_name, enum_name
        message = serve_pb2.DESCRIPTOR.message_types_by_name[message_name]
        assert raw_name in message.fields_by_name, f"{message_name}.{raw_name}"
        assert raw_name in _RAW_FALLBACK_SUFFIXES, raw_name


def test_ocr_options_listed_as_proto_only_in_validator():
    assert "ocr_options" in _PROTO_ONLY_FIELD_NAMES
    assert "force_full_page_ocr" in _PROTO_ONLY_FIELD_NAMES


def test_docling_document_model_fields_covered_by_schema_validator(caplog):
    """DoclingDocument coverage is the schema_validator's job; pin that it runs
    against the live model and reports no pydantic-only gaps."""
    assert DoclingDocument.model_fields
    with caplog.at_level(logging.WARNING):
        validate_docling_document_schema()
    assert "Fields in Pydantic but not in proto" not in caplog.text


def test_zip_archive_result_filename_optional_on_proto():
    field = serve_pb2.ZipArchiveResult.DESCRIPTOR.fields_by_name["filename"]
    assert field.number == 2
    assert field.has_presence
