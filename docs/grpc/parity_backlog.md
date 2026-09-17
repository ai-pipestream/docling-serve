# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync arrives.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — save/enable in Cursor Automations.
- Local backup cron: `0 9 * * 1 ~/.local/bin/parity-duty-weekly` → `/work/docling-research/scripts/parity_duty_weekly.sh` (Forgejo open-PR sweep log under `~/.local/share/docling-parity-duty/`).
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-09-17 (late++)

| Track | State |
| --- | --- |
| Forgejo parser-family dep PRs | **0 open** (collector family + module-parser / grPOIc / calamine / lol-html) |
| docling-core `feat/add-protobuf` | At **2.97.0**; `upstream/main` is ancestor (fork ahead with protobuf). |
| docling-serve `grpc-native-converter` | Content at **1.33.0** (S3 region settings included). Git ancestry still diverges from `upstream/main` (ours-merge blocked by AI-trailer pre-push on upstream commits). |
| gRParse Convert options (recent) | Classification filters; **typed** `VlmConvertOptions` / `PictureDescriptionVlmEngineOptions` / `CodeFormulaVlmOptions`; **ScalarValue maps** for ocr/table/layout/picture_classification custom configs. Docker **82/82**. Pushed through typed custom_config commit. |
| Monday Automation | Draft reopened — **must Save/Enable**. |

## Next agent actions

1. Confirm Monday Automation is saved and enabled.
2. Forgejo dep sweep each cycle.
3. Optional: migrate PictureDescriptionLocal/Api `generation_config`/`params` from `Value` to `ScalarValue`; typed `vlm_pipeline_model_local`/`api` messages (still strings here).
4. Optional COLLECTOR_VLM enum; streaming `page_range` if DocumentChunk ever carries the field.
5. Optional: rewrite/re-sync serve history so `upstream/main` is a true merge parent without pushing AI-attributed upstream messages through the hook.
