# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync lands.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — save/enable in Cursor Automations.
- Local backup cron: `0 9 * * 1 ~/.local/bin/parity-duty-weekly` → `/work/docling-research/scripts/parity_duty_weekly.sh` (Forgejo open-PR sweep log under `~/.local/share/docling-parity-duty/`).
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-09-17 (evening)

| Track | State |
| --- | --- |
| Forgejo parser-family dep PRs | **0 open** (rechecked) |
| docling-core `feat/add-protobuf` | At **2.97.0**; `upstream/main` is ancestor (fork ahead with protobuf). |
| docling-serve `grpc-native-converter` | Merged `upstream/main` → tip at **1.33.0**; gRPC mapping/fake tests **118 passed**. |
| gRParse `document_timeout` | **Landed** `9e3234c`: allowlist + deadline cap + coordinator unit test. |
| gRParse `page_range` | **Landed** `9e3234c`: CV scheduler inclusive span; original page nos; page_scheduler unit test. Wire remains `repeated int32` `[start,end]` (serve uses `IntSpan`). |
| Monday Automation | Draft reopened — **must Save/Enable**. |
| gRParse Docker ctest | In progress (host lacks OpenCV 5). |

## Next agent actions

1. Confirm Monday Automation is saved and enabled.
2. Finish Docker `collector-coordinator-test` / `page-scheduler-test` green for `9e3234c`.
3. Forgejo dep sweep each cycle.
4. Image-export cluster (`image_export_mode` / `images_scale`) and streaming `page_range` if DocumentChunk gains the field.
5. PDF-collector / NATIVE path: apply `page_range` when not using CV scheduler.
