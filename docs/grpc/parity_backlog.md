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
| gRParse `document_timeout` / `page_range` | **Landed** `9e3234c`: deadline cap + CV page span. PDF/NATIVE: `bf63781` forwards as `PdfOptions.pages`. |
| gRParse `include_images` / `images_scale` / `image_export_mode` | **Landed** `a4f63a0`/`dbc0455`: picture crops + Markdown export modes. Docker **81/81** green. |
| Monday Automation | Draft reopened — **must Save/Enable**. |

## Next agent actions

1. Confirm Monday Automation is saved and enabled.
2. Forgejo dep sweep each cycle.
3. Remaining Convert gaps (OCR engine, table/VLM enrichment, etc.).
4. Streaming `page_range` if DocumentChunk gains the field.
