# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync arrives.

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
| gRParse `document_timeout` / `page_range` | In tree `9e3234c` (deadline + CV span); PDF/NATIVE `bf63781` → `PdfOptions.pages`. |
| gRParse `include_images` / `images_scale` / `image_export_mode` | In tree `a4f63a0`/`dbc0455` (picture crops + Markdown export). Docker **81/81** passed. |
| gRParse `ocr_engine` / `do_table_structure` | In tree `4f1358a`: RapidOCR/AUTO accepted; other engines named and turned down; `do_table_structure=false` skips RapidTable. |
| gRParse `table_mode` / `ocr_lang` / `do_picture_classification` | table_mode accepted (single RapidTable); ocr_lang accepted without remapping models; picture classification can be turned off. |
| Monday Automation | Draft reopened — **must Save/Enable**. |

## Next agent actions

1. Confirm Monday Automation is saved and enabled.
2. Forgejo dep sweep each cycle.
3. Remaining Convert options (VLM/picture description, pdf_backend, enrichment presets, …).
4. Streaming `page_range` if DocumentChunk ever carries the field.
