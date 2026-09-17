# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync arrives.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — save/enable in Cursor Automations.
- Local backup cron: `0 9 * * 1 ~/.local/bin/parity-duty-weekly` → `/work/docling-research/scripts/parity_duty_weekly.sh` (Forgejo open-PR sweep + upstream tip deltas; logs under `~/.local/share/docling-parity-duty/`; machine-readable `last-status.txt`).
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-09-17 (chunking_info + ProfilingItem)

| Track | State |
| --- | --- |
| Forgejo parser-family dep PRs | **0 open** (weekly script covers full collector family) |
| docling-core `feat/add-protobuf` | At **2.97.0**; `upstream/main` is ancestor (0 behind). |
| docling-serve `grpc-native-converter` | Content matches upstream tip (**yaml/vtt/html_split/dclx**, **S3.region**, Ray metrics, settings). **`PROCESSING_PIPELINE_NATIVE` live**; **ProfilingItem** additive on convert responses; **`ChunkDocumentResponse.chunking_info`** (`map<string, ScalarValue>`). Ancestry still diverges (merge blocked by upstream AI trailer on #641). |
| gRParse | **S3.region**; **ProfilingItem** populated on ConvertSource; **chunking_info** next. Prior Convert parity; fleet-only: `canonical_json`/`gdocs_json`, collectors. |
| Monday Automation | Draft open in Glass — **must Save/Enable** (auth required). |
| Local Monday cron | Installed; script expanded to full collector family. |

## Next agent actions

1. Confirm Monday Automation is saved and enabled (user Sign-in in Automations UI).
2. Forgejo dep sweep each cycle (script + rule list).
3. Ancestry heal only if the AI-trailer pre-push gate is waived or upstream `#641` is rewritten without the Claude trailer.
4. Note: gRParse field tags 44+ are fleet-specific; serve chunking fields are at 48–50, gRParse at 52–54 (same names). `OUTPUT_FORMAT_CHUNKS` is enum 13 here (serve uses 11; 11 is GDOCS_JSON in gRParse). `OUTPUT_FORMAT_DCLX` is enum 14 here (serve uses 10; 10 is CANONICAL_JSON in gRParse).
