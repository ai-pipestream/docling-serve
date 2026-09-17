# Docling ↔ gRPC ↔ gRParse parity backlog

Living checklist for the scheduled parity duty. Update when a sync lands.

## Cadence

- Weekly Automation: **Mondays 09:00** (cron `0 9 * * 1`) — save/enable in Cursor Automations.
- Always-on rule: `/work/.cursor/rules/docling-parity-duty.mdc`
- gRParse note: `AGENTS.md` → Recurring parity duty

## Status 2026-09-17

| Track | State |
| --- | --- |
| Forgejo parser-family dep PRs | **0 open** (cleared this cycle) |
| docling-core `feat/add-protobuf` | Synced through **2.97** (image_dir / image_uri_prefix on export helpers; MD/DocLang serializer fixes). Pushed. |
| docling-serve `grpc-native-converter` | Synced through **1.33**. Pushed. |
| `DOCLING_SERVE_ARTIFACT_STORAGE_REGION` | Settings → `orchestrator_factory` → shared by REST and gRPC (`get_async_orchestrator`). **No request-proto field.** |
| Core `export_to_markdown(image_dir=…)` | Local/core API only; not a serve Convert option yet. gRParse is diskless on the hot path — treat as **deferred** unless REST grows matching options. |
| Serve chunking / plugin connectors / `allowed_source_types` | Documented in `pydantic_api_changelog.md`; wire audit still open. |

## Next agent actions

1. Confirm the Monday Automation exists and is enabled (open Automations UI if unsure).
2. `GET …/pulls?state=open` for `ai-pipestream` parser family on `git.rokkon.com` (`FORGEJO_PAT`).
3. `git fetch` docling-core / docling-serve upstream; if ahead, sync → tests → changelog → gRParse ports.
4. Prefer typed proto fields; no JSON bridge; no upstream docling-project PRs for this fork work.
