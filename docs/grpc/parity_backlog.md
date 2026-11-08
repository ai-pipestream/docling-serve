# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync arrives.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — enabled (`4163836e-b285-11f1-a3d8-362438fd9788`).
- Local backup cron: `0 9 * * 1 ~/.local/bin/parity-duty-weekly` → `/work/docling-research/scripts/parity_duty_weekly.sh` (Forgejo open-PR sweep + upstream tip deltas; logs under `~/.local/share/docling-parity-duty/`; machine-readable `last-status.txt`).
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-11-02 (serve 1.38.2 + slim 2.145.0, core 2.105.0, jobkit 3.9.1)

Merged upstream docling-serve `v1.38.2` (`9c058db`, `#746` dependency ranges). Package version is **1.38.2**. Lock pins **docling-slim 2.145.0** and **docling-jobkit 3.9.1**. There is no jobkit tag after v3.9.1, so later jobkit commits stay out of this lock.

docling-core is pinned to git rev `005037bb9e1af28971204c813e1d7b90be8e70eb` (**2.105.0**) from `https://github.com/ai-pipestream/docling-core`, branch `ai-pipestream/sync-upstream-2026-10-26-8ae9`. That replaces `099ccf93820aff5c02cd1877269a364bdc7c4a9b` (2.104.0). Slim 2.145 requires `docling-core>=2.103.1,<3`. The lock source is that git rev. There is no path dependency. This serve change does not re-port docling-core document behavior. The document proto stays the one imported from that pin.

| Field | Message | Tag |
| --- | --- | --- |
| `filename` | `ZipArchiveResult` | 2 |
| `ocr_auto` | `ConvertDocumentOptions.ocr_options` | 54 |
| `easyocr` | `ConvertDocumentOptions.ocr_options` | 55 |
| `tesseract` (factory kind `tesserocr`) | `ConvertDocumentOptions.ocr_options` | 56 |
| `tesseract_cli` (factory kind `tesseract`) | `ConvertDocumentOptions.ocr_options` | 57 |
| `rapidocr` | `ConvertDocumentOptions.ocr_options` | 58 |
| `ocrmac` | `ConvertDocumentOptions.ocr_options` | 59 |
| `nemotron_ocr` (factory kind `nemotron-ocr`) | `ConvertDocumentOptions.ocr_options` | 60 |
| `kserve_v2_ocr` | `ConvertDocumentOptions.ocr_options` | 61 |

New messages: `OcrLang`, `KserveGrpcChannelArg`, `OcrOptionsBase`, `OcrAutoOptions`, `EasyOcrOptions`, `TesseractOcrOptions`, `TesseractCliOcrOptions`, `RapidOcrOptions`, `OcrMacOptions`, `NemotronOcrOptions`, `KserveV2OcrOptions`.

New enums: `OcrMode`, `RapidOcrBackend`, `RapidOcrModelSize`, `NemotronOcrMergeLevel`, `KserveV2Transport`. Closed literals keep a `*_raw` companion (`mode_raw`, `backend_raw`, `model_size_raw`, `merge_level_raw`, `transport_raw`).

`ocr_custom_config` stays field 39. When `ocr_options` is set, the arm owns every field of that message. The map may only add keys the message does not define. A repeated key is an error. A non-auto `ocr_preset`, or an `ocr_engine` string that is not the arm's factory kind, is an error. `ocr_lang` fills `lang` only when the arm left `lang` unset. Unset optional fields are omitted, so the engine class default stays. Explicit false is written as false. An empty `OcrLang.values` is an empty language list. An omitted `lang` leaves the class default. `kind` is the oneof arm, not a field. Factory kinds: `auto`, `easyocr`, `tesserocr`, `tesseract`, `rapidocr`, `ocrmac`, `nemotron-ocr`, `kserve_v2_ocr`.

`force_full_page_ocr` is `optional bool` tag 6 on `OcrOptionsBase`. It is the deprecated computed alias of `mode = FULL_PAGE`, not a stored Pydantic field. The schema walker treats it as proto-only. Setting both `mode` and `force_full_page_ocr` is an error.

`bitmap_area_threshold` was removed from `OcrOptions` in slim 2.145. It is not a typed field. A key the selected message does not define can still travel in `ocr_custom_config`.

`ZipArchiveResult.filename` is copied only when the caller set it. `None` stays unset. `""` is a real name.

The schema walker discovers `OcrOptions.__subclasses__()` and flattens `OcrOptionsBase` through each engine message's `base` field. A field slim adds later, or a new subclass with no message, fails `test_serve_types_no_pydantic_fields_missing_on_proto`.

### Skipped on the serve wire

| Item | Why it stays out |
| --- | --- |
| ASR option models (`InlineAsrTransformersOptions`, MLX fields, new `AsrModelType`) | Not fields of `ConvertDocumentsOptions`. |
| `GenerationStopper.is_valid_end` | A method, not a request field. |
| jobkit commits after v3.9.1 | No release tag after v3.9.1. |
| docling-core 2.105.0 document edits | The pin moves. Document fields stay on the imported core proto. This PR does not edit them. |

### gRParse

This PR does not change gRParse. Serve now has `ZipArchiveResult.filename` and the typed OCR oneof. Porting those is separate work.

Skips recorded for gRParse this cycle:

| Item | Why it stays out of gRParse |
| --- | --- |
| `ZipArchiveResult.filename` | Not ported in this serve PR. gRParse does not return this zip result model. |
| Typed OCR oneof | Not ported in this serve PR. |
| ASR option families | `asr_service.proto` is whisper.cpp. Those slim option models are not engines that process loads. |
| `GenerationStopper.is_valid_end` | A method, not a request field. |
| RQ settings from serve 1.38.x | gRParse has no RQ. |

## Status 2026-10-26 (serve 1.38.1 + slim 2.142.1, jobkit 3.9.1)

Synced docling-serve `v1.38.1` and upstream `4b0bd7b` (`#744`) onto `feat/docling-2.140-confidence-pages`. Package version is **1.38.1**. Jobkit floor is `>=3.9.1,<4`. Lock pins **docling-slim 2.142.1** (PyPI 2.143.0 was not taken) and **docling-jobkit 3.9.1**. Settings from the merge, no proto tags: `eng_rq_redis_health_check_interval` 30s, `eng_ray_task_metadata_ttl` 7 days, `eng_ray_tenant_metrics_refresh_interval` 30s.

Sweep correction: `serve_main_unreleased=1`. That commit is `4b0bd7b` (`#744`, max sources on the chunk endpoints). It adds no proto tag. gRPC already enforced the cap.

| Field | Message | Tag |
| --- | --- | --- |
| `target_document_version` | `ConvertDocumentRequest` | 5 |
| `target_document_version` | `BatchConvertDocumentRequest` | 6 |
| `RESPONSE_FORMAT_DOCLANG` | `ResponseFormat` | 6 |
| `RESPONSE_FORMAT_DEEPSEEKOCR_MARKDOWN` | `ResponseFormat` | 7 |
| `RESPONSE_FORMAT_UNLIMITED_OCR_MARKDOWN` | `ResponseFormat` | 8 |
| `RESPONSE_FORMAT_CHANDRA_HTML` | `ResponseFormat` | 9 |
| `RESPONSE_FORMAT_DOTS_JSON` | `ResponseFormat` | 10 |
| `RESPONSE_FORMAT_NEMOTRON_PARSE_V2` | `ResponseFormat` | 11 |
| `RESPONSE_FORMAT_NEMOTRON_PARSE_V3_5` | `ResponseFormat` | 12 |
| `RESPONSE_FORMAT_MINERU2` | `ResponseFormat` | 13 |
| `response_format_raw` | `VlmModelLocal` | 9 |
| `response_format_raw` | `VlmModelApi` | 10 |
| `response_format_raw` | `VlmModelSpec` | 14 |
| `trust_remote_code` | `BaseVlmEngineOptions` | 2 |

`VlmModelSpec.trust_remote_code` stays at tag 9. `target_document_version` uses `^\d{1,9}\.\d{1,9}\.\d{1,9}$` and rejects versions older than `1.{FIRST_SUPPORTED_MINOR}.0`. JSON exports and JSON target files are projected. The typed `DoclingDocument` stays on the current schema. Chunk RPCs do not carry the field.

`ZipArchiveResult.filename` was on docling main only in this cycle, not in slim 2.142.1, so it stayed off the wire. Slim 2.145.0 shipped it. The 2026-11-02 cycle adds tag 2.

This cycle's lock pinned docling-core **2.104.0** from `https://github.com/ai-pipestream/docling-core` at `099ccf93820aff5c02cd1877269a364bdc7c4a9b` (branch `ai-pipestream/sync-upstream-2026-10-26-8ae9`). Slim 2.142.1 requires `docling-core>=2.103.1`. The 2026-11-02 cycle moves that pin to `005037bb9e1af28971204c813e1d7b90be8e70eb` (2.105.0) on the same branch. Published `feat/add-protobuf` was still `a7da172` (2.101.1) on 2026-10-26.

### gRParse

Matching proto changes are being done in gRParse separately: `ResponseFormat` members, `response_format_raw`, `BaseVlmEngineOptions.trust_remote_code`, `extract_form_fields`, and the new `StructureRule` values.

Skips recorded for gRParse this cycle:

| Item | Why it stays out of gRParse |
| --- | --- |
| JSON down-projection | gRParse's source of truth is the typed document. A JSON projector would reintroduce a versioned JSON dialect it does not own. |
| Pillow mode `I` | gRParse does not use Pillow. Page rasters are PNG from the CV path. |
| RQ health interval, Ray metadata TTL, Ray tenant metrics refresh | gRParse has no RQ or Ray. |
| Transformers ASR families | `asr_service.proto` is whisper.cpp. A model-family enum would advertise engines the process cannot load. |
| EPUB image default | Already on. `include_images = 5` defaults images on and emits image resources. |

## Status 2026-10-19 (core 2.103.0 + serve 1.37.0, slim 2.140.0)

| Track | State |
| --- | --- |
| docling-core `feat/add-protobuf` | Sync branch `sync/upstream-2026-10-19` merges upstream `main` at **v2.103.0** (2.102.0 plus the 8 post-release commits). Document proto unchanged: the new MIME types are validator-only and `ImageRef.uri` stays a string. Restored the `docling-serialize` console script the original protobuf commit dropped. Descriptor identity against gRParse `document.proto` still fails on 4 gRParse-only messages (`TextAnalysis`, `TextAnalysis.LayerSourcesEntry`, `CollectorWarning`, `ParseIdentity`); this was already true at `a7da172`. |
| docling-serve `grpc-native-converter` | Branch `feat/docling-2.140-confidence-pages`. Lock: slim **2.140.0** (floor raised to `>=2.140.0`, since the mapping reads `ConfidenceScores.pages`), editable core **2.103.0**, jobkit **3.8.2** (no new release). Wire: `ConfidenceScores.pages = 11`. |
| gRParse | See the 2026-10-19 decisions below. |

### gRParse decisions for core 2.103 / slim 2.140

| Feature | Decision | Notes |
| --- | --- | --- |
| `ConfidenceScores.pages` | Add | `map<int32, ConfidenceScores> pages = 11` in `parse_types.proto`, same tag as serve, with per-page grades. |
| `VlmStopReason` / `VlmPrediction.stop_reason` | Add, enhanced | Typed enum with a `_raw` companion on VLM element provenance, so clients can tell a length cut-off or content filter from a clean stop. |
| Contextualized table chunk token limits (#690), `max_tokens_override` | Check, add if cheap | Confirm gRParse's table chunks honour `max_tokens` once headers and context are added. |
| `_count_column_header_rows` (#823) | Check | Compare gRParse's header-row counting with the upstream rule (spanning headers, unflagged row labels in the leading column). |
| `allow_image_file_uri` / `load_local_images` (#900) | Check, document | gRParse must never open `file://` or path image URIs from client documents. If it already does not, record that as stricter than upstream (there is no opt-in). |
| Calendar MIME types (`text/calendar`, `text/x-vcalendar`, `application/calendar+json`, `application/calendar+xml`) (#892) | Defer | docling has no calendar backend; the allowlist only lets `DocumentOrigin` carry the type. gRParse will route calendars when a typed calendar collector exists rather than accept the MIME and produce an empty document. |
| `ThreadedDoclingParseBackendOptions.max_concurrent_results` | Defer | gRParse does not use the threaded docling-parse backend; its PDF collectors stream pages through gRPC with their own back-pressure. A buffered-page limit has nothing to bound. |
| `ApiAsrOptions` | Add in grpc-asr | Remote OpenAI-compatible transcription belongs to the ASR collector, with typed fields and `params` as `map<string, ScalarValue>`. |

## Status 2026-10-14 (core 2.101.1 + serve 1.37.0, slim 2.138.0)

| Track | State |
| --- | --- |
| docling-serve history | One-time `-s ours` merge of upstream `v1.36.0` records ancestry with an identical tree. From here on, sync by merging upstream release tags (no more per-commit replay). |
| docling-serve `parity/serve-1.37.0` | Merged `v1.37.0` (#721, #723, #724, #725). Wire: `INPUT_FORMAT_IWORK_NUMBERS = 36`, `CodeFormulaVlmOptions.expansion_factor = 7`, `.stop_on_repetition = 8`, `CHART_EXTRACTION_OUTPUT_FORMAT_GRANITE_VISION_CHART2CSV = 2`. Lock: jobkit **3.8.2**, slim **2.138.0**, core **2.101.1**. Upstream tests `test_config_file_loading.py::test_nonexistent_config_file_ignored` and `::test_invalid_yaml_ignored` fail on the pure upstream files (they contradict #598 fail-fast config loading); not a gRPC regression. |
| Open gap | REST `GET /v1/capabilities` (from #714) has no gRPC RPC. Needs a typed `GetCapabilities` design (presets, defaults, allowed engines) before it can carry #721/#723 effects to gRPC clients. |
| gRParse | See the 1.37.0 deviation entries below. |

### gRParse decisions for 1.37.0

| Feature | Decision | Notes |
| --- | --- | --- |
| `INPUT_FORMAT_IWORK_NUMBERS = 36` | Add | Mirror the serve tag in `parse_types.proto`, map MIME `application/vnd.apple.numbers` and `.numbers`. Route through the same iWork container reader used for Pages and Keynote, and emit sheets as typed tables (calamine-style cell types) rather than flattened text. |
| `expansion_factor`, `stop_on_repetition` | Add, enhanced | Add the two typed fields to gRParse's code/formula options. Enhancement: also apply repetition detection to API/vLLM engines at stream time (cancel the request) instead of only trimming output afterwards, and report a typed `truncated_for_repetition` flag per element. |
| `GRANITE_VISION_CHART2CSV` output format | Add | gRParse already has `CHART_PRESET_GRANITE_VISION_CHART2CSV` in `enrich_service.proto`; add the matching `ChartExtractionOutputFormat` value in `parse_types.proto` so the custom-config path can select it. |
| `numbering_schemes` `division` / `subdivision` | Add, enhanced | Accept the new names. Enhancement candidate: a typed `NumberingScheme` enum in gRParse with a `_raw` companion, since gRParse may deviate from the upstream `list[str]`. |
| #725 Ray timeouts | Skip (documented) | gRParse does not run a Ray coordinator/replica model; per-document deadlines are already enforced through gRPC deadlines and the worker watchdog. Nothing to mirror. |
| #721 default code/formula preset | Check | Confirm gRParse's default code/formula preset resolves to a real preset (`granite_docling`); if gRParse ships its own default, document it. |
| #723 custom OCR presets selectable | Check | Confirm gRParse's preset policy never filters admin-registered custom OCR presets out of the allow-list. |

## Status 2026-10-11 (core 2.101.1 + serve 1.36.0, slim 2.132.0)

| Track | State |
| --- | --- |
| docling-core `feat/add-protobuf` | Merged `upstream/main` through **2.101.1**. Document proto unchanged (MIME allowlist / DocLang export params / field-item validator only). Schema walker green: 541 Pydantic fields. |
| docling-serve `grpc-native-converter` | Cherry-picked 1.36.0 (viz UI, lock). Wire: `INPUT_FORMAT_IWORK_KEYNOTE = 35`. Lock: jobkit **3.8.1**, slim **2.132.0**, editable core **2.101.1**. |
| gRParse | Added `INPUT_FORMAT_IWORK_KEYNOTE = 35` + MIME/`.key` mapping (`dc700de`). Local ctest blocked (OpenCV 5 missing); CI must confirm. |
| Forgejo parser-family dep PRs | **0 merged**. Open and deferred: gRParse#16 numpy→2.5.4 (core requires `<2.5`); vlm-convert#7 fastapi 0.143, #6 accelerate 1.15; module-parser#71 docling-testcontainers 0.7.0. |

## Status 2026-10-01 (core 2.99.0 + serve 1.35.0, slim 2.130.0)

| Track | State |
| --- | --- |
| docling-core `feat/add-protobuf` | Merged `upstream/main` through **2.99.0**. Document proto unchanged: origin MIME is still a string; AcroForm widget flags live on `SegmentedPage`, not `PageItem`. |
| docling-serve `grpc-native-converter` | Cherry-picked 1.35.0 (UI, chart-extraction policy, RQ metrics, `enable_api_docs`). Convert-option tags 51–53 already covered caption placement and chart extraction. Lock: jobkit **3.8.0**, slim **2.130.0**. |
| gRParse | No new document-wire fields this cycle. |
| Forgejo parser-family dep PRs | **0 merged**. Held: gRParse#12 `@types/node` v26, gRParse#11 CUDA 13.4.2; `@grpc/grpc-js` 1.14.5 demo lockfiles; lol-html#11 protobuf 4.36.2; opennlp#20 protoc 4.36.2; opennlp#21 slf4j 2.0.20; pdf-inspector#9 marked 18.0.14. |

## Status 2026-09-22 (core 2.97.2 + serve 1.34.0, slim 2.129.0)

| Track | State |
| --- | --- |
| docling-core `feat/add-protobuf` | Merged `upstream/main` through **2.97.2** and doclang #785. Caption placement is #786 (markdown export param, not a document field). |
| docling-serve `grpc-native-converter` | Still **1.34.0** (no newer serve release). Lock raised to docling-slim **2.129.0** and editable core **2.97.2**. Wire adds `caption_placement` (51), `chart_extraction_preset` (52), `chart_extraction_custom_config` (53), and optional S3 keys. |
| gRParse | Same fields at tags 55–57. Layout caption order follows the core bbox-center rule. Chart preset is forwarded as `chart_preset_raw`; a custom config that is not chart2csv-only is rejected. Omitted S3 keys use `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` together, or the call is rejected. |
| Forgejo parser-family dep PRs | **0 merged** this cycle. Held: gRParse#12 `@types/node` (CI failure), gRParse#11 CUDA 13.4.1 base image (CI failure), lol-html#11 protobuf 4.36.2 (typos and rust CI failure), opennlp#20 protoc 4.36.2 (no CI status). Still open and held: `@grpc/grpc-js` 1.14.5 demo lockfiles on libreoffice#12, pdf-inspector#8, xml#4, epub#3, markup#7, ebcdic#3, lol-html#10, calamine#10. |

| Track | State |
| --- | --- |
| Forgejo parser-family dep PRs | **8 merged** this cycle (protobuf 4.36.1→4.36.2 on libreoffice#13, email#12, enrich#12, grPOIc#13, calamine#11, opennlp#17/#18; GraalVM native 1.1.13→1.1.14 opennlp#19). **9 held**: `@grpc/grpc-js` 1.14.5 demo lockfiles (CI pending/failed on xml#4, ebcdic#3; others lockfile-only) and lol-html#11 protobuf (typos CI failed). |
| docling-core `feat/add-protobuf` | At **2.97.1**; `upstream/main` is ancestor (0 behind). Serializer-only `#782` (doclang footnotes / grouped furniture vs page-break); no proto change. |
| docling-serve `grpc-native-converter` | Version **1.34.0**. Wire already had Ray metrics `#688` and notifier `#700`. REST `PdfBackend` string rename (`threaded_docling_parse` → `docling_parse`, old value `_docling_parse`) needs no new tag. `usage.md` lists `afp`. Ancestry still diverges (merge blocked by upstream AI trailer on #641). |
| gRParse | No new wire this cycle (footnote fix is Python doclang serializer; PdfBackend rename is REST string-only; AFP already mapped). |
| Monday Automation | **Saved/Enabled** — `4163836e-b285-11f1-a3d8-362438fd9788` (“Docling parity + Forgejo dep PRs”), cron `0 9 * * 1`, `enabled=true` (verified via Automations API). Marker: `~/.local/share/docling-parity-duty/automation-verified`. |
| Local Monday cron | Installed; script expanded to full collector family; honors `~/.local/share/docling-parity-duty/automation-verified`. |

## Next agent actions

1. Forgejo dep sweep each cycle (script + rule list).
2. Ancestry heal only if the AI-trailer pre-push gate is waived or upstream `#641` is rewritten without the Claude trailer.
3. Note: gRParse field tags 44+ are fleet-specific; serve chunking fields are at 48–50, gRParse at 52–54 (same names). `OUTPUT_FORMAT_CHUNKS` is enum 13 here (serve uses 11; 11 is GDOCS_JSON in gRParse). `OUTPUT_FORMAT_DCLX` is enum 14 here (serve uses 10; 10 is CANONICAL_JSON in gRParse).
