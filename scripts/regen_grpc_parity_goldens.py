#!/usr/bin/env python3
"""Regenerate DoclingDocument protobuf goldens for gRPC parity tests.

Uses the in-process DocumentConverter by default (same mapping path the gRPC
server uses after conversion). Pass --grpc HOST:PORT to go through the live
docling-serve-grpc fork instead.

Records docling / docling-core versions in VERSIONS.txt beside the goldens.
No JSON is written: goldens are binary (.pb) and text-format (.textproto).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from google.protobuf import text_format

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "tests" / "goldens" / "docling_parity"
DEFAULT_FIXTURES = [
    ROOT / "tests" / "2408.09869v5.pdf",
]


def _versions() -> str:
    import docling
    import docling_core
    import importlib.metadata as md

    lines = [
        f"docling={getattr(docling, '__version__', 'unknown')}",
        f"docling-core={md.version('docling-core')}",
        f"docling-serve={md.version('docling-serve')}",
    ]
    try:
        lines.append(f"docling-slim={md.version('docling-slim')}")
    except md.PackageNotFoundError:
        lines.append("docling-slim=absent")
    return "\n".join(lines) + "\n"


def _convert_local(path: Path):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling_core.proto import docling_document_to_proto

    pipeline = PdfPipelineOptions()
    pipeline.do_ocr = False
    pipeline.do_table_structure = True
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline),
        }
    )
    result = converter.convert(str(path))
    return docling_document_to_proto(result.document)


def _convert_grpc(path: Path, target: str):
    import base64

    import grpc
    from docling_serve.grpc.gen.ai.docling.serve.v1 import (
        docling_serve_pb2 as serve_pb2,
    )
    from docling_serve.grpc.gen.ai.docling.serve.v1 import (
        docling_serve_pb2_grpc as serve_pb2_grpc,
    )
    from docling_serve.grpc.gen.ai.docling.serve.v1 import (
        docling_serve_types_pb2 as types_pb2,
    )

    options = [
        ("grpc.max_send_message_length", 2 * 1024 * 1024 * 1024 - 1),
        ("grpc.max_receive_message_length", 2 * 1024 * 1024 * 1024 - 1),
    ]
    channel = grpc.insecure_channel(target, options=options)
    stub = serve_pb2_grpc.DoclingServeServiceStub(channel)
    b64 = base64.b64encode(path.read_bytes()).decode()
    req = serve_pb2.ConvertSourceRequest(
        request=types_pb2.ConvertDocumentRequest(
            sources=[
                types_pb2.Source(
                    file=types_pb2.FileSource(base64_string=b64, filename=path.name)
                )
            ],
            options=types_pb2.ConvertDocumentOptions(
                do_ocr=False,
                do_table_structure=True,
            ),
        )
    )
    resp = stub.ConvertSource(req, timeout=300)
    if not resp.HasField("document") or not resp.document.HasField("doc"):
        raise RuntimeError(f"ConvertSource returned no document for {path}")
    return resp.document.doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grpc",
        metavar="HOST:PORT",
        help="Use live docling-serve-grpc at HOST:PORT instead of DocumentConverter",
    )
    parser.add_argument(
        "fixtures",
        nargs="*",
        type=Path,
        help="Fixture files (default: tests/2408.09869v5.pdf)",
    )
    args = parser.parse_args()
    fixtures = args.fixtures or DEFAULT_FIXTURES
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    (GOLDEN_DIR / "VERSIONS.txt").write_text(_versions(), encoding="utf-8")

    for path in fixtures:
        if not path.is_file():
            print(f"missing fixture: {path}", file=sys.stderr)
            return 2
        print(f"converting {path} ...")
        if args.grpc:
            proto = _convert_grpc(path, args.grpc)
        else:
            proto = _convert_local(path)
        stem = path.stem
        pb_path = GOLDEN_DIR / f"{stem}.pb"
        text_path = GOLDEN_DIR / f"{stem}.textproto"
        pb_path.write_bytes(proto.SerializeToString())
        text_path.write_text(text_format.MessageToString(proto), encoding="utf-8")
        print(f"  wrote {pb_path.name} ({pb_path.stat().st_size} bytes)")
        print(f"  wrote {text_path.name}")
    print("versions:")
    print((GOLDEN_DIR / "VERSIONS.txt").read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
