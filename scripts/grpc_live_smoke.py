#!/usr/bin/env python3
"""Live gRPC smoke: one PDF and one DOCX through a running docling-serve-grpc.

The server is started by the caller. This client only converts and asserts
protobuf fields on the response document.
"""

from __future__ import annotations

import argparse
import base64
import sys
import zipfile
from pathlib import Path

import grpc

from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2 as serve_pb2,
    docling_serve_pb2_grpc as serve_pb2_grpc,
    docling_serve_types_pb2 as types_pb2,
)


def write_docx(path: Path, paragraph: str) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)


def _convert(stub, filename: str, payload: bytes):
    source = types_pb2.Source(
        file=types_pb2.FileSource(
            base64_string=base64.b64encode(payload).decode(),
            filename=filename,
        )
    )
    options = types_pb2.ConvertDocumentOptions(
        do_ocr=False,
        do_table_structure=False,
    )
    request = serve_pb2.ConvertSourceRequest(
        request=types_pb2.ConvertDocumentRequest(sources=[source], options=options)
    )
    response = stub.ConvertSource(request, timeout=600)
    arm = response.WhichOneof("result")
    if arm == "failure":
        failure = response.failure
        raise SystemExit(
            f"{filename}: failure category={failure.category} "
            f"message={failure.message!r}"
        )
    if arm != "response":
        raise SystemExit(f"{filename}: result arm {arm!r}")
    status = response.response.status
    if status not in (
        types_pb2.CONVERSION_STATUS_SUCCESS,
        types_pb2.CONVERSION_STATUS_PARTIAL_SUCCESS,
    ):
        errors = [item.error_message for item in response.response.errors]
        raise SystemExit(f"{filename}: status={status} errors={errors!r}")
    document = response.response.document.doc
    if document.schema_name != "DoclingDocument":
        raise SystemExit(f"{filename}: schema_name={document.schema_name!r}")
    if document.version != "1.11.0":
        raise SystemExit(f"{filename}: version={document.version!r}")
    if not document.name:
        raise SystemExit(f"{filename}: empty document name")
    texts = []
    for item in document.texts:
        case = item.WhichOneof("item")
        body = getattr(item, case) if case else None
        base = getattr(body, "base", None) if body is not None else None
        text = getattr(base, "text", "") if base is not None else ""
        if text:
            texts.append(text)
    print(
        f"{filename}: schema_name={document.schema_name} version={document.version} "
        f"name={document.name!r} pages={len(document.pages)} texts={len(document.texts)} "
        f"text_sample={texts[:3]!r}"
    )
    return texts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="127.0.0.1:50051")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument(
        "--expect-docx-text",
        default="Docling gRPC smoke paragraph.",
    )
    args = parser.parse_args()

    options = [
        ("grpc.max_send_message_length", 64 * 1024 * 1024),
        ("grpc.max_receive_message_length", 64 * 1024 * 1024),
    ]
    channel = grpc.insecure_channel(args.target, options=options)
    grpc.channel_ready_future(channel).result(timeout=120)
    stub = serve_pb2_grpc.DoclingServeServiceStub(channel)

    health = stub.Health(serve_pb2.HealthRequest(), timeout=30)
    print(f"health: status={health.status!r} version={health.version!r}")

    pdf_texts = _convert(stub, args.pdf.name, args.pdf.read_bytes())
    if not pdf_texts:
        raise SystemExit("pdf: no text items")
    docx_texts = _convert(stub, args.docx.name, args.docx.read_bytes())
    if args.expect_docx_text not in " ".join(docx_texts):
        raise SystemExit(f"docx text missing {args.expect_docx_text!r}: {docx_texts!r}")
    print("smoke ok")


if __name__ == "__main__":
    try:
        main()
    except grpc.RpcError as exc:
        print(f"rpc error: {exc.code()} {exc.details()}", file=sys.stderr)
        raise SystemExit(1) from exc
