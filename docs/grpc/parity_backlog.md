# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync lands.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — save/enable in Cursor Automations.
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-09-17

| Track | State |
| --- | --- |
| Forgejo parser-family dep PRs | **0 open** (rechecked on `git.rokkon.com/ai-pipestream`) |
| docling-core `feat/add-protobuf` | Synced through **2.97**. Pushed. |
| docling-serve `grpc-native-converter` | Synced through **1.33**. Pushed. |
| `DOCLING_SERVE_ARTIFACT_STORAGE_REGION` | Settings → `orchestrator_factory` → shared by REST and gRPC. **No request-proto field.** |
| Core `export_to_markdown(image_dir=…)` | Deferred (diskless gRParse hot path; not a serve Convert option). |
| `InputFormat.RTF` / `MHTML` | **Fixed** on serve proto + mapping + coverage test. gRParse enum tags **32/33** added (18–31 reserved for later collector-format sync). |
| Convert `chunking_preset` / `chunking_options` | Present on serve `ConvertDocumentOptions`. gRParse uses dedicated hierarchical/hybrid chunk RPCs — intentional shape difference. |
| Chunker `use_markdown_images` / `image_placeholder` | Serve wire present. gRParse proto fields added (C++ optional until exporters consume them). |
| `allowed_source_types` | Server policy / settings only — not a client Convert field. Covered by serve policy tests. |
| Plugin connectors / `max_num_elements` | Serve + jobkit wire present. Out of scope for gRParse unless collector batch grows. |
| gRParse `InputFormat` tags 18–31 | Reserved; fill when porting DOC…EBCDIC `from_formats` filtering. |

## Next agent actions

1. Confirm the Monday Automation exists and is enabled (open Automations UI if unsure).
2. `GET https://git.rokkon.com/api/v1/repos/ai-pipestream/<repo>/pulls?state=open` (`FORGEJO_PAT`).
3. `git fetch` docling-core / docling-serve upstream; if ahead, sync → tests → changelog → gRParse ports.
4. Prefer typed proto fields; no JSON bridge; no upstream docling-project PRs for this fork work.
5. Optional: implement gRParse chunker markdown-image options; fill InputFormat 18–31 when needed.
