# Pydantic API Changelog (upstream model → gRPC wire)

This is the record of every **additive or breaking change in the Pydantic
layer** that the ai-pipestream gRPC fork has had to absorb, and how each one
was accommodated in protobuf. The Pydantic models are the system of record:

- `docling-core` — `DoclingDocument` and its members (`docling_document.proto`)
- `docling` / `docling-slim` — engine enums and option models the request
  surface references (`InputFormat`, `OutputFormat`, `PdfBackend`,
  `ProcessingPipeline`, `VlmModelType`, `HeadingHierarchyOptions`, …)
- `docling-serve` — `ConvertDocumentsRequestOptions`, connector
  sources/targets, `ServicePolicy` (`docling_serve_types.proto`)

Out of scope here: fork-owned proto extensions that have no Pydantic
counterpart (see `proto/ai/docling/core/v1/PARITY.md` in docling-core), the
fork-owned `StreamDocument` service, and upstream fixes that did not change a
model. Field numbers below are the proto tags that were assigned.

Conventions used when accommodating a change:

- Closed proto enum + `*_raw` string companion for every Pydantic enum, so an
  unknown value survives version skew.
- Typed messages for nested option models; `map<string, ScalarValue>` only
  where upstream is genuinely `dict[str, Any]`.
- New fields land on the message that mirrors the Pydantic model that owns
  them. No JSON bridge on the typed path.

## Baseline (2026-06-22)

Fork cut from docling-core **2.83.1** (schema **1.10.0**), docling-serve
**1.25.0**, docling-slim **2.104**, docling-jobkit **1.23**. The initial
proto already carried everything on those models, including the
`VlmModelType` values that upstream had added shortly before
(`NANONETS_OCR2*`, `GLMOCR*`, `LIGHTONOCR*`, `DEEPSEEKOCR_OLLAMA`,
`GRANITEDOCLING*`) and `InputFormat.LATEX/VTT`, `OutputFormat.VTT/DOCLANG`.

## 2026-06-23 — docling-core 2.84 (OpenDocument formats, chart serialization)

| Change | Kind | Layer | Proto accommodation |
| --- | --- | --- | --- |
| `PictureClassificationLabel.OTHER_CHART` added | additive | core | `PICTURE_CLASSIFICATION_LABEL_OTHER_CHART` in the closed enum; round-trip test added. |
| `DocItemLabel.CHART` deprecated in favour of `PICTURE` + `other_chart` meta classification | behavioural | core | No wire change. `DOC_ITEM_LABEL_CHART = 2` stays (still a valid Pydantic value; enums are append-only). |

## 2026-07-02 — docling-serve 1.26, docling-jobkit 2.x

| Change | Kind | Layer | Proto accommodation |
| --- | --- | --- | --- |
| `ServicePolicy.s3_enabled` removed; replaced by `allowed_target_types` plus S3 source/target pairing rules | **breaking** | serve | No wire change. gRPC policy bridge re-pointed at the REST `policy.py` rules; disallowed target types abort with `INVALID_ARGUMENT`. Fake-service S3 tests rewritten. |

## 2026-07-24 — docling-serve 1.27, docling-jobkit 3.0, docling-slim 2.113

| Change | Kind | Layer | Proto accommodation |
| --- | --- | --- | --- |
| Connector sources/targets moved to `docling.datamodel.service` | **breaking** (import surface) | jobkit/serve | No wire change. `mapping.py` imports and source/target pairing reuse the upstream module. |
| `InputFormat` gained `DOC`, `PPT`, `XLS`, `ODT`, `ODS`, `ODP`, `XML_DOCLANG`, `DCLX`, `EMAIL`, `EPUB`, `VIDEO`, `BOXNOTE` | additive | engine | `INPUT_FORMAT_*` tags 18–29; `_map_input_format` entries. |
| `OutputFormat` gained `DCLX`, `CHUNKS` | additive | engine | `OUTPUT_FORMAT_DCLX = 10`, `OUTPUT_FORMAT_CHUNKS = 11`. |

## 2026-08-07 — docling-serve 1.29, docling-jobkit 3.3, docling-slim 2.118

| Change | Kind | Layer | Proto accommodation |
| --- | --- | --- | --- |
| `ConvertDocumentsRequestOptions.do_pdf_heading_hierarchy`, `pdf_heading_hierarchy_options` (`HeadingHierarchyOptions`: `enabled`, `use_bookmarks`, `use_numbering`, `use_style`, `numbering_schemes`, `max_level`, `bookmark_match_threshold`) | additive | serve/engine | `ConvertDocumentOptions` 45, 46; new `HeadingHierarchyOptions` message (fields 1–7). |
| `ConvertDocumentsRequestOptions.include_page_images` | additive | serve | `ConvertDocumentOptions.include_page_images = 44`. |
| `page_range` typed as a `(start, end)` tuple | tightened | serve | `repeated int32 page_range` → `optional ai.docling.core.v1.IntSpan page_range = 12` (same tag, typed). |
| `vlm_pipeline_model_local` / `vlm_pipeline_model_api` became typed models | tightened | serve | `optional string` → `VlmModelLocal` / `VlmModelApi` messages at 27 / 28 (`VlmEngineType` enum, `EngineModelConfig`, `ApiModelConfig`, `VlmModelSpec`). |
| `vlm_pipeline_custom_config` became `VlmConvertOptions` | tightened | serve | `google.protobuf.Struct` → typed `VlmConvertOptions` at 33 (`BaseVlmEngineOptions`, `scale`, `max_size`, `batch_size`, `force_backend_text`). |
| `picture_description_custom_config`, `code_formula_custom_config`, `table_structure_custom_config`, `layout_custom_config`, `ocr_custom_config`, `picture_classification_custom_config` | additive | serve | 34, 35, 36, 37, 39, 43. Typed messages where upstream has a model (`PictureDescriptionVlmEngineOptions`, `CodeFormulaVlmOptions`); `map<string, ScalarValue>` where upstream is `dict[str, Any]`. |
| Picture classification allow/deny lists and min confidence on description/classification options | additive | engine | `repeated PictureClassificationLabel classification_allow/deny`, `classification_min_confidence` on the relevant option messages; `PictureClassificationLabel` closed enum (0–40). |
| Chunker export options `use_markdown_images`, `image_placeholder` | additive | serve | Fields 3/4 and 6/7 on the hierarchical and hybrid chunking option messages. |
| Connectors: `AzureBlobSource/Target`, `GoogleCloudStorageSource/Target`, `GoogleDriveSource/Target`, plugin `GenericSource` (`kind` + attributes) | additive | jobkit/serve | `Source` oneof 4–7, `Target` oneof 6–8; typed credential messages; `map<string, ScalarValue> attributes` for the plugin source. |
| `max_num_elements` on S3 / Azure / GCS sources and targets | additive | jobkit | `optional int32 max_num_elements` on each connector message. |

## 2026-08-14 — docling-slim 2.120

| Change | Kind | Layer | Proto accommodation |
| --- | --- | --- | --- |
| `HeadingHierarchyOptions.use_font_style`, `style_size_tolerance` | additive | engine | `HeadingHierarchyOptions` 8, 9. |

## 2026-08-23 — docling-serve 1.31, docling-slim 2.121, docling-jobkit 3.4

| Change | Kind | Layer | Proto accommodation |
| --- | --- | --- | --- |
| `InputFormat.IWORK_PAGES`, `InputFormat.EBCDIC` | additive | engine | `INPUT_FORMAT_IWORK_PAGES = 30`, `INPUT_FORMAT_EBCDIC = 31`. |

## 2026-08-28 — docling-slim 2.123

| Change | Kind | Layer | Proto accommodation |
| --- | --- | --- | --- |
| `ConvertDocumentsRequestOptions.md_compact_tables` | additive | serve | `ConvertDocumentOptions.md_compact_tables = 47`. |

## 2026-09-03 — docling-serve 1.32, docling-slim 2.124, docling-core 2.94

| Change | Kind | Layer | Proto accommodation |
| --- | --- | --- | --- |
| `OutputFormat.LATEX` | additive | engine | `OUTPUT_FORMAT_LATEX = 12`; `DocumentExports.latex = 7`, produced with `LaTeXDocSerializer` only when requested. |
| In-body `doclang_content` on the export result | additive | serve | `DocumentExports.doclang = 6`. |
| Azure Blob presigned artifact storage | additive | serve | No proto change: this is server configuration, not a request option. |

## 2026-09-05 — docling-core 2.95, docling-slim 2.125 / 2.126

| Change | Kind | Layer | Proto accommodation |
| --- | --- | --- | --- |
| `PdfBackend.THREADED_DOCLING_PARSE` (present since ~2.124, now the upstream default) | additive | engine | `PDF_BACKEND_THREADED_DOCLING_PARSE = 6`; drift guard `test_pdf_backend_proto_covers_pydantic`. |
| `ProcessingPipeline.NATIVE` — model-free PDF text/image extraction (slim 2.126) | additive | engine | `PROCESSING_PIPELINE_NATIVE = 5` reserved now; mapping resolves it via `getattr` so the tag is live the moment the pin can move. A request for it on an engine that lacks it is rejected with `INVALID_ARGUMENT` instead of silently falling back to the default pipeline. Drift guard `test_processing_pipeline_proto_covers_pydantic`. |
| `PdfDestinationKind`, `PdfDestination`, `PdfTableOfContents.destination` | additive | core (parse layer) | No proto change. These live on `ParsedPdfDocument`, which is not carried on the gRPC document wire. The fork's `DoclingDocument.outline` (`OutlineEntry`, field 18) is a separate concept and unchanged. |
| Chandra-OCR MLX minimum-version gate | runtime only | engine | None. Not a `VlmModelType` value. |

Schema version has stayed at **1.10.0** for the whole window; no
`DoclingDocument` structural change has required a proto field since the
baseline.

## Not yet accommodated

- `docling-slim >= 2.125` cannot be locked in docling-serve: `docling-jobkit`
  3.5's `models-vlm-inline` extra pulls `mlx-vlm >= 0.6.17`, which requires
  `transformers >= 5.14` on Darwin while serve's constraints cap it at
  `< 5.9`. The pin stays at `>= 2.124` until jobkit or upstream serve resolves
  it. `PROCESSING_PIPELINE_NATIVE` is therefore reserved but unreachable on
  the current lock.
