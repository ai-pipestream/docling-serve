# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync lands.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — save/enable in Cursor Automations.
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-09-17 (later)

| Track | State |
| --- | --- |
| Forgejo parser-family dep PRs | **0 open** (rechecked) |
| docling-core `feat/add-protobuf` | At **2.97**; `upstream/main` not ahead (content merged). |
| docling-serve `grpc-native-converter` | At **1.33.0**; upstream commits may appear “behind” due to squash history, content present. |
| `DOCLING_SERVE_ARTIFACT_STORAGE_REGION` | Settings-only; wired via `orchestrator_factory`. |
| `InputFormat` serve | RTF/MHTML added earlier this cycle. |
| `InputFormat` gRParse | Tags **18–33** now match serve (DOC…EBCDIC + RTF/MHTML). Proto committed; C++ stubs regenerate on next successful cmake build. |
| Chunker `use_markdown_images` / `image_placeholder` | Proto fields present; C++ exporters not consuming yet. |
| Convert-side `chunking_preset` | Serve has it; gRParse uses dedicated chunk RPCs (intentional). |
| Monday Automation | Draft reopened in Automations editor — **must Save/Enable**. |

## Next agent actions

1. Confirm Monday Automation is saved and enabled.
2. Forgejo dep sweep (`FORGEJO_PAT` @ `git.rokkon.com/ai-pipestream`).
3. Fetch upstream; sync if new releases land.
4. Optional: implement gRParse chunker markdown-image options; consume new InputFormat tags in from_formats filtering.
