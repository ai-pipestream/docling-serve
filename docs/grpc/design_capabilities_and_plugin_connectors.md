# Design: typed capabilities RPC and typed plugin connectors

Status: proposal (no implementation yet). Target: `grpc-native-converter` after serve 1.37.0.

Both designs follow the existing contract in `upstream_sync_procedure.md`: Pydantic is the
source of truth, the proto mirrors it 1:1 in proto-native idioms (closed enums, typed
messages, `oneof` for unions), and every field is checked by the startup schema validator.
The only untyped data allowed is a raw-preserving field for values the server cannot type,
and it never replaces a typed field.

## Part 1: `GetCapabilities` RPC (mirrors REST `GET /v1/capabilities`, #714)

### Why

REST clients learn presets, defaults, allowed sources/targets, limits and features from
`/v1/capabilities` (`docling_serve/capabilities.py`, `CapabilitiesResponse`). gRPC clients
cannot. This hides the effect of #721 (`default_code_formula_preset`) and #723 (custom OCR
presets stay selectable) from gRPC clients, and forces them to hard-code preset ids.

### Rules carried over from REST

- Reuse `build_capabilities(settings, policy, versions, manager)`; the servicer maps its
  `CapabilitiesResponse` to proto. No second implementation of the policy logic.
- Same leak rules: custom presets expose only their id; no model repo, engine options,
  endpoint or credential. `versions` only when `show_version_info` is on, and only
  `docling*` keys.
- Same auth as the other RPCs (API key metadata when `api_key` is set).

### Proto (in `docling_serve.proto` / `docling_serve_types.proto`)

```proto
rpc GetCapabilities(GetCapabilitiesRequest) returns (GetCapabilitiesResponse);

message GetCapabilitiesRequest {}

message GetCapabilitiesResponse {
  // Present only when the server shows version info (Pydantic: dict | None).
  optional PackageVersions versions = 1;
  // Pydantic dict[str, StageCapabilities]; keys are a closed set today.
  repeated StageCapabilities stages = 2;
  repeated SourceKind sources = 3;
  repeated string sources_raw = 4;        // kinds with no SourceKind value (plugins)
  TargetCapabilities targets = 5;
  repeated OutputFormat output_formats = 6;
  repeated string output_formats_raw = 7; // forward-compat companion
  repeated ImageRefMode image_export_modes = 8;
  repeated string image_export_modes_raw = 9;
  LimitsCapabilities limits = 10;
  FeatureCapabilities features = 11;
}

message PackageVersions {
  // Pydantic dict[str, str]; keys are package names, so a map is the 1:1 shape.
  map<string, string> packages = 1;
}

enum CapabilityStage {
  CAPABILITY_STAGE_UNSPECIFIED = 0;
  CAPABILITY_STAGE_OCR = 1;
  CAPABILITY_STAGE_LAYOUT = 2;
  CAPABILITY_STAGE_TABLE_STRUCTURE = 3;
  CAPABILITY_STAGE_VLM_PIPELINE = 4;
  CAPABILITY_STAGE_PICTURE_DESCRIPTION = 5;
  CAPABILITY_STAGE_PICTURE_CLASSIFICATION = 6;
  CAPABILITY_STAGE_CODE_FORMULA = 7;
  CAPABILITY_STAGE_CHART_EXTRACTION = 8;
  CAPABILITY_STAGE_CHUNKING = 9;
}

message StageCapabilities {
  CapabilityStage stage = 1;
  string stage_raw = 2;                    // set only when stage is UNSPECIFIED
  string option = 3;                       // request option name, e.g. "ocr_preset"
  optional string custom_config_option = 4; // unset when the admin disallows custom config
  string default = 5;                      // preset id that "default" resolves to
  repeated PresetInfo presets = 6;
}

enum PresetSource {
  PRESET_SOURCE_UNSPECIFIED = 0;
  PRESET_SOURCE_DEFAULT = 1;
  PRESET_SOURCE_DOCLING = 2;
  PRESET_SOURCE_CUSTOM = 3;
}

message PresetInfo {
  string id = 1;
  string name = 2;
  optional string description = 3;
  PresetSource source = 4;   // Pydantic Literal["default","docling","custom"]: closed enum
}

message TargetCapabilities {
  repeated TargetKind allowed = 1;
  repeated string allowed_raw = 2;
  TargetKind default = 3;
  string default_raw = 4;
}

message LimitsCapabilities {
  double max_document_timeout = 1;
  double max_images_scale = 2;
  int32 max_sources_per_request = 3;
  optional int64 max_num_pages = 4;   // Pydantic int | None ("unbounded" is unset)
  optional int64 max_file_size = 5;
}

message FeatureCapabilities {
  bool api_key_required = 1;
  bool artifact_storage = 2;
  optional bool websocket = 3;        // Pydantic default True; REST-specific, see below
  // gRPC-only: the server exposes Watch* streaming RPCs.
  bool grpc_streaming = 4;
}
```

`SourceKind` and `TargetKind` are new closed enums built from the `Literal` `kind` values
already mirrored by the `Source` and `Target` oneofs (`file`, `http`, `s3`, `azure_blob`,
`google_cloud_storage`, `google_drive`; targets also `inbody`, `zip`, `put`,
`presigned_url`). Plugin kinds have no enum value and go to the `*_raw` lists. That is the
only raw data in the message.

### Typing decisions

| Pydantic | Proto | Reason |
| --- | --- | --- |
| `stages: dict[str, StageCapabilities]` | `repeated StageCapabilities` with `CapabilityStage` | keys are a fixed set (`_STAGES`); a closed enum is stricter than a string map |
| `PresetInfo.source: Literal[...]` | `PresetSource` enum | closed set |
| `sources: list[str]`, `targets.allowed: list[str]` | enum plus `_raw` list | built-in kinds are known; plugin kinds are not |
| `output_formats`, `image_export_modes: list[str]` | existing `OutputFormat` / `ImageRefMode` enums plus `_raw` | reuse enums already on the wire |
| `int \| None` limits | `optional int64` | `max_num_pages` / `max_file_size` default to `sys.maxsize`, which overflows `int32` |
| preset ids | `string` | open set (admins register custom ids) |

### Schema validator and tests

- Add `CapabilitiesResponse` to the serve-types walk, with stage keys checked against
  `CapabilityStage` and `_raw` companions allowlisted.
- Drift guards like `test_input_format_proto_covers_pydantic`: every `_STAGES` key maps to a
  `CapabilityStage`; every built-in connector `kind` maps to a `SourceKind` / `TargetKind`.
- Parity test: for a fake settings plus policy, REST `/v1/capabilities` JSON and the gRPC
  response carry the same data, including #721's default preset and #723's custom OCR id.

### Open questions for Kristian

1. `websocket` is a REST feature flag. Mirror it as-is (proposed, for 1:1) or drop it on gRPC?
2. Should `GetCapabilities` be cacheable through a `version_hash` field so clients can skip
   reloads? This would be a gRPC-only extra.

## Part 2: typed config for plugin sources and targets (#660)

### Why

Upstream `GenericSourceRequest` / `GenericTargetRequest` are `kind: str` with
`extra="allow"`. jobkit resolves the `kind` to a plugin's Pydantic config model, a
`BaseModel` with a `Literal` `kind` that the `docling_jobkit` entry-point factory
registers. Today the proto carries `GenericSource { kind, map<string, ScalarValue>
attributes }`, which:

- loses nested objects and lists (a plugin config with a nested credentials block cannot
  be sent),
- has no types: every value is a loose scalar, and the gRPC side only finds errors after
  jobkit validates.

### Proposal: plugins ship a proto message; raw only for unknown plugins

```proto
message GenericSource {
  string kind = 1;
  oneof config {
    // Typed config: a message the plugin registers (see below), packed as Any.
    // type_url must be the registered message for `kind`.
    google.protobuf.Any typed = 3;
    // Raw-preserving fallback for a kind the server has no proto for. Kept as JSON
    // so nested data survives; validated by the plugin's Pydantic model.
    google.protobuf.Struct raw = 4;
  }
  // Deprecated: superseded by `config`. Kept for wire compatibility; rejected when
  // `config` is set.
  map<string, ScalarValue> attributes = 2 [deprecated = true];
}
// GenericTarget: same shape.
```

Registration (server side, no new runtime dependency for plugins without protos):

1. A plugin package can expose, next to its jobkit entry point, an optional
   `grpc_config_descriptor` (a `FileDescriptorProto` plus message name) for each `kind`.
2. At startup the server loads each registered descriptor into its descriptor pool and
   runs the schema validator against the plugin's Pydantic config model: every field,
   type, enum, optionality and default must match, as for built-ins. A mismatch fails
   startup, the same way built-in drift does.
3. Request mapping: `typed` is unpacked using the registered descriptor, converted with the
   existing message-to-dict rules (`HasField` for optionals, closed enums to Pydantic enum
   values), and validated with `model_validate` on the plugin's config model. A
   `type_url` that does not match `kind` is `INVALID_ARGUMENT`.
4. `raw` is accepted only when the server has no descriptor for `kind`. It goes straight to
   `model_validate`, so Pydantic stays the type authority. When a descriptor exists, `raw`
   is rejected so clients cannot bypass the typed path.
5. `GetCapabilities` lists plugin kinds in `sources_raw` / `targets_raw`, and a new
   `ConnectorSchema { kind, type_url, has_typed_config }` list lets clients discover which
   kinds take `typed`.

### Why not just `Struct` everywhere

`Struct` would satisfy `extra="allow"` but drops the strong-typing rule for every plugin,
including ones that can declare their schema. The proposal keeps typed messages as the
normal path and limits `Struct` to the case the rules allow: raw data the server cannot type.

### Migration

- Phase 1: add `config` (`typed` / `raw`), keep `attributes`, map `attributes` as today.
  Log a deprecation warning when `attributes` is used.
- Phase 2 (next minor): reject `attributes` when `config` is set; document the removal.
- `buf breaking` (FILE) stays green in phase 1: only additive fields.

### Tests

- A fixture plugin with a nested config model plus its descriptor: typed round trip,
  enum mapping, an `optional` left unset keeps the Pydantic default
  (`model_fields_set` stays truthful, #680 rule).
- Descriptor drift: change a field type in the fixture descriptor and expect startup to fail.
- `raw` accepted for an unregistered kind, rejected for a registered one.
- `type_url` / `kind` mismatch returns `INVALID_ARGUMENT`.

### Open questions for Kristian

1. Should plugin descriptors also come from a server setting (a path to `.binpb` files) for
   plugins we do not control? Proposed: yes, as a second registration source.
2. Should raw fallback be on by default, or behind a setting such as
   `grpc_allow_raw_plugin_config` (proposed default: on, to match REST behaviour)?
