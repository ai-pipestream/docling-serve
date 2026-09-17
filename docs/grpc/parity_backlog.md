# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync arrives.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — save/enable in Cursor Automations.
- Local backup cron: `0 9 * * 1 ~/.local/bin/parity-duty-weekly` → `/work/docling-research/scripts/parity_duty_weekly.sh` (Forgejo open-PR sweep log under `~/.local/share/docling-parity-duty/`).
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-09-17 (post-exports YAML/VTT/html_split)

| Track | State |
| --- | --- |
| Forgejo parser-family dep PRs | **0 open** (script covers collectors + grPOIc/calamine/lol-html/module-parser) |
| docling-core `feat/add-protobuf` | At **2.97.0**; `upstream/main` is ancestor. |
| docling-serve `grpc-native-converter` | Content includes **1.33.0 + Ray app metrics (#688)** + **DocumentExports yaml/vtt/html_split_page**. Ancestry still diverges from `upstream/main` tip `c3becab`. |
| gRParse Convert options (recent) | IntSpan `page_range`; typed VLM; `COLLECTOR_VLM`; **CHUNKS**; **DCLX**; **`INPUT_FORMAT_AFP`**; **`OCR_ENGINE_TESSERACT_CLI`**; yaml/vtt/html_split already on wire. |
| Monday Automation | Draft reopened — **must Save/Enable**. |
| Local Monday cron | Installed (`parity-duty-weekly`). |

## Next agent actions

1. Confirm Monday Automation is saved and enabled.
2. Forgejo dep sweep each cycle.
3. Optional: rewrite/re-sync serve history so `upstream/main` is a true merge parent.
4. Note: gRParse field tags 44+ are fleet-specific; serve chunking fields are at 48–50, gRParse at 52–54 (same names). `OUTPUT_FORMAT_CHUNKS` is enum 13 here (serve uses 11; 11 is GDOCS_JSON in gRParse). `OUTPUT_FORMAT_DCLX` is enum 14 here (serve uses 10; 10 is CANONICAL_JSON in gRParse).
