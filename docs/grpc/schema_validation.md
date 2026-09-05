# gRPC Schema Validation Matrix

This document defines how to validate the Docling Pydantic schema against protobuf descriptors at startup. For an overview of gRPC support, see [README.md](README.md). The goal is to prevent data loss and hard-fail on breaking type mismatches, while tolerating missing fields with warnings.

## 1) Core Rules

- **Type mismatch**: fail hard.
- **Missing field**: warn only.
- **Known coercions**: allowed explicitly via an allowlist.

The validator should compare **Pydantic model fields** against **protobuf descriptors**. JSON exports must use the canonical Pydantic serializer and must not be derived from protobuf.

---

## 2) Cardinality Rules

### Proto -> Pydantic

| Proto Field | Expected Pydantic |
|------------|-------------------|
| singular (non-repeated) | `T` or `Optional[T]` |
| `optional` (proto3 presence) | `Optional[T]` |
| `repeated T` | `List[T]` |
| `map<K, V>` | `Dict[K, V]` |
| `oneof {A,B}` | `Union[A,B]` or discriminated union |

**Hard fail** if:
- proto `repeated` ↔ Pydantic not list-like
- proto `map` ↔ Pydantic not dict-like
- proto `oneof` ↔ Pydantic not union-like

---

## 3) Pydantic Canonical Type Mapping

Normalize Pydantic types into canonical forms before comparison:

| Pydantic Type | Canonical |
|-------------|-----------|
| `str` | `string` |
| `int` | `int` |
| `float` | `float` |
| `bool` | `bool` |
| `bytes` | `bytes` |
| `Enum` | `enum` |
| `BaseModel` subclass | `message:<ModelName>` |
| `List[T]` | `list<T>` |
| `Dict[K,V]` | `map<K,V>` |
| `Optional[T]` | `optional<T>` |
| `Union[A,B]` | `union<A,B>` |
| `Literal["x"]` | treat as `string` with constraint |

**Notes**
- `Annotated[...]`: strip and use inner type.
- `Tuple` types map to dedicated proto messages via `_TUPLE_MESSAGE_EQUIVALENCES`:
  - `Tuple[int,int]` → `message:IntSpan` (charspan, FineRef.range)
  - `Tuple[float,float]` → `message:FloatPair` (chart coordinates, scatter points)
  - `Tuple[str,int]` → `message:StringIntPair` (stacked bar chart segments)
- Discriminated unions: treat as `union` with discriminator.

---

## 4) Proto Canonical Type Mapping

| Proto FieldDescriptor | Canonical |
|----------------------|-----------|
| TYPE_STRING | `string` |
| TYPE_BOOL | `bool` |
| TYPE_BYTES | `bytes` |
| TYPE_DOUBLE / TYPE_FLOAT | `float` |
| TYPE_INT32 / SINT32 / SFIXED32 / FIXED32 / UINT32 | `int32` |
| TYPE_INT64 / SINT64 / SFIXED64 / FIXED64 / UINT64 | `int64` |
| TYPE_ENUM | `enum:<EnumName>` |
| TYPE_MESSAGE | `message:<MessageName>` |

**Cardinality**
- `label == LABEL_REPEATED` → `list<T>` unless `map_entry` → `map<K,V>`
- `has_presence == True` → `optional<T>`

---

## 5) Type Compatibility Matrix

### Primitive Types

| Pydantic | Proto | Result |
|---------|-------|--------|
| `string` | `string` | OK |
| `int` | any int32/int64 | OK (subject to allowlist) |
| `float` | `float` | OK |
| `bool` | `bool` | OK |
| `bytes` | `bytes` | OK |

### Messages

| Pydantic | Proto | Result |
|---------|-------|--------|
| `message:Foo` | `message:Foo` | OK |
| `message:Foo` | `message:Bar` | FAIL |

### Enums

| Pydantic | Proto | Result |
|---------|-------|--------|
| `enum:Foo` | `enum:Foo` | OK |
| `enum:Foo` | `enum:Bar` | FAIL |
| `enum:Foo` | `string` | FAIL unless allowlisted |

### Lists / Maps

| Pydantic | Proto | Result |
|---------|-------|--------|
| `list<T>` | repeated `T` | OK |
| `map<K,V>` | map `K,V` | OK |
| `tuple<int,int>` | `message:IntSpan` | OK (charspan, range) |
| `tuple<float,float>` | `message:FloatPair` | OK (chart coords) |
| `tuple<string,int>` | `message:StringIntPair` | OK (stacked bar) |

---

## 6) Known / Allowed Coercions (Allowlist)

The core `DoclingDocument` contract has **no** coercions. Every entry in
`ALLOWED_COERCIONS` belongs to the serve request/response surface and is
justified inline in `schema_validator.py`. Keys are either a bare field path,
a `**.field` suffix pattern, or a message-scoped `<ProtoMessage>.<field>`
key (matched against the validation context, e.g.
`TaskStatusPollResponse.task_status`).

Current serve-side coercions:

| Path | Pydantic | Proto | Why |
|------|----------|-------|-----|
| `ocr_engine` | `str` | `OcrEngine` enum (+ presets) | REST keeps the engine id open; gRPC closes it with a raw fallback. |
| `headers` | `dict[str, Any]` | `map<string, string>` | HTTP headers are strings on the wire. |
| `**.params`, `**.generation_config`, `**.extra_generation_config`, `**.extra_config`, `*_custom_config` (untyped ones) | `dict[str, Any]` | `map<string, ScalarValue>` | Open scalar bags; nesting is rejected by construction. |
| typed `*_custom_config` | `Union[Model, dict]` | the `Model` message | gRPC exposes only the typed arm. |
| `**.timings` | `dict[str, ProfilingItem]` | `map<string, double>` | Carries `ProfilingItem.total()`; full profile is a deferred wire change. |
| `**.artifact_type` | `Literal[...]` | `ArtifactType` enum | Closed enum + `artifact_type_raw`. |
| `**.url_expires_at` | `datetime | None` | `optional string` | ISO-8601. |
| `**.metadata` (Chunk) | `dict | None` | `map<string, ScalarValue>` | Flattened dotted keys; `uint_value` for `binary_hash`. |
| `TaskStatusPollResponse.task_status` | `ConversionStatus` | `TaskStatus` | Upstream types the REST field with the wider enum; identical strings for the four task states. |
| `ProgressTaskCompleted.task_status` | `Literal["success","failure"]` | `TaskStatus` | Closed enum. |

Sub-fields beneath an allowlisted path are not re-reported: the two sides
represent that subtree differently by definition.

### Structural Equivalences (not coercions)

These are type-level matches handled by `_TUPLE_MESSAGE_EQUIVALENCES`,
`_ONEOF_WRAPPER_MESSAGES` and `_MESSAGE_NAME_EQUIVALENCES` — they do NOT go
through the allowlist:

- `Tuple[int, int]` ↔ `message:IntSpan` (charspan, range)
- `Tuple[float, float]` ↔ `message:FloatPair` (chart coordinates)
- `Tuple[str, int]` ↔ `message:StringIntPair` (stacked bar values)
- `Union[str, Path]` ↔ `string` (Path is string-serializable)
- Discriminated unions ↔ oneof wrapper messages (see §13.6). On the serve
  side `Source` / `Target` wrap the connector request models, so a Pydantic
  `Union[FileSourceRequest, ...]` is compatible with `message:Source`.
- Pydantic model name ↔ proto message name where the wire name differs:
  `ConvertDocumentsOptions`→`ConvertDocumentOptions`,
  `ExportDocumentResponse`→`DocumentResponse`, `DocumentResultItem`→`Document`,
  `ChunkedDocumentResultItem`→`Chunk`, `TaskProcessingMeta`→`TaskStatusMetadata`.
- `_NESTED_LEAF_MODELS` (`ConvertDocumentsOptions`, `ExportDocumentResponse`)
  are validated as their own top-level pair and treated as leaves when they
  appear nested, so the request envelopes don't re-walk them.
  `ExportDocumentResponse` is additionally a deliberate structural divergence:
  REST inlines serialized strings (`md_content`, `json_content`, …) while gRPC
  carries a typed `DoclingDocument` plus `DocumentExports`.

---

## 7) Oneof / Union Rules

Proto `oneof` must map to a Pydantic union.

Example:
- Proto `BaseTextItem` (oneof title/section_header/...) 
  ↔ Pydantic `Union[TitleItem, SectionHeaderItem, ...]`

**Fail** if:
- oneof maps to a single type
- Pydantic uses an untyped dict or Any

---

## 8) Optional vs Required

Proto3 does not enforce required fields, so strictness is relaxed.

- Pydantic required but proto optional: **warn only**
- Proto required (proto2) but Pydantic optional: **warn only**

---

## 9) Missing Field Policy

- Field exists in Pydantic but not proto → **WARN**
- Field exists in proto but not Pydantic → **WARN**
- Only **type mismatch** → **FAIL**

---

## 10) Suggested Validator Outputs

- **Missing fields**: list + warning
- **Type mismatches**: list + fail
- **Allowed coercions**: list + info

---

## 11) Descriptor API Quick Reference

- Proto descriptor: `DoclingDocument.DESCRIPTOR`
- Field access: `.fields_by_name['field']`
- Map fields: `field.message_type.GetOptions().map_entry == True`
- Oneof: `descriptor.oneofs_by_name['name']`
- Optional (proto3 presence): `field.has_presence == True`

---

## 12) Notes on JSON Exports

- JSON export must always use the canonical Pydantic serializer.
- JSON must **not** be derived from protobuf conversion.
- Protobuf conversion is separate and should never drive JSON output.

---

## 13) Suppression Rulesets

The validator suppresses certain proto-only or Pydantic-only paths that arise
from intentional structural divergences between the two schemas.  Every
suppression must be explicitly declared in one of the rulesets below.  When
either schema changes, the validator will surface any new path that does not
fall into a known ruleset, forcing a conscious decision.

### 13.1) Field Name Aliases (`_FIELD_NAME_ALIASES`)

Pydantic's `RefItem` and `FineRef` use `cref` (JSON alias for `$ref`).
The proto field is named `ref`.  These carry the same data; the validator
resolves the alias before comparing types.

| Pydantic field | Proto field | Reason |
|---------------|------------|--------|
| `cref`        | `ref`      | JSON `$ref` alias |

### 13.2) Custom Fields

Pydantic models expose dynamic extension data through the `get_custom_part()`
method, not as a declared `model_fields` entry.  Proto uses
`map<string, google.protobuf.Value> custom_fields` on each message.  All
paths containing `.custom_fields` are suppressed because the Pydantic side
has no corresponding model field to compare against.

### 13.3) Proto-Only Structural Prefixes (`_PROTO_ONLY_PREFIXES`)

Some proto messages include fields that have no direct Pydantic counterpart
because the converter builds them from different source structures.

| Proto prefix | Why it exists | Converter behaviour |
|-------------|--------------|-------------------|
| `tables.data.grid` | `repeated TableRow grid` — row-major accessor | Converter builds grid rows from `table_cells` |
| `pictures.meta.tabular_chart.chart_data.grid` | Same pattern inside chart metadata | Same as above |
| `chart_data.grid` | Same path during oneof wrapper member validation | Same as above |

All sub-paths under these prefixes are suppressed.

### 13.4) Enum Fallback Fields (`_RAW_FALLBACK_SUFFIXES`)

When a proto enum field encounters an unrecognised value at runtime, the
converter stores the raw string in a companion `*_raw` field.  These fields
exist only in proto and have no Pydantic counterpart by design.

| Suffix | Backing enum field | Purpose |
|--------|-------------------|---------|
| `coord_origin_raw` | `CoordOrigin` | Forward-compat for unknown coordinate origins |
| `code_language_raw` | `CodeLanguageLabel` | Forward-compat for unknown code languages on `CodeItem` |
| `language_raw` | `CodeLanguageLabel` | Forward-compat on `CodeMetaField.language` |
| `code_raw` | `HumanLanguageLabel` | Forward-compat on `LanguageMetaField.code` |
| `label_raw` | `DocItemLabel` | Forward-compat for unknown document labels |
| `status_raw` | `ConversionStatus` | Serve response items / progress docs |
| `category_raw`, `phase_raw` | `FailureCategory`, `FailurePhase` | `PublicFailureInfo`, `ErrorItem.category` |
| `mean_grade_raw`, `low_grade_raw` | `QualityGrade` | `ConfidenceScores` |
| `artifact_type_raw` | `ArtifactType` | `ArtifactRef` |
| `task_type_raw` | `TaskType` | `TaskStatusPollResponse` |
| `component_type_raw` | `DoclingComponentType` | `ErrorItem` |
| `document_type_raw` | `InputFormat` | `DocumentCompletedItem` |

### 13.5) Base Field Wrappers (`_BASE_FIELD_WRAPPERS`)

Proto text-item variants (`TitleItem`, `SectionHeaderItem`, …) contain a
`base` sub-message (`TextItemBase`) that holds common fields.  Pydantic uses
class inheritance instead.  The validator flattens through the `base` field
so paths align: proto `texts.title.base.text` is compared as `texts.text`.

### 13.6) Oneof Wrapper Messages (`_ONEOF_WRAPPER_MESSAGES`)

Pydantic uses discriminated unions (e.g., `Union[TitleItem, SectionHeaderItem, ...]`).
Proto models these as a message containing a `oneof` with one field per variant
(e.g., `BaseTextItem`, `PictureAnnotation`, `TableAnnotation`, `SourceType`).
The validator skips recursive descent into these wrapper messages at the
document level and instead validates each variant independently against its
concrete proto message.

### 13.7) Leaf Messages (`_PROTO_LEAF_MESSAGES`)

Certain proto messages are treated as opaque leaf nodes — no recursive descent:

- **google.protobuf well-known types** (`Struct`, `Value`, `ListValue`) —
  model dynamic JSON-like data.  Pydantic uses `Dict[str, Any]`.
- **Tuple-equivalent messages** (`IntSpan`, `FloatPair`, `StringIntPair`) —
  matched structurally via `_TUPLE_MESSAGE_EQUIVALENCES`.
- **`ScalarValue`** — closed scalar oneof used for `dict[str, Any]` bags.
  Map values of this type are not descended either.
- **`ConvertDocumentOptions`, `DocumentResponse` / `ExportDocumentResponse`**
  — validated as their own top-level pair (see §6).

### 13.8) Serve validation pairs (`validate_serve_types_schema`)

Beyond the `DoclingDocument`, the startup validator compares every serve
Pydantic model that has a wire counterpart, using the proto message name as
the context so discriminator suppressions and scoped coercions resolve:

- Options and connectors: `ConvertDocumentsOptions`, every `*SourceRequest`
  / `*Target` arm (including `GenericSource` / `GenericTarget`).
- Request envelopes: `ConvertSourcesRequest`, `BatchConvertSourcesRequest`,
  `CallbackSpec`.
- Responses: `ErrorItem`, `ConfidenceScores`, `PublicFailureInfo`,
  `ArtifactRef`, `DocumentResultItem`, `DocumentArtifactItem`,
  `ConvertDocumentResponse`, `ChunkedDocumentResultItem`,
  `ChunkDocumentResponse`, `ZipArchiveResult`,
  `PresignedUrlConvertDocumentResponse` (`RemoteTargetResult`),
  `PresignedUrlConvertResponse` (`PresignedArtifactResult`),
  `TaskFailureResult`, `TaskProcessingMeta`, `TaskStatusResponse`.
- Progress callbacks: `ProgressSetNumDocs`, `ProcessedDocsItem`,
  `ProgressUpdateProcessed`, `DocumentCompletedItem`,
  `ProgressDocumentCompleted`, `ProgressTaskCompleted`.

Pydantic `kind` discriminators on result / progress variants are absorbed by
the parent oneof tag (`_PYDANTIC_ONLY_DISCRIMINATORS`). The only accepted
proto-only fields are the `*_raw` fallbacks and `Generic{Source,Target}.attributes`:
those models declare `extra="allow"`, so the validator treats a top-level
`map<string, ScalarValue>` on the proto side as the wire form of the extras
(`_SCALAR_EXTRAS_MAP`) and reports it as an allowed coercion rather than a
proto-only field. `test_serve_types_no_pydantic_fields_missing_on_proto`
enforces this.

---

## 14) Adding New Fields — Checklist

When adding a new field to either the Pydantic model or the proto definition:

1. Add the field to both schemas (Pydantic model AND proto).
2. Add the converter mapping in `docling_document_converter.py`.
3. Run the validator: `uv run python -c "from docling_serve.grpc.schema_validator import validate_docling_document_schema; validate_docling_document_schema()"`.
   - The validator runs automatically at gRPC server startup.
4. If the validator warns about a new missing field:
   - **If intentional** (structural divergence): add it to the appropriate suppression ruleset above and document why.
   - **If unintentional**: fix the schema or converter.
5. If the validator fails with a type mismatch:
   - **If the coercion is safe**: add it to `ALLOWED_COERCIONS` and document why.
   - **If not**: fix the type to match.
6. Add or update converter tests. Run `test_docling_document_round_trip_no_field_loss` to verify no silent field loss.
7. Regenerate proto stubs: `uv run python scripts/gen_grpc.py`
