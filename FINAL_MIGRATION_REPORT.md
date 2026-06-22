# FINAL_MIGRATION_REPORT.md

Generated: 2026-06-21 22:54 MDT context, final audit requested immediately after commit `3f975a779`.

Purpose: plain-English final boundary report for the Athena/Hermes/sebOS/Photon migration. This is the “what happened and what is true now” document.

## Executive summary

- Migration is safe to stop now. The three repos have no tracked dirty migration work remaining.
- Photon no longer owns sebOS domain execution directly as the primary path. Photon tries the `hermes-sebos` plugin Photon boundary facade first and keeps a narrowed legacy fallback allowlist.
- sebOS remains the domain owner for goals, journal, Mission Control, Reminders, Calendar, router intents, and Apple provider behavior.
- Hermes core is mostly back to generic/runtime concerns, but one known temporary local shim remains: Athena goals injection into prompt context behind a config gate.
- Remaining work is architectural cleanup, not emergency repair: remove the Athena goals core shim later, shrink Photon fallback when confidence is high, and upstream/genericize Hermes patches where appropriate.

## Sources read

Required local docs read:

- `/Users/clawdolf/.hermes/hermes-agent/DOCS_EVIDENCE.md`
- `/Users/clawdolf/.hermes/hermes-agent/DISCOVERY.md`
- `/Users/clawdolf/.hermes/hermes-agent/TARGET_ARCHITECTURE.md`
- `/Users/clawdolf/.hermes/hermes-agent/BOUNDARY_RULES.md`
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_PLAN.md`
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`
- `/Users/clawdolf/.hermes/hermes-agent/UNIT2_BOUNDARY_DESIGN.md`
- `/Users/clawdolf/.hermes/hermes-agent/UNIT3_IMPLEMENTATION_PROMPT.md`

No other `UNIT*.md` files were found under `/Users/clawdolf/.hermes/hermes-agent`.

## Final repo status

### Hermes Agent

Path: `/Users/clawdolf/.hermes/hermes-agent`

- Branch: `clean-stock`
- HEAD: `3f975a779 feat(athena): inject sebOS goals context behind config gate`
- Tracked status: clean.
- `git diff --stat`: empty.
- Ignored files exist. They are generated/dependency/runtime artifacts such as `__pycache__/`, `.pytest-cache/`, `node_modules/`, `venv/`, build outputs, web assets, and test duration files. No actionable untracked migration files remain.

### sebOS

Path: `/Users/clawdolf/.hermes/sebos`

- Branch: `main`
- HEAD: `71a793b fix(reminders): prefer event for read providers`
- Tracked status: clean.
- `git diff --stat`: empty.
- Ignored runtime artifacts exist: `.pytest_cache/`, `__pycache__/`, `inbox/`, `logs/`, `sebos.db`, backups, and `state/`. No actionable untracked migration files remain.

### hermes-sebos plugin

Path: `/Users/clawdolf/.hermes/plugins/hermes-sebos`

- Branch: `main`
- HEAD: `0df6693 package Photon sebOS boundary facade`
- Tracked status: clean.
- `git diff --stat`: empty.
- Ignored status: only `__pycache__/`.

Literal note on the requested “clean or only ignored pycache” check: the plugin repo satisfies that literally. Hermes and sebOS are tracked-clean but have existing ignored generated/dependency/runtime directories beyond pycache. That is normal for these repos and not migration dirt.

## Migration commits by repo

### Hermes Agent commits

- `612ddef34 refactor(photon): route sebOS calls through hermes-sebos facade`
  - Routed Photon/sebOS command paths through the plugin-owned boundary facade with fallback.
  - Covered explicit command routing, board/now/next, active journal prompt, natural route paths, reminder writer execution, audio journal ingest, and fallback narrowing.

- `7984b418e docs(migration): record boundary packaging units`
  - Handoff docs for completed boundary packaging units.

- `29c5391dd docs(migration): record event-primary reminders provider order`
  - Handoff docs for sebOS Reminders provider-order package.

- `7a3748600 refactor(tools): move sebos_event to plugin opt-in`
  - Moved `sebos_event` out of core hardcoding and into plugin opt-in/messaging toolset resolution.

- `5aecff67d feat(gateway): add platform outbound capability hooks`
  - Added generic platform capability hooks and outbound sanitizer behavior.
  - This is generic gateway/platform behavior, not Athena/sebOS-specific behavior.

- `3928d4953 fix(gateway): isolate session platform guard behavior`
  - Removed stale iMessage guidance from Discord session prompts.
  - Corrected Photon shared-cloud guard auth expectation to the real Basic auth shape.

- `3f975a779 feat(athena): inject sebOS goals context behind config gate`
  - Adds the temporary Athena goals prompt-context shim.
  - This is explicitly marked as local fork debt and future migration target.

### sebOS commits

- `8508131 fix(reminders): resolve remindctl in stripped PATH contexts`
  - Hardened Reminders reliability for stripped PATH/Hermes/launchd contexts.

- `cbdadca feat(journal): add pending prompt CLI`
  - Added `sebos-journal-pending-prompt` CLI with tests.

- `2dc2647 feat(router): add read-only reminder command intents`
  - Added read-only router intents for “what reminders do I have” and “where am I” style queries.
  - Explicitly did not enable a default Apple Notes writer/appender.

- `71a793b fix(reminders): prefer event for read providers`
  - Made Apple Reminders read/delete/provider behavior prefer `event` where approved, with fallback.

### hermes-sebos plugin commits

- `0df6693 package Photon sebOS boundary facade`
  - Made `/Users/clawdolf/.hermes/plugins/hermes-sebos` durable as its own local git repo.
  - Tracks `plugin.yaml`, `__init__.py`, `tools.py`, `photon_boundary.py`, `.gitignore`, and `README.md`.

## Current boundaries

### Photon transport/facade behavior

Photon is still the iMessage transport/front desk. It owns:

- inbound/outbound normalization,
- thread/reply/attachment mechanics,
- tapbacks/quiet replies,
- sidecar and Spectrum/Photon transport concerns,
- iMessage-specific safety gates,
- user-facing ack/text behavior.

Photon no longer treats sebOS command execution as an open-ended direct subprocess surface. It now tries the `hermes-sebos` Photon boundary facade first for migrated sebOS paths. If the plugin boundary is unavailable or fails, Photon falls back to the old `_run_sebos_json` path only for a narrowed allowlist:

- `sebos-route-command`
- `sebos-render-mission-control`
- `sebos-journal-pending-prompt`
- `sebos-add-reminder`
- `sebos-ingest-journal`

That fallback remains intentional rollback safety. It is also remaining debt.

### hermes-sebos plugin role

`hermes-sebos` is the local plugin boundary between Hermes/Photon and sebOS.

It currently owns:

- `sebos_event` plugin tool implementation and validation,
- opt-in behavior for messaging toolsets,
- Photon-facing sebOS facade in `photon_boundary.py`, including:
  - `run_sebos_json(...)`,
  - `route_text_command(...)`,
  - `render_mission_control(...)`,
  - `active_journal_prompt_date(...)`,
  - `add_reminder(...)`,
  - `ingest_journal(...)`.

The facade preserves legacy JSON contracts and keeps raw CLI/tool text from becoming user-facing copy.

It is not yet a full MCP server or generalized context provider.

### sebOS domain ownership

sebOS owns the domain state and deterministic local behavior:

- goals and north-star operating state,
- journal and pending prompt logic,
- Mission Control / Control Center rendering,
- command router intents,
- Reminders and Calendar reads/writes/provider ordering,
- Apple domain behavior,
- local SQLite/state files,
- finance/WHOOP/Close/etc. domain adapters outside this migration scope.

sebOS stays outside Hermes core. Hermes calls it through plugin/tool/facade boundaries.

### Hermes core remaining local shims

Known remaining local shim:

- Athena goals injection in:
  - `agent/agent_init.py`
  - `agent/prompt_builder.py`
  - `agent/system_prompt.py`
  - tests under `tests/agent/`

What it does:

- Reads config key `athena.goals_injection`, default enabled.
- Reads `athena.goals_file`, defaulting to `sebos/state/athena_goals.json` under `get_hermes_home()`.
- Renders a compact `# Athena Operating Goals` block from sebOS-owned JSON.
- Injects that block into the system prompt context tier.
- Fails closed on missing/malformed/empty goals and length-caps output.

Verdict:

- Acceptable temporarily.
- Not acceptable as final architecture.
- Future target: `hermes-sebos` plugin context provider or sebOS MCP/resource/prompt plus a generic Hermes context-provider hook.

Other Hermes patches that may be upstreamable/generic:

- platform outbound capability hooks,
- outbound sanitizer,
- session/platform guard cleanup,
- plugin opt-in messaging toolset support.

Those are generic enough to consider upstreaming after one more review pass.

### Calendar/Reminder provider order

Calendar:

- Calendar reads prefer `event calendar list --json` and fall back to SQLite when needed.
- Calendar writes use `event calendar create/update/delete`.

Reminders:

- Reminder reads prefer `event reminders list --json`.
- `remindctl` remains fallback, with JXA/SQLite behavior where existing code supports it.
- Reminder writes use provider order `event -> remindctl` in auto mode.
- Reminder delete matching prefers event-backed listing, then remindctl fallback.
- Fallback is preserved for stripped PATH, unavailable CLI, denied permissions, malformed JSON, or unsupported advanced fields.

This matches the approved direction: EventKit/`event` primary over `remindctl` where approved.

## Tests confirmed during migration

The handoff records the following successful test evidence:

### Photon / hermes-sebos boundary

- Unit 3 explicit command route:
  - `31 passed`
  - sebOS router `46 passed`
  - static/focused follow-up `33 passed`
  - `py_compile` passed

- Unit 4 board/now/next:
  - `36 passed`
  - sebOS router `46 passed`
  - focused follow-up `33 passed`
  - `py_compile` passed

- Unit 5 active journal prompt:
  - `38 passed`
  - sebOS router `46 passed`
  - focused follow-up `34 passed`
  - `py_compile` passed

- Unit 6 natural note/journal/board route:
  - `40 passed`
  - sebOS router `46 passed`
  - focused follow-up `36 passed`
  - `py_compile` passed

- Unit 7 natural reminder writer:
  - initial failure fixed in test default mocking
  - final `43 passed`
  - sebOS router `46 passed`
  - focused follow-up `38 passed`
  - `py_compile` passed

- Unit 8 audio journal ingest:
  - `46 passed`
  - sebOS router `46 passed`
  - focused follow-up `40 passed`
  - `py_compile` passed

- Unit 10 fallback allowlist narrowing:
  - `49 passed`
  - sebOS router `46 passed`
  - focused Photon `43 passed`
  - repeated sebOS router `46 passed`
  - `py_compile` passed

- Unit 12 plugin packaging:
  - Hermes focused `43 passed`
  - sebOS router `46 passed`
  - plugin `py_compile` passed

### Dirty work/package commits

- Unit 13 reconcile pass:
  - Hermes review suite `338 passed, 1 skipped`
  - sebOS combined `54 passed`
  - `py_compile` passed

- Unit 14 Reminders reliability:
  - `tests/test_reminders.py`: `8 passed`
  - command-router + reminders: `54 passed`
  - `py_compile` passed
  - `git diff --cached --check` passed

- Unit 15 pending journal prompt CLI:
  - CLI tests `4 passed`
  - CLI + journal suite `63 passed`
  - `py_compile` passed
  - `git diff --cached --check` passed

- Unit 16 command-router review:
  - router tests `46 passed`
  - combined suite `58 passed`
  - `py_compile` passed

- Unit 17 read-only command intents:
  - router tests `46 passed`
  - combined suite `58 passed`
  - `py_compile` passed
  - static check showed no default Apple Notes writer/appender

- Unit 18 review/provider audit:
  - Hermes dirty review suite `299 passed, 1 skipped`
  - Photon focused `43 passed`
  - sebOS focused `58 passed`
  - provider suites `28 passed`

- Unit 19 event-primary Reminders:
  - provider/router focused `73 passed`
  - broader provider/router `88 passed`
  - full sebOS suite `546 passed`
  - `py_compile` passed
  - read-only live provider check returned event sources for today/overdue/week

- Unit 20 `sebos_event` plugin migration:
  - `34 passed`
  - `py_compile` passed
  - registry opt-in probe passed

- Unit 21 platform capability/outbound sanitizer:
  - `15 passed`
  - `py_compile` passed

- Unit 22 session/Photon guard:
  - `83 passed`
  - `py_compile` passed

- Unit 23 Athena goals review:
  - `167 passed, 1 skipped`
  - `py_compile` passed

- Final Athena commit package:
  - `167 passed, 1 skipped`
  - `py_compile` passed
  - `git diff --cached --check` passed

## Remaining debt

### 1. Athena goals injection temporary local shim

Status: known, accepted, documented debt.

Why it exists:

- It preserves Athena’s current north-star behavior now.
- It avoids memory drift by reading sebOS-owned goals state.
- It is config-gated and fail-closed.

Why it should move:

- It hardcodes Athena/sebOS behavior in Hermes core.
- It directly reads a sebOS-owned JSON file from generic agent initialization/prompt code.
- It belongs behind a plugin/MCP/context-provider boundary.

Target:

- `hermes-sebos` plugin context provider, or
- sebOS MCP resource/prompt exposing read-only `athena_goals`, plus
- generic Hermes context-provider hook for stable/context prompt injection.

### 2. Photon/sebOS fallback allowlist

Status: intentional rollback safety, still debt.

Current allowlist:

- `sebos-route-command`
- `sebos-render-mission-control`
- `sebos-journal-pending-prompt`
- `sebos-add-reminder`
- `sebos-ingest-journal`

Why keep now:

- It makes runtime rollback low-risk if the plugin facade fails.
- It preserves current iMessage behavior.

Future cleanup:

- Add observability for facade-vs-fallback usage.
- Remove or further narrow fallback once real runtime confidence exists.

### 3. Upstreamable Hermes patches

Likely upstreamable after review:

- generic platform capability declarations,
- outbound sanitizer plumbing,
- plugin messaging-toolset opt-in,
- session/platform prompt guard cleanup,
- perhaps generic context-provider hook needed for Athena goals migration.

Do not upstream Seb-specific Athena/sebOS behavior.

### 4. Plugin/MCP future work

Future units:

- Turn Athena goals into a read-only `hermes-sebos` context provider or sebOS MCP resource/prompt.
- Decide whether sebOS should expose broader resources/prompts through MCP, especially goals, Mission Control, journal prompt status, and read-only state summaries.
- Keep write paths explicit and approval-gated. Do not expose broad mutating sebOS APIs without tool filtering/allowlists.

### 5. Ignored/runtime cleanup, optional

Not migration-blocking:

- Hermes has many ignored generated/dependency directories.
- sebOS has ignored runtime state, DB, logs, backups.
- Plugin has ignored pycache only.

If Seb wants a cosmetic cleanup later, do it as a separate cleanup unit. Do not mix it with boundary migration.

## What is true now

- Hermes Agent is the runtime.
- Athena is the user-facing operator identity.
- Photon is iMessage transport/front desk.
- sebOS is the domain state/executor.
- `hermes-sebos` is now a durable local plugin boundary repo.
- Dolf/OpenClaw paths are not active migration targets.
- No gateway restart, launchd edit, live send, push, PR, rebase, merge, force-push, Apple mutation, Close mutation, Monarch mutation, Photon mutation, Telegram mutation, or finance mutation was performed in the final audit/report step.

## Safe stop verdict

Safe to stop: yes.

Reason:

- Tracked worktrees are clean across Hermes, sebOS, and `hermes-sebos`.
- The current runtime boundary is documented and tested.
- Remaining debt is known, bounded, and not blocking current operation.
- The only architecture violation left is deliberately labeled as a temporary local shim.

## Exact next recommendation

Do not keep poking this migration tonight unless there is a concrete bug.

Next useful unit, when approved:

1. Design the generic Hermes context-provider hook needed to remove Athena goals from core.
2. Implement a read-only `hermes-sebos` or sebOS MCP `athena_goals` provider.
3. Prove prompt parity against the current Athena goals tests.
4. Remove the direct sebOS file read from `agent_init.py`.
5. Commit that as one bounded cleanup unit.

Until then, stop. The system is in a coherent, documented state.
