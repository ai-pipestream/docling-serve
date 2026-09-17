# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync arrives.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — save/enable in Cursor Automations.
- Local backup cron: `0 9 * * 1 ~/.local/bin/parity-duty-weekly` → `/work/docling-research/scripts/parity_duty_weekly.sh` (Forgejo open-PR sweep log under `~/.local/share/docling-parity-duty/`).
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-09-17 (late++++)

| Track | State |
| --- | --- |
| Forgejo parser-family dep PRs | **0 open** |
| docling-core `feat/add-protobuf` | At **2.97.0**; `upstream/main` is ancestor. |
| docling-serve `grpc-native-converter` | Content at **1.33.0**; git ancestry still diverges from `upstream/main`. |
| gRParse Convert options (recent) | IntSpan `page_range`; typed VLM configs; **`COLLECTOR_VLM` sole-collector path** (= `PROCESSING_PIPELINE_VLM`). Docker **82/82**. |
| Monday Automation | Draft reopened — **must Save/Enable**. |
| Local Monday cron | Installed (`parity-duty-weekly`). |

## Next agent actions

1. Confirm Monday Automation is saved and enabled.
2. Forgejo dep sweep each cycle.
3. Optional: rewrite/re-sync serve history so `upstream/main` is a true merge parent.
4. Note: gRParse field tags 44+ are fleet-specific; serve uses 44–50 for include_page_images / heading / chunking — same names live at different tags by design.
