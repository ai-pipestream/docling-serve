"""Fixture goldens: DoclingDocument protobuf from DocumentConverter must match
the checked-in golden byte-for-byte after a deterministic normalize.

Goldens live under tests/goldens/docling_parity/. Regenerate with
scripts/regen_grpc_parity_goldens.py (optionally --grpc host:port).

Also covers ConvertDocumentOptions page_range and heading options round-trip
on the same path the gRPC server uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from google.protobuf import text_format

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.proto import docling_document_to_proto
from docling_core.proto.gen.ai.docling.core.v1 import docling_document_pb2 as doc_pb2
from docling_core.types.doc.common.constants import CURRENT_VERSION

from docling_serve.grpc.gen.ai.docling.serve.v1 import docling_serve_types_pb2 as pb2
from docling_serve.grpc.mapping import to_convert_options

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "tests" / "goldens" / "docling_parity"
PDF = ROOT / "tests" / "2408.09869v5.pdf"


def _normalize_for_compare(msg: doc_pb2.DoclingDocument) -> doc_pb2.DoclingDocument:
    """Drop volatile fields that change across runs (timings are not on the doc)."""
    out = doc_pb2.DoclingDocument()
    out.CopyFrom(msg)
    # origin.binary_hash is content-stable; keep it. Clear nothing else for now.
    return out


@pytest.mark.skipif(not PDF.is_file(), reason="fixture PDF absent")
def test_regen_script_versions_file_documents_pins():
    versions = GOLDEN_DIR / "VERSIONS.txt"
    if not versions.is_file():
        pytest.skip(
            "goldens not generated yet; run scripts/regen_grpc_parity_goldens.py"
        )
    text = versions.read_text(encoding="utf-8")
    assert "docling-core=" in text
    assert "docling-serve=" in text


@pytest.mark.skipif(not PDF.is_file(), reason="fixture PDF absent")
def test_pdf_fixture_matches_checked_in_docling_document_golden():
    pb_path = GOLDEN_DIR / f"{PDF.stem}.pb"
    if not pb_path.is_file():
        pytest.skip("golden absent; run scripts/regen_grpc_parity_goldens.py")

    pipeline = PdfPipelineOptions()
    pipeline.do_ocr = False
    pipeline.do_table_structure = True
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)}
    )
    result = converter.convert(str(PDF))
    actual = _normalize_for_compare(docling_document_to_proto(result.document))
    expected = doc_pb2.DoclingDocument()
    expected.ParseFromString(pb_path.read_bytes())
    expected = _normalize_for_compare(expected)

    assert actual.version == CURRENT_VERSION
    assert expected.version == CURRENT_VERSION
    assert actual.name == expected.name
    assert len(actual.texts) == len(expected.texts)
    assert len(actual.tables) == len(expected.tables)
    assert len(actual.pictures) == len(expected.pictures)
    assert set(actual.pages.keys()) == set(expected.pages.keys())

    # Field-by-field text content and heading levels
    for i, (a, e) in enumerate(zip(actual.texts, expected.texts)):
        a_case = a.WhichOneof("item")
        e_case = e.WhichOneof("item")
        assert a_case == e_case, f"texts[{i}] variant {a_case} != {e_case}"
        if a_case == "section_header":
            assert a.section_header.level == e.section_header.level
            assert a.section_header.base.text == e.section_header.base.text
        elif a_case == "title":
            assert a.title.base.text == e.title.base.text
        elif a_case == "text":
            assert a.text.base.text == e.text.base.text
        elif a_case == "list_item":
            assert a.list_item.base.text == e.list_item.base.text

    for i, (a, e) in enumerate(zip(actual.tables, expected.tables)):
        assert a.data.num_rows == e.data.num_rows, f"tables[{i}] rows"
        assert a.data.num_cols == e.data.num_cols, f"tables[{i}] cols"
        assert len(a.data.table_cells) == len(e.data.table_cells), f"tables[{i}] cells"

    # Also accept textproto as the human-readable twin of the binary golden
    text_path = GOLDEN_DIR / f"{PDF.stem}.textproto"
    if text_path.is_file():
        from_text = doc_pb2.DoclingDocument()
        text_format.Parse(text_path.read_text(encoding="utf-8"), from_text)
        assert from_text.SerializeToString() == expected.SerializeToString()


def test_page_range_and_heading_options_round_trip():
    from docling_serve.grpc.gen.ai.docling.core.v1 import (
        docling_document_pb2 as core_pb2,
    )

    options = pb2.ConvertDocumentOptions(
        page_range=core_pb2.IntSpan(start=1, end=2),
        do_pdf_heading_hierarchy=True,
        pdf_heading_hierarchy_options=pb2.HeadingHierarchyOptions(
            numbering_schemes=[
                pb2.NUMBERING_SCHEME_PART,
                pb2.NUMBERING_SCHEME_ARABIC,
            ],
        ),
    )
    mapped = to_convert_options(options)
    assert mapped.page_range == (1, 2)
    assert mapped.do_pdf_heading_hierarchy is True
    assert mapped.pdf_heading_hierarchy_options is not None
