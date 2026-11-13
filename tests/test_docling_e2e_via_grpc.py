"""Convert PDFs through a running docling-serve gRPC server.

The PDF directory is ``DOCLING_E2E_PDF_DIR``. When that variable is unset,
the test uses the PDFs shipped in this repo's ``tests/`` directory.
``DOCLING_E2E_GRPC_TARGET`` overrides the server address (default
``localhost:50051``).
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import grpc
import pytest

from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2 as serve_pb2,
    docling_serve_pb2_grpc as serve_pb2_grpc,
    docling_serve_types_pb2 as types_pb2,
)

SKIP_E2E_TEST = {"skipped_1page.pdf", "skipped_2pages.pdf"}
_DEFAULT_PDF_DIR = Path(__file__).resolve().parent


def pdf_dir() -> Path:
    raw = os.environ.get("DOCLING_E2E_PDF_DIR")
    if raw:
        return Path(raw)
    return _DEFAULT_PDF_DIR


def grpc_target() -> str:
    return os.environ.get("DOCLING_E2E_GRPC_TARGET", "localhost:50051")


def get_pdf_paths() -> list[Path]:
    root = pdf_dir()
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*.pdf")
        if path.name not in SKIP_E2E_TEST and path.is_file()
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "pdf_path" not in metafunc.fixturenames:
        return
    paths = get_pdf_paths()
    if not paths:
        metafunc.parametrize(
            "pdf_path",
            [
                pytest.param(
                    None,
                    marks=pytest.mark.skip(
                        reason=(f"No PDFs under {pdf_dir()} (set DOCLING_E2E_PDF_DIR)")
                    ),
                )
            ],
        )
        return
    metafunc.parametrize("pdf_path", paths, ids=lambda path: path.name)


@pytest.fixture(scope="module")
def grpc_stub():
    # 2 GB message limits
    options = [
        ("grpc.max_send_message_length", 2 * 1024 * 1024 * 1024 - 1),
        ("grpc.max_receive_message_length", 2 * 1024 * 1024 * 1024 - 1),
    ]
    channel = grpc.insecure_channel(grpc_target(), options=options)
    return serve_pb2_grpc.DoclingServeServiceStub(channel)


def test_convert_pdf_via_grpc(grpc_stub, pdf_path: Path):
    print(f"Testing {pdf_path.name}")

    payload = pdf_path.read_bytes()
    source = types_pb2.Source(
        file=types_pb2.FileSource(
            base64_string=base64.b64encode(payload).decode(),
            filename=pdf_path.name,
        )
    )
    options = types_pb2.ConvertDocumentOptions(do_table_structure=True)
    request = serve_pb2.ConvertSourceRequest(
        request=types_pb2.ConvertDocumentRequest(
            sources=[source],
            options=options,
        )
    )

    response = grpc_stub.ConvertSource(request)
    doc_proto = response.response.document.doc
    assert doc_proto.schema_name == "DoclingDocument"
    assert doc_proto.name
    assert len(doc_proto.pages) >= 1
    assert len(doc_proto.texts) >= 1
    print(f"  Result: {len(doc_proto.texts)} texts, {len(doc_proto.tables)} tables")
