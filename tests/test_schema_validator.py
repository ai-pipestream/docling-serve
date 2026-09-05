"""Tests for the gRPC schema validator.

Covers allowlist matching used by startup validation against core protobuf.
"""

import logging
from unittest.mock import patch

import pytest

from docling_serve.grpc.schema_validator import (
    _is_coercion_allowed,
    _types_compatible,
    validate_docling_document_schema,
    validate_serve_types_schema,
)


def test_validate_passes_on_current_schemas():
    """The validator must pass without exception on the real schemas."""
    validate_docling_document_schema()


def test_validate_serve_types_passes_on_current_schemas():
    """Serve request/option protos must stay aligned with Pydantic models."""
    validate_serve_types_schema()


def test_serve_types_no_pydantic_fields_missing_on_proto(caplog):
    """Every serve Pydantic field (requests, responses, callbacks) is on the wire.

    Proto-only fields are limited to the documented *_raw fallbacks. The
    Generic{Source,Target}.attributes bags are the wire form of Pydantic's
    extra="allow" and are reported as allowed coercions, not divergences.
    """
    with caplog.at_level(logging.INFO):
        validate_serve_types_schema()
    assert "Serve fields in Pydantic but not in proto" not in caplog.text
    assert "Serve fields in proto but not in Pydantic" not in caplog.text
    for message in ("GenericSource", "GenericTarget"):
        assert (
            f"{message}.attributes: extra='allow' -> map<string,message:ScalarValue>"
            in caplog.text
        )


def test_serve_types_covers_response_side_messages():
    """The response/callback messages are part of the validated pair list."""
    import inspect

    from docling_serve.grpc import schema_validator

    source = inspect.getsource(schema_validator.validate_serve_types_schema)
    for proto_name in (
        "ErrorItem",
        "ConfidenceScores",
        "PublicFailureInfo",
        "ArtifactRef",
        "DocumentArtifactItem",
        "ConvertDocumentResponse",
        "ChunkDocumentResponse",
        "ZipArchiveResult",
        "RemoteTargetResult",
        "PresignedArtifactResult",
        "TaskFailureResult",
        "TaskStatusPollResponse",
        "BatchConvertDocumentRequest",
        "CallbackSpec",
        "GenericTarget",
        "ProgressSetNumDocs",
        "ProgressUpdateProcessed",
        "ProgressDocumentCompleted",
        "ProgressTaskCompleted",
    ):
        assert f'"{proto_name}"' in source, proto_name


def test_context_scoped_coercion_matches_qualified_path():
    """Allowlist keys may be scoped to one message via '<Proto>.<field>'."""
    assert _is_coercion_allowed(
        "task_status",
        "enum:ConversionStatus",
        "enum:TaskStatus",
        context="TaskStatusPollResponse.",
    )
    assert not _is_coercion_allowed(
        "task_status",
        "enum:ConversionStatus",
        "enum:TaskStatus",
        context="SomethingElse.",
    )


def test_message_name_equivalences_and_union_wrapper_compat():
    assert _types_compatible("message:DocumentResultItem", "message:Document")
    assert _types_compatible(
        "optional<message:TaskProcessingMeta>", "message:TaskStatusMetadata"
    )
    assert _types_compatible(
        "list<message:ChunkedDocumentResultItem>", "list<message:Chunk>"
    )
    # Discriminated source/target unions collapse onto the oneof wrapper.
    assert _types_compatible(
        "union<message:InBodyTarget,message:ZipTarget>", "message:Target"
    )
    assert not _types_compatible(
        "union<message:InBodyTarget,message:ZipTarget>", "message:FileSource"
    )


def test_no_warnings_on_current_schemas(caplog):
    """Every Pydantic field must be on the proto. Fork extensions may be proto-only."""
    with caplog.at_level(logging.WARNING):
        validate_docling_document_schema()
    assert "Fields in Pydantic but not in proto" not in caplog.text


def test_warns_on_missing_proto_field(caplog):
    """A Pydantic field not present in proto should produce a warning."""
    with (
        patch(
            "docling_serve.grpc.schema_validator._collect_pydantic_fields",
            return_value={"name": "string"},
        ),
        patch(
            "docling_serve.grpc.schema_validator._collect_proto_fields",
            return_value={},
        ),
        patch.dict(
            "docling_serve.grpc.schema_validator._ONEOF_WRAPPER_MESSAGES",
            {},
            clear=True,
        ),
        caplog.at_level(logging.WARNING),
    ):
        validate_docling_document_schema()
    assert "Fields in Pydantic but not in proto" in caplog.text


def test_fails_on_type_mismatch():
    """An incompatible type mismatch (not in allowlist) must raise RuntimeError."""
    with (
        patch(
            "docling_serve.grpc.schema_validator._collect_pydantic_fields",
            return_value={"name": "int"},
        ),
        patch(
            "docling_serve.grpc.schema_validator._collect_proto_fields",
            return_value={"name": "string"},
        ),
        patch.dict(
            "docling_serve.grpc.schema_validator._ONEOF_WRAPPER_MESSAGES",
            {},
            clear=True,
        ),
    ):
        with pytest.raises(RuntimeError, match="type mismatch"):
            validate_docling_document_schema()


def test_allowlist_suppresses_known_coercions(caplog):
    """Explicitly allowlisted coercions must not fail."""
    with (
        patch.dict(
            "docling_serve.grpc.schema_validator.ALLOWED_COERCIONS",
            {"name": ("int", "string")},
            clear=True,
        ),
        patch(
            "docling_serve.grpc.schema_validator._collect_pydantic_fields",
            return_value={"name": "int"},
        ),
        patch(
            "docling_serve.grpc.schema_validator._collect_proto_fields",
            return_value={"name": "string"},
        ),
        patch.dict(
            "docling_serve.grpc.schema_validator._ONEOF_WRAPPER_MESSAGES",
            {},
            clear=True,
        ),
        caplog.at_level(logging.INFO),
    ):
        validate_docling_document_schema()
    assert "Allowed coercions" in caplog.text
    assert "name: int ↔ string" in caplog.text


def test_cardinality_mismatch_fails():
    """Proto repeated ↔ Pydantic non-list must fail."""
    with (
        patch(
            "docling_serve.grpc.schema_validator._collect_pydantic_fields",
            return_value={"items": "string"},
        ),
        patch(
            "docling_serve.grpc.schema_validator._collect_proto_fields",
            return_value={"items": "list<string>"},
        ),
        patch.dict(
            "docling_serve.grpc.schema_validator._ONEOF_WRAPPER_MESSAGES",
            {},
            clear=True,
        ),
    ):
        with pytest.raises(RuntimeError, match="Cardinality mismatch"):
            validate_docling_document_schema()


def test_oneof_union_compatibility():
    """Proto oneof (union) ↔ Pydantic union should be compatible."""
    assert _types_compatible(
        "union<message:TitleItem,message:TextItem>",
        "union<message:TitleItem,message:TextItem>",
    )


class TestTypesCompatible:
    def test_same_type(self):
        assert _types_compatible("string", "string")

    def test_int_int32(self):
        assert _types_compatible("int", "int32")

    def test_int_int64(self):
        assert _types_compatible("int", "int64")

    def test_optional_unwrap(self):
        assert _types_compatible("optional<string>", "string")
        assert _types_compatible("string", "optional<string>")

    def test_message_match(self):
        assert _types_compatible("message:Foo", "message:Foo")

    def test_message_mismatch(self):
        assert not _types_compatible("message:Foo", "message:Bar")

    def test_list_union_vs_message(self):
        assert _types_compatible(
            "list<union<message:A,message:B>>", "list<message:Wrapper>"
        )

    def test_incompatible(self):
        assert not _types_compatible("int", "string")


class TestStructuralEquivalences:
    """Tests for structural type equivalences (not allowlisted, but structurally matched)."""

    def test_tuple_intspan_equivalence(self):
        """tuple<int,int> ↔ message:IntSpan should be compatible."""
        assert _types_compatible("tuple<int,int>", "message:IntSpan")

    def test_optional_tuple_intspan(self):
        """optional<tuple<int,int>> ↔ optional<message:IntSpan> should be compatible."""
        assert _types_compatible(
            "optional<tuple<int,int>>", "optional<message:IntSpan>"
        )

    def test_oneof_wrapper_sourcetype(self):
        """union<message:TrackSource> ↔ message:SourceType (oneof wrapper)."""
        assert _types_compatible("message:TrackSource", "message:SourceType")

    def test_string_path_union_vs_string(self):
        """union<string,Path> ↔ string should be compatible (Path is string-like)."""
        assert _types_compatible("union<string,Path>", "string")

    def test_list_of_oneof_wrapper(self):
        """list<union<message:TrackSource>> ↔ list<message:SourceType> should work."""
        assert _types_compatible(
            "list<union<message:TrackSource>>", "list<message:SourceType>"
        )


class TestCoercionAllowlist:
    def test_exact_path_match(self):
        with patch.dict(
            "docling_serve.grpc.schema_validator.ALLOWED_COERCIONS",
            {"origin.hash": ("int", "string")},
            clear=True,
        ):
            assert _is_coercion_allowed("origin.hash", "int", "string")
            assert not _is_coercion_allowed("foo.origin.hash", "int", "string")

    def test_suffix_wildcard_match(self):
        with patch.dict(
            "docling_serve.grpc.schema_validator.ALLOWED_COERCIONS",
            {"**.hash": ("int", "string")},
            clear=True,
        ):
            assert _is_coercion_allowed("origin.hash", "int", "string")
            assert _is_coercion_allowed("foo.bar.hash", "int", "string")
            assert not _is_coercion_allowed("foo.bar.hash_value", "int", "string")

    def test_map_key_pattern(self):
        with patch.dict(
            "docling_serve.grpc.schema_validator.ALLOWED_COERCIONS",
            {"items": ("map<int,*>", "map<string,*>")},
            clear=True,
        ):
            assert _is_coercion_allowed(
                "items", "map<int,message:Foo>", "map<string,message:Foo>"
            )

    def test_enum_pattern(self):
        with patch.dict(
            "docling_serve.grpc.schema_validator.ALLOWED_COERCIONS",
            {"**.state": ("enum", "string")},
            clear=True,
        ):
            assert _is_coercion_allowed("foo.state", "enum:State", "string")

    def test_not_allowed(self):
        assert not _is_coercion_allowed("foo.bar", "int", "string")
