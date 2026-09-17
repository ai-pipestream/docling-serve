# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync arrives.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — save/enable in Cursor Automations.
- Local backup cron: `0 9 * * 1 ~/.local/bin/parity-duty-weekly` → `/work/docling-research/scripts/parity_duty_weekly.sh` (Forgejo open-PR sweep log under `~/.local/share/docling-parity-duty/`).
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-09-17 (post-S3 region + DocumentExports)

| Track | State |
| --- | --- |
| Forgejo parser-family dep PRs | **0 open** (weekly script now covers pdfium/poppler/qparse/fastwarc/parser-protos/opennlp too) |
| docling-core `feat/add-protobuf` | At **2.97.0**; `upstream/main` is ancestor (0 behind). |
| docling-serve `grpc-native-converter` | Convert enums/options/settings match upstream tip content (**yaml/vtt/html_split/dclx**, **S3.region**, Ray metrics, artifact region). Git ancestry still diverges (35 commits). |
| gRParse | **S3.region** + prior Convert parity; fleet-only: `canonical_json`/`gdocs_json`, collectors. |
| Monday Automation | Draft open in Glass — **must Save/Enable** (auth required). |
| Local Monday cron | Installed; script expanded to full collector family. |

## Next agent actions

1. Confirm Monday Automation is saved and enabled (user Sign-in in Automations UI).
2. Forgejo dep sweep each cycle (script + rule list).
3. Optional: rewrite/re-sync serve history so `upstream/main` is a true merge parent.
4. Note: gRParse field tags 44+ are fleet-specific; serve chunking fields are at 48–50, gRParse at 52–54 (same names). `OUTPUT_FORMAT_CHUNKS` is enum 13 here (serve uses 11; 11 is GDOCS_JSON in gRParse). `OUTPUT_FORMAT_DCLX` is enum 14 here (serve uses 10; 10 is CANONICAL_JSON in gRParse).

## Next agent actions

1. Confirm Monday Automation is saved and enabled.
2. Forgejo dep sweep each cycle.
3. Optional: rewrite/re-sync serve history so `upstream/main` is a true merge parent.
4. Note: gRParse field tags 44+ are fleet-specific; serve chunking fields are at 48–50, gRParse at 52–54 (same names). `OUTPUT_FORMAT_CHUNKS` is enum 13 here (serve uses 11; 11 is GDOCS_JSON in gRParse). `OUTPUT_FORMAT_DCLX` is enum 14 here (serve uses 10; 10 is CANONICAL_JSON in gRParse).
