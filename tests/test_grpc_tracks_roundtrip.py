"""Schema 1.12 tracks round-trip on the gRPC convert response.

The document bytes are core's typed protos (TrackItem, MediaRef,
MediaMimetype, DocItemLabel.TRACK). Serve does not re-encode them.
"""

from __future__ import annotations

import base64

import pytest

from docling.datamodel.base_models import ConversionStatus
from docling_core.proto import proto_to_docling_document
from docling_core.proto.gen.ai.docling.core.v1 import docling_document_pb2
from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    MediaRef,
    TrackSource,
)
from docling_jobkit.datamodel.result import (
    DoclingTaskResult,
    ExportDocumentResponse,
    ExportResult,
)

from docling_serve.grpc.gen.ai.docling.serve.v1 import docling_serve_pb2
from tests.test_grpc_service_fake import FakeOrchestrator, _server_with

pytestmark = pytest.mark.unit


def _track_document() -> DoclingDocument:
    document = DoclingDocument(name="town-hall")
    track = document.add_track(
        audio=MediaRef(mimetype="audio/mpeg", uri="https://example.invalid/talk.mp3")
    )
    document.add_text(
        label=DocItemLabel.TEXT,
        text="hello track",
        parent=track,
        source=TrackSource(start_time=0.0, end_time=1.5, voice="narrator"),
    )
    return document


class _TrackOrchestrator(FakeOrchestrator):
    async def enqueue(self, **kwargs):
        task = await super().enqueue(**kwargs)
        export = ExportResult(
            content=ExportDocumentResponse(
                filename="town-hall.md",
                md_content="hello track",
                json_content=_track_document(),
            ),
            status=ConversionStatus.SUCCESS,
        )
        self.results[task.task_id] = DoclingTaskResult(
            result=export,
            processing_time=0.2,
            num_converted=1,
            num_succeeded=1,
            num_failed=0,
        )
        return task


def _file_request() -> docling_serve_pb2.ConvertSourceRequest:
    payload = base64.b64encode(b"dummy").decode("utf-8")
    from docling_serve.grpc.gen.ai.docling.serve.v1 import docling_serve_types_pb2

    return docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=payload,
                        filename="talk.mp3",
                    )
                )
            ]
        )
    )


@pytest.mark.asyncio
async def test_convert_source_tracks_round_trip_on_typed_document():
    tracks_field = docling_document_pb2.DoclingDocument.DESCRIPTOR.fields_by_name[
        "tracks"
    ]
    assert tracks_field.number == 29
    assert docling_document_pb2.DocItemLabel.DOC_ITEM_LABEL_TRACK == 31

    async with _server_with(orchestrator=_TrackOrchestrator()) as stub:
        response = await stub.ConvertSource(_file_request())

    assert response.WhichOneof("result") == "response"
    document = response.response.document.doc
    assert document.version == "1.12.0"
    assert len(document.tracks) == 1
    track = document.tracks[0]
    assert track.label == docling_document_pb2.DocItemLabel.DOC_ITEM_LABEL_TRACK
    assert not track.HasField("label_raw")
    assert track.audio.mimetype == docling_document_pb2.MediaMimetype.MEDIA_MIMETYPE_MP3
    assert track.audio.WhichOneof("uri") == "url"
    assert track.audio.url == "https://example.invalid/talk.mp3"
    assert not track.HasField("video")

    restored = proto_to_docling_document(document)
    assert restored.name == "town-hall"
    assert restored.version == "1.12.0"
    assert len(restored.tracks) == 1
    assert restored.tracks[0].label is DocItemLabel.TRACK
    assert restored.tracks[0].audio is not None
    assert restored.tracks[0].audio.mimetype == "audio/mpeg"
    assert str(restored.tracks[0].audio.uri) == "https://example.invalid/talk.mp3"
    assert len(restored.texts) == 1
    assert restored.texts[0].text == "hello track"
    assert len(restored.texts[0].source) == 1
    source = restored.texts[0].source[0]
    assert isinstance(source, TrackSource)
    assert source.start_time == pytest.approx(0.0)
    assert source.end_time == pytest.approx(1.5)
    assert source.voice == "narrator"
