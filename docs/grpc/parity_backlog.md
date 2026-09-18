# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync arrives.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — enabled (`4163836e-b285-11f1-a3d8-362438fd9788`).
- Local backup cron: `0 9 * * 1 ~/.local/bin/parity-duty-weekly` → `/work/docling-research/scripts/parity_duty_weekly.sh` (Forgejo open-PR sweep + upstream tip deltas; logs under `~/.local/share/docling-parity-duty/`; machine-readable `last-status.txt`).
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-09-18 (core 2.97.1 + serve 1.34.0)

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
