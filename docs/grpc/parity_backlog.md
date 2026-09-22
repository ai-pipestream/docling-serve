# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync arrives.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — enabled (`4163836e-b285-11f1-a3d8-362438fd9788`).
- Local backup cron: `0 9 * * 1 ~/.local/bin/parity-duty-weekly` → `/work/docling-research/scripts/parity_duty_weekly.sh` (Forgejo open-PR sweep + upstream tip deltas; logs under `~/.local/share/docling-parity-duty/`; machine-readable `last-status.txt`).
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-09-22 (core 2.97.2 + serve 1.34.0, slim 2.129.0)

| Track | State |
| --- | --- |
| docling-core `feat/add-protobuf` | Merged `upstream/main` through **2.97.2** and doclang #785. Caption placement is #786 (markdown export param, not a document field). |
| docling-serve `grpc-native-converter` | Still **1.34.0** (no newer serve release). Lock raised to docling-slim **2.129.0** and editable core **2.97.2**. Wire adds `caption_placement` (51), `chart_extraction_preset` (52), `chart_extraction_custom_config` (53), and optional S3 keys. |
| gRParse | Same fields at tags 55–57. Layout caption order follows the core bbox-center rule. Chart preset is forwarded as `chart_preset_raw`; a custom config that is not chart2csv-only is rejected. Omitted S3 keys use `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` together, or the call is rejected. |
| Forgejo parser-family dep PRs | **0 merged** this cycle. Held: gRParse#12 `@types/node` (CI failure), gRParse#11 CUDA 13.4.1 base image (CI failure), lol-html#11 protobuf 4.36.2 (typos and rust CI failure), opennlp#20 protoc 4.36.2 (no CI status). Still open and held: `@grpc/grpc-js` 1.14.5 demo lockfiles on libreoffice#12, pdf-inspector#8, xml#4, epub#3, markup#7, ebcdic#3, lol-html#10, calamine#10. |

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
