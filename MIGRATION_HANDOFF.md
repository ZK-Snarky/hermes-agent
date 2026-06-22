# MIGRATION_HANDOFF.md

## Session scope

Docs-grounded architecture migration audit for Athena/Hermes/sebOS/Photon. Phases 0-4 only. No implementation, no gateway restart, no launchd change, no live iMessage send, no external mutations.

## Docs read

Official/local Hermes docs:
- `website/docs/user-guide/features/plugins.md`
- `website/docs/user-guide/features/mcp.md`
- `website/docs/user-guide/features/tools.md`
- `website/docs/developer-guide/adding-tools.md`
- `website/docs/developer-guide/tools-runtime.md`
- `website/docs/developer-guide/adding-platform-adapters.md`
- `website/docs/developer-guide/gateway-internals.md`
- `website/docs/user-guide/messaging/photon.md`
- `website/docs/user-guide/configuration.md`
- `website/docs/user-guide/profiles.md`
- `website/docs/user-guide/multi-profile-gateways.md`
- `website/docs/user-guide/features/skills.md`
- `website/docs/user-guide/features/cron.md`
- `website/docs/user-guide/features/memory.md`
- `website/docs/user-guide/features/memory-providers.md`

Official online URLs inspected:
- https://hermes-agent.nousresearch.com/docs
- https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins
- https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp
- https://hermes-agent.nousresearch.com/docs/user-guide/features/tools
- https://hermes-agent.nousresearch.com/docs/user-guide/messaging/photon
- https://hermes-agent.nousresearch.com/docs/user-guide/configuration
- https://hermes-agent.nousresearch.com/docs/developer-guide/
- https://docs.photon.codes/llms.txt, fetched successfully via canonical redirect to https://photon.codes/docs/llms.txt, HTTP 200

Local convention/reference files read:
- `/Users/clawdolf/.hermes/skills/devops/hermes-boundary-migration/SKILL.md`
- `/Users/clawdolf/.hermes/skills/software-development/sebos-architecture/references/hermes-compatible-sebos-boundaries.md`
- `/Users/clawdolf/.hermes/skills/software-development/sebos-architecture/references/photon-imessage-routing-and-models.md`
- `/Users/clawdolf/.hermes/skills/software-development/sebos-architecture/references/athena-hermes-goals-photon-operationalization-20260621.md`
- `/Users/clawdolf/.hermes/skills/software-development/sebos-architecture/references/mission-control-apple-notes-reminders.md`
- `/Users/clawdolf/.hermes/skills/software-development/sebos-architecture/references/photon-marker-audio-journal-recovery.md`
- `/Users/clawdolf/.hermes/tmp/hermes-boundary-migration-claude-output-20260621.md`

## Code inspected

Hermes:
- `plugins/platforms/photon/adapter.py`
- `toolsets.py`
- `tools/registry.py`
- `model_tools.py`
- `gateway/run.py`
- `gateway/session.py`
- `gateway/platform_registry.py`
- `gateway/outbound_sanitize.py`
- `agent/agent_init.py`
- `agent/prompt_builder.py`
- `agent/system_prompt.py`
- tests under `tests/plugins/platforms/photon`, `tests/agent`, `tests/gateway`, `tests/tools`, `tests/test_toolsets.py`

sebOS/plugin:
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/plugin.yaml`
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/__init__.py`
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/tools.py`
- `/Users/clawdolf/.hermes/sebos/lib/command_router.py`
- `/Users/clawdolf/.hermes/sebos/lib/reminders.py`
- `/Users/clawdolf/.hermes/sebos/lib/reminder_writer.py`

## Files written

- `/Users/clawdolf/.hermes/hermes-agent/DOCS_EVIDENCE.md`
- `/Users/clawdolf/.hermes/hermes-agent/DISCOVERY.md`
- `/Users/clawdolf/.hermes/hermes-agent/TARGET_ARCHITECTURE.md`
- `/Users/clawdolf/.hermes/hermes-agent/BOUNDARY_RULES.md`
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_PLAN.md`
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`

## Commands run

```bash
cd /Users/clawdolf/.hermes/hermes-agent
git branch --show-current
git status --short
git diff --stat
git diff --name-status

cd /Users/clawdolf/.hermes/sebos
git branch --show-current
git status --short
git diff --stat
git diff --name-status

cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/test_toolsets.py tests/tools/test_sebos_event.py -q -o 'addopts='

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q

whoami
stat -f%Su /dev/console
launchctl print "gui/$(id -u)" >/dev/null 2>&1 && echo "gui domain OK" || echo "no gui domain"
```

## Test results

- Hermes focused tests: `60 passed in 2.33s`.
- sebOS command router tests: `46 passed in 0.07s`.
- Environment: shell user `clawdolf`, console user `clawdolf`, GUI domain OK.

## Highest-risk boundary violations

1. Photon adapter owns sebOS domain calls and direct subprocess routing. Evidence: hardcoded sebOS paths `adapter.py:92-96`, subprocess runner `:388-424`, write calls `:745-753`, `:1091-1096`, `:1119-1127`, pre-agent short circuit `:1687-1709`.
2. Photon intent gate can mutate sebOS before Hermes/Athena tool boundary. Evidence: classifier/writes/short-circuit in adapter.
3. `reminder_writer.py` Terminal fallback can launch a temp `.command` via `open`. Evidence: `lib/reminder_writer.py:33-48`, defaults `:84-100`, `:336-357`.
4. Core prompt injection reads sebOS goals directly. Evidence: `agent/agent_init.py:1273-1295`, `agent/system_prompt.py:421-426`.
5. Core bridge `include_in_messaging_toolsets` may expose plugin tools to `_HERMES_CORE_FAMILY`, not strictly messaging. Evidence: `toolsets.py:576-588`, `:724-729`.

## Highest-confidence recommendations

1. Move sebOS/Athena domain policy out of Photon adapter. Keep Photon transport-only.
2. Expose sebOS through `hermes-sebos` plugin for narrow native tools and/or sebOS MCP for broader resources/tools/prompts.
3. Keep Apple Reminders/Notes/Calendar semantics inside sebOS.
4. Keep generic platform capability/sanitizer support only if it stays platform-neutral and tested.
5. Freeze/export current dirty patches before any Hermes update/rebase.

## Low-confidence / docs-ambiguous areas

- Exact per-profile plugin directory behavior needs source confirmation before relying on profile-scoped plugin isolation.
- Whether `include_in_messaging_toolsets` should be upstreamed or replaced by documented plugin toolset configuration needs maintainer decision.
- Whether Athena goals should be plugin injected context, config-backed prompt hint, context engine provider, or accepted local fork debt needs decision.
- Whether `reminder_writer.py` Terminal fallback should be disabled from non-interactive/Photon paths needs Seb decision.
- Deep Photon/Spectrum provider implementation must read specific docs pages and installed `spectrum-ts` source before SDK-level changes.

## Recommended first implementation unit

Do P0 freeze/export, then a small P2 boundary slice before de-domaining Photon:
- snapshot current Hermes/sebOS/plugin state,
- prove `hermes-sebos` plugin loads in the active profile,
- add or confirm a non-Photon sebOS route surface for `reminders_read`, `reminder_write`, `board`, `note/journal_write`,
- then switch Photon to call that boundary in P1.

Do not start P1 alone. It risks breaking iMessage behavior while removing the old direct path.

## What still needs Seb approval

- Any code implementation.
- Any commit/stash that changes current working state.
- Any gateway restart.
- Any launchd change.
- Any live iMessage/Reminders/Notes/Close/Monarch mutation.
- Decision: plugin-only, MCP-only, or hybrid sebOS boundary.
- Decision: keep/disable Terminal fallback for reminder writes from non-interactive paths.

## Unit 1 execution update — 2026-06-22

Scope executed:
- P0 freeze/export current Hermes, sebOS, and `hermes-sebos` plugin state.
- Smallest P2 boundary-prep slice: verified active-profile plugin discovery and `sebos_event` registration.
- No Photon de-domaining, no gateway restart, no launchd edit, no live iMessage send, no Reminders/Notes/Close/Monarch mutation, no push/merge/force-push.
- No behavior/code changes made by this unit; only migration handoff/export artifacts were written.

Verified current state:
- Hermes repo branch: `clean-stock`.
- Hermes dirty state remains present and exported.
- sebOS repo branch: `main`.
- sebOS dirty state remains present and exported.
- Runtime plugin directory exists at `/Users/clawdolf/.hermes/plugins/hermes-sebos` and is not a git repo, so it was copied into the export bundle.

Plugin load proof:
- Plugin scanner source paths: bundled `/Users/clawdolf/.hermes/hermes-agent/plugins`, user `/Users/clawdolf/.hermes/plugins`.
- Config has `plugins.enabled: [hermes-sebos]`.
- `hermes-sebos` loaded from user plugins with `enabled: true`, `tools: 1`, `error: null`.
- `sebos_event` registered in toolset `sebos`.
- `sebos_event.include_in_messaging_toolsets == true`.
- `sebos_event` requirement check returned `true`.
- `registry.get_messaging_optin_tool_names()` returned `['sebos_event']`.

Export bundle:
- Workspace: `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z`
- Archive: `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z.tar.gz`
- Plan: `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z/EXPORT_PLAN.md`
- Plugin proof: `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z/plugin-load-proof.json`

Verification commands and results:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/test_toolsets.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 34 passed in 1.24s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.08s
```

Rollback notes:
- Use `hermes/staged.patch`, `hermes/unstaged.patch`, and `hermes/untracked_snapshot/` inside the export workspace to restore Hermes state.
- Use `sebos/staged.patch`, `sebos/unstaged.patch`, and `sebos/untracked_snapshot/` to restore sebOS state.
- Use `plugin-hermes-sebos/` in the export workspace to restore the runtime plugin copy.

Next single task:
- Define and implement the non-Photon sebOS route boundary for reminders/board/note/journal, then switch Photon over in a separate approved P1 unit.

Blockers needing Seb approval:
- Whether the route boundary should be plugin-only, MCP-only, or hybrid.
- Whether reminder writer Terminal fallback is allowed from non-interactive paths.
- Any code change that touches Photon routing, sebOS writes, live config, gateway process, launchd, or live sends.

## Exact next prompt for a fresh implementation session

```text
You are implementing the next unit of the Athena/Hermes/sebOS/Photon boundary migration. Read these files first:
/Users/clawdolf/.hermes/hermes-agent/DOCS_EVIDENCE.md
/Users/clawdolf/.hermes/hermes-agent/DISCOVERY.md
/Users/clawdolf/.hermes/hermes-agent/TARGET_ARCHITECTURE.md
/Users/clawdolf/.hermes/hermes-agent/BOUNDARY_RULES.md
/Users/clawdolf/.hermes/hermes-agent/MIGRATION_PLAN.md
/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md

Mission: design and implement the smallest non-Photon sebOS route boundary for reminders/board/note/journal only after Seb chooses plugin-only, MCP-only, or hybrid. Do not de-domain Photon until that boundary is tested. Do not restart gateway, edit launchd, send iMessages, mutate Reminders/Notes/Close/Monarch, push, merge, or force-push without explicit approval. Preserve current behavior.
```

## Unit 2 boundary design update — 2026-06-22

Scope executed:
- Designed Unit 3 only. No code behavior changes, no Photon de-domain, no gateway restart, no launchd edit, no live iMessage send, no external data mutation, no push/merge/rebase/stash/commit.
- Verified Unit 1 export artifacts still exist:
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z`
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z.tar.gz`

Docs read:
- `/Users/clawdolf/.hermes/skills/devops/hermes-boundary-migration/SKILL.md`
- `/Users/clawdolf/.hermes/hermes-agent/DOCS_EVIDENCE.md`
- `/Users/clawdolf/.hermes/hermes-agent/DISCOVERY.md`
- `/Users/clawdolf/.hermes/hermes-agent/TARGET_ARCHITECTURE.md`
- `/Users/clawdolf/.hermes/hermes-agent/BOUNDARY_RULES.md`
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_PLAN.md`
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`

Files inspected:
- `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py`
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/plugin.yaml`
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/__init__.py`
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/tools.py`
- `/Users/clawdolf/.hermes/sebos/lib/command_router.py`
- `/Users/clawdolf/.hermes/sebos/lib/reminders.py`
- `/Users/clawdolf/.hermes/sebos/lib/reminder_writer.py`
- `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_rules.py`
- `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_intent_gate.py`
- Relevant Photon tests discovered by grep under `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon`

State verification:
- Hermes repo branch: `clean-stock`.
- sebOS repo branch: `main`.
- Existing dirty worktrees remain; Unit 2 added docs only.
- Required grep was run against `plugins/platforms/photon/adapter.py` and `tests/plugins/platforms/photon` for sebOS/Athena coupling terms.

Files written/updated:
- Created `/Users/clawdolf/.hermes/hermes-agent/UNIT2_BOUNDARY_DESIGN.md`
- Created `/Users/clawdolf/.hermes/hermes-agent/UNIT3_IMPLEMENTATION_PROMPT.md`
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_PLAN.md`
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`

Design chosen:
- Use the existing `hermes-sebos` user plugin as the near-term Hermes/sebOS boundary for Unit 3.
- Add a plugin-owned Photon route facade in parallel, backed by sebOS CLI wrappers.
- Route only the explicit sebOS command path through that facade first, with fallback to Photon’s current `_run_sebos_json` path.
- Do not introduce MCP in Unit 3; keep MCP as a future broader resources/prompts/tools option.

Recommended Unit 3 target:
- Add `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`.
- Minimally update `plugins/platforms/photon/adapter.py` so the explicit command branch around `sebos-route-command` delegates to the plugin facade first and falls back to old behavior.
- Update focused Photon tests to prove boundary delegation and fallback parity.
- Do not touch board, natural intent gate, date parsing, reminder writer behavior, audio journal, gateway, launchd, live config, or sebOS domain code.

Tests run and results:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 30 passed in 1.32s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.07s
```

Rollback notes:
- Unit 2 only wrote/updated migration docs. Rollback is deleting `UNIT2_BOUNDARY_DESIGN.md` and `UNIT3_IMPLEMENTATION_PROMPT.md`, then reverting the appended sections in `MIGRATION_PLAN.md` and `MIGRATION_HANDOFF.md`.
- No runtime behavior was changed.

Blockers or decisions needed from Seb:
- No decision needed before Unit 3 if Seb approves only the prompt in `/Users/clawdolf/.hermes/hermes-agent/UNIT3_IMPLEMENTATION_PROMPT.md`.
- Seb approval is needed before any expansion into MCP, natural intent migration, reminder writer Terminal fallback changes, audio journal migration, gateway restart/live smoke, launchd, live sends, or external mutations.

Exact next prompt path:
- `/Users/clawdolf/.hermes/hermes-agent/UNIT3_IMPLEMENTATION_PROMPT.md`

## Unit 3 smallest boundary slice update — 2026-06-22

Scope executed:
- Implemented the approved smallest Unit 3 slice only: introduced a `hermes-sebos` plugin-owned Photon route facade and routed only the explicit Photon sebOS command path through it.
- Preserved the existing Photon `_run_sebos_json` fallback for plugin-boundary import/unavailability/facade failure.
- No gateway restart, no launchd edit, no live iMessage/Photon send, no Reminders/Notes/Close/Monarch/Telegram/Calendar/WHOOP/finance mutation, no push/merge/rebase/stash/commit, and no sebOS repo edits.

Docs read:
- `/Users/clawdolf/.hermes/skills/devops/hermes-boundary-migration/SKILL.md`
- `/Users/clawdolf/.hermes/hermes-agent/DOCS_EVIDENCE.md`
- `/Users/clawdolf/.hermes/hermes-agent/DISCOVERY.md`
- `/Users/clawdolf/.hermes/hermes-agent/TARGET_ARCHITECTURE.md`
- `/Users/clawdolf/.hermes/hermes-agent/BOUNDARY_RULES.md`
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_PLAN.md`
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`
- `/Users/clawdolf/.hermes/hermes-agent/UNIT2_BOUNDARY_DESIGN.md`

State verification before edits:
- Hermes repo branch: `clean-stock`; existing dirty worktree preserved.
- sebOS repo branch: `main`; existing dirty worktree preserved and not edited in Unit 3.
- Unit 1 workspace and archive verified present:
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z`
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z.tar.gz`

Files changed by Unit 3:
- Created `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`.
- Updated `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py`.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_rules.py`.
- Added `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_photon_boundary.py`.
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`.

Behavior migrated:
- Explicit `_handle_sebos_rules` commands that match `_looks_like_sebos_command`, including `reminder: ...` and `j: ...`, now call private Photon helper `_route_explicit_sebos_command`.
- `_route_explicit_sebos_command` tries `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py::route_text_command(...)` first with `write=True`, `db_path=str(_SEBOS_DB_PATH)`, `channel="imessage"`, and `timeout=45.0`.
- If the plugin boundary is unavailable or raises, Photon falls back to the old `_run_sebos_json("sebos-route-command", "--text", "-", "--write", "--db", str(_SEBOS_DB_PATH), "--json", stdin=text, timeout=45.0)` path.
- User-facing reply/tapback behavior after the route result is unchanged.

Tests run and results:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 31 passed in 1.30s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.07s

cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py -q -o 'addopts='
# 33 passed in 1.43s

cd /Users/clawdolf/.hermes/hermes-agent
python -m py_compile plugins/platforms/photon/adapter.py /Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py
# passed
```

Static verification run:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
rg -n "sebos-route-command|sebos-add-reminder|sebos-journal-pending-prompt|sebos-ingest-journal|_run_sebos_json|photon_boundary" plugins/platforms/photon/adapter.py tests/plugins/platforms/photon/test_sebos_rules.py /Users/clawdolf/.hermes/plugins/hermes-sebos
```
Result summary:
- New plugin facade owns the direct `sebos-route-command` CLI construction for the migrated explicit-command path.
- Photon adapter still contains `_run_sebos_json` and direct sebOS CLI calls for fallback plus unmigrated paths: Mission Control board, active journal prompt, audio journal ingest, natural reminder writer, and natural note/journal/board intent routing.
- Focused tests now prove explicit command facade delegation and old-runner fallback parity.

Rollback notes:
- Revert changes to `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py` and `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_rules.py`.
- Remove `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_photon_boundary.py`.
- Remove `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`.
- Existing Photon `_run_sebos_json` fallback remains, so runtime rollback is low-risk.

Remaining Photon/sebOS boundary debt:
- `_run_sebos_json` remains in Photon as fallback and for unmigrated paths.
- Board/now/next still call sebOS directly.
- Active journal prompt and audio journal ingest still call sebOS directly.
- Natural-language intent gate still owns date/defaulting and direct reminder write behavior.
- Natural note/journal/board intent routing still shells through Photon.
- Tests still encode old boundary behavior for unmigrated paths until each path moves.

Next recommended single slice:
- Move board/now/next rendering through the same `hermes-sebos` Photon facade with fallback, preserving exact board/section user-facing output and adding focused delegation/fallback tests.

Blockers or decisions needed from Seb:
- No approval needed for rollback.
- Seb approval is required before the next implementation slice, MCP work, natural-language intent migration, reminder writer Terminal fallback changes, audio journal migration, gateway restart/live smoke, launchd edits, live sends, external mutations, or any push/merge/rebase/stash/commit.

## Unit 4 board/now/next boundary slice update — 2026-06-22

Scope executed:
- Implemented the approved next single slice: moved Photon `board`, `now`, and `next` Mission Control rendering through the existing `hermes-sebos` Photon facade with fallback.
- Preserved existing board body and NOW/NEXT section slicing behavior in Photon.
- Preserved the existing Photon `_run_sebos_json` fallback for plugin-boundary import/unavailability/facade failure.
- No gateway restart, no launchd edit, no live iMessage/Photon send, no Reminders/Notes/Close/Monarch/Telegram/Calendar/WHOOP/finance mutation, no sebOS repo edit, and no push/merge/rebase/stash/commit.

Docs/context read:
- `hermes-boundary-migration` skill.
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md` Unit 3 update.
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`.
- Relevant Photon adapter and Photon test sections.

State verification before edits:
- Hermes repo branch: `clean-stock`; existing dirty worktree preserved.
- sebOS repo branch: `main`; existing dirty worktree preserved and not edited in Unit 4.
- Unit 1 workspace and archive verified present:
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z`
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z.tar.gz`

Files changed by Unit 4:
- Updated `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py` with `render_mission_control(...)`.
- Updated `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py` with `_render_mission_control(...)` facade/fallback helper.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_rules.py` with board delegation and NEXT fallback coverage.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_photon_boundary.py` with `render_mission_control` CLI-contract coverage.
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`.

Behavior migrated:
- `board`, `now`, and `next` still short-circuit inside `_handle_sebos_rules`, but `_mission_control_text()` now calls `_render_mission_control()`.
- `_render_mission_control()` tries `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py::render_mission_control(dry_run=True, timeout=25.0)` first.
- If the plugin boundary is unavailable or raises, Photon falls back to the old `_run_sebos_json("sebos-render-mission-control", "--dry-run", "--json", timeout=25.0)` path.
- Board sends the same full body, and NOW/NEXT continue using existing `_section_from_board(...)` slicing.

Tests run and results:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py -q -o 'addopts='
# 36 passed in 1.52s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.07s

cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 33 passed in 1.49s

cd /Users/clawdolf/.hermes/hermes-agent
python -m py_compile plugins/platforms/photon/adapter.py /Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py
# passed
```

Static verification run:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
rg -n "sebos-render-mission-control|sebos-route-command|sebos-add-reminder|sebos-journal-pending-prompt|sebos-ingest-journal|_run_sebos_json|photon_boundary|render_mission_control" plugins/platforms/photon/adapter.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py /Users/clawdolf/.hermes/plugins/hermes-sebos
```
Result summary:
- Plugin facade now owns direct `sebos-render-mission-control` CLI construction for the migrated board/now/next path.
- Photon adapter still contains `_run_sebos_json` and direct sebOS CLI calls for fallback plus unmigrated paths: active journal prompt, audio journal ingest, natural reminder writer, and natural note/journal/board intent routing.
- Focused tests now prove board facade delegation and Mission Control fallback parity.

Rollback notes:
- Revert Unit 4 changes to `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`.
- Revert Unit 4 changes to `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py`.
- Revert Unit 4 additions in `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_rules.py` and `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_photon_boundary.py`.
- Existing Photon `_run_sebos_json` fallback remains, so runtime rollback is low-risk.

Remaining Photon/sebOS boundary debt:
- `_run_sebos_json` remains in Photon as fallback and for unmigrated paths.
- Active journal prompt and audio journal ingest still call sebOS directly.
- Natural-language intent gate still owns date/defaulting and direct reminder write behavior.
- Natural note/journal/board intent routing still shells through Photon.
- Tests still encode old boundary behavior for unmigrated paths until each path moves.

Next recommended single slice:
- Move active journal prompt probing through the same `hermes-sebos` Photon facade with fallback, preserving audio journal fall-through behavior and adding focused delegation/fallback tests. Do not move audio ingest yet.

Blockers or decisions needed from Seb:
- No approval needed for rollback.
- Seb approval is required before the next implementation slice, MCP work, natural-language intent migration, reminder writer Terminal fallback changes, audio journal ingest migration, gateway restart/live smoke, launchd edits, live sends, external mutations, or any push/merge/rebase/stash/commit.

## Unit 5 active journal prompt boundary slice update — 2026-06-22

Scope executed:
- Implemented the approved next single slice: moved Photon active journal prompt probing through the existing `hermes-sebos` Photon facade with fallback.
- Preserved audio journal ingest behavior and fall-through behavior. This slice did not move audio ingest.
- Preserved the existing Photon `_run_sebos_json` fallback for plugin-boundary import/unavailability/facade failure.
- No gateway restart, no launchd edit, no live iMessage/Photon send, no Reminders/Notes/Close/Monarch/Telegram/Calendar/WHOOP/finance mutation, no sebOS repo edit, and no push/merge/rebase/stash/commit.

Docs/context read:
- `hermes-boundary-migration` skill and Unit 3 facade reference.
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md` Unit 4 update.
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`.
- Relevant Photon adapter and Photon test sections.

State verification before edits:
- Hermes repo branch: `clean-stock`; existing dirty worktree preserved.
- sebOS repo branch: `main`; existing dirty worktree preserved and not edited in Unit 5.
- Unit 1 workspace and archive verified present:
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z`
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z.tar.gz`

Files changed by Unit 5:
- Updated `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py` with `active_journal_prompt_date(...)`.
- Updated `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py` with `_active_journal_prompt_result(...)` facade/fallback helper.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_intent_gate.py` with active journal prompt delegation and fallback coverage.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_photon_boundary.py` with `active_journal_prompt_date` CLI-contract coverage.
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`.

Behavior migrated:
- `_active_journal_prompt_date(message_dt)` now calls `_active_journal_prompt_result(message_dt)`.
- `_active_journal_prompt_result(...)` tries `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py::active_journal_prompt_date(at, db_path=str(_SEBOS_DB_PATH), timeout=20.0)` first.
- If the plugin boundary is unavailable or raises, Photon falls back to the old `_run_sebos_json("sebos-journal-pending-prompt", "--at", at, "--db", str(_SEBOS_DB_PATH), "--json")` path.
- `_try_ingest_audio_journal_reply(...)` still only consumes the returned date/no-date value; audio ingest itself remains unchanged.

Tests run and results:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py -q -o 'addopts='
# 38 passed in 1.63s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.07s

cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 34 passed in 1.44s

cd /Users/clawdolf/.hermes/hermes-agent
python -m py_compile plugins/platforms/photon/adapter.py /Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py tests/plugins/platforms/photon/test_intent_gate.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py
# passed
```

Static verification run:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
rg -n "sebos-render-mission-control|sebos-route-command|sebos-add-reminder|sebos-journal-pending-prompt|sebos-ingest-journal|_run_sebos_json|photon_boundary|render_mission_control|active_journal_prompt_date" plugins/platforms/photon/adapter.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py /Users/clawdolf/.hermes/plugins/hermes-sebos
```
Result summary:
- Plugin facade now owns direct `sebos-journal-pending-prompt` CLI construction for the migrated active prompt probe path.
- Photon adapter still contains `_run_sebos_json` and direct sebOS CLI calls for fallback plus unmigrated paths: audio journal ingest, natural reminder writer, and natural note/journal/board intent routing.
- Focused tests now prove active journal prompt facade delegation and old-runner fallback parity.

Rollback notes:
- Revert Unit 5 changes to `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`.
- Revert Unit 5 changes to `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py`.
- Revert Unit 5 additions in `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_intent_gate.py` and `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_photon_boundary.py`.
- Existing Photon `_run_sebos_json` fallback remains, so runtime rollback is low-risk.

Remaining Photon/sebOS boundary debt:
- `_run_sebos_json` remains in Photon as fallback and for unmigrated paths.
- Audio journal ingest still calls sebOS directly.
- Natural-language intent gate still owns date/defaulting and direct reminder write behavior.
- Natural note/journal/board intent routing still shells through Photon.
- Tests still encode old boundary behavior for unmigrated paths until each path moves.

Next recommended single slice:
- Move natural note/journal/board intent routing through the existing `route_text_command` facade with fallback, preserving the existing `dry_run/no_appender_wired` fall-through behavior. Do not move natural reminder writes or audio ingest yet.

Blockers or decisions needed from Seb:
- No approval needed for rollback.
- Seb approval is required before the next implementation slice, MCP work, natural-language reminder migration, reminder writer Terminal fallback changes, audio journal ingest migration, gateway restart/live smoke, launchd edits, live sends, external mutations, or any push/merge/rebase/stash/commit.

## Unit 6 natural note/journal/board route boundary slice update — 2026-06-22

Scope executed:
- Implemented the approved next single slice: moved natural non-reminder intent routing (`note`, `journal`, `board`, `now`) through the existing `route_text_command` facade helper with fallback.
- Preserved natural reminder write behavior; reminders still use `sebos-add-reminder` directly in Photon and were not migrated.
- Preserved the existing `dry_run/no_appender_wired` fall-through behavior for natural notes.
- No gateway restart, no launchd edit, no live iMessage/Photon send, no Reminders/Notes/Close/Monarch/Telegram/Calendar/WHOOP/finance mutation, no sebOS repo edit, and no push/merge/rebase/stash/commit.

Docs/context read:
- `hermes-boundary-migration` Unit 3 facade reference.
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md` Unit 5 update.
- Relevant Photon adapter and Photon intent-gate tests.

State verification before edits:
- Hermes repo branch: `clean-stock`; existing dirty worktree preserved.
- sebOS repo branch: `main`; existing dirty worktree preserved and not edited in Unit 6.
- Unit 1 workspace and archive verified present:
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z`
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z.tar.gz`

Files changed by Unit 6:
- Updated `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py` so the non-reminder `_try_intent_gate(...)` branch calls `_route_explicit_sebos_command(routed_text)` instead of direct `_run_sebos_json("sebos-route-command", ...)`.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_intent_gate.py` with facade delegation and fallback/no-appender fall-through coverage for natural notes.
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`.

Behavior migrated:
- Natural note/journal/board/now intents still use `_intent_to_sebos_text(...)` to preserve text normalization.
- The resulting routed text now flows through `_route_explicit_sebos_command(...)`, which tries `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py::route_text_command(...)` first.
- If the plugin boundary is unavailable or raises, Photon falls back to the old `_run_sebos_json("sebos-route-command", "--text", "-", "--write", "--db", str(_SEBOS_DB_PATH), "--json", stdin=routed_text, timeout=45.0)` path.
- `kind == "note"` with `status == "dry_run"` and `details.reason == "no_appender_wired"` still returns `None` so the message can fall through.

Tests run and results:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py -q -o 'addopts='
# 40 passed in 1.68s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.07s

cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 36 passed in 1.50s

cd /Users/clawdolf/.hermes/hermes-agent
python -m py_compile plugins/platforms/photon/adapter.py /Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py tests/plugins/platforms/photon/test_intent_gate.py
# passed
```

Static verification run:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
rg -n "sebos-render-mission-control|sebos-route-command|sebos-add-reminder|sebos-journal-pending-prompt|sebos-ingest-journal|_run_sebos_json|photon_boundary|render_mission_control|active_journal_prompt_date|_route_explicit_sebos_command" plugins/platforms/photon/adapter.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py /Users/clawdolf/.hermes/plugins/hermes-sebos
```
Result summary:
- Natural non-reminder intent route now shares `_route_explicit_sebos_command(...)` with explicit sebOS commands.
- Plugin facade still owns direct `sebos-route-command`, `sebos-render-mission-control`, and `sebos-journal-pending-prompt` CLI construction for migrated paths.
- Photon adapter still contains `_run_sebos_json` and direct sebOS CLI calls for fallback plus unmigrated paths: audio journal ingest and natural reminder writer.

Rollback notes:
- Revert Unit 6 changes to `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py`.
- Revert Unit 6 additions in `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_intent_gate.py`.
- Existing Photon `_run_sebos_json` fallback remains, so runtime rollback is low-risk.

Remaining Photon/sebOS boundary debt:
- `_run_sebos_json` remains in Photon as fallback and for unmigrated paths.
- Audio journal ingest still calls sebOS directly.
- Natural-language reminder writer still owns date/defaulting and direct `sebos-add-reminder` behavior in Photon.
- Tests still encode old boundary behavior for unmigrated reminder/audio paths until each path moves.

Next recommended single slice:
- Move natural reminder writer execution through the facade with fallback while preserving all date/defaulting semantics in Photon for now. Do not change reminder writer Terminal fallback, date parsing, or audio ingest.

Blockers or decisions needed from Seb:
- No approval needed for rollback.
- Seb approval is required before the next implementation slice, MCP work, reminder writer Terminal fallback changes, audio journal ingest migration, gateway restart/live smoke, launchd edits, live sends, external mutations, or any push/merge/rebase/stash/commit.

## Unit 7 natural reminder writer boundary slice update — 2026-06-22

Scope executed:
- Implemented the approved next single slice: moved natural reminder writer execution through the existing `hermes-sebos` Photon facade with fallback.
- Preserved all current Photon date/defaulting/location parsing semantics.
- Did not change sebOS reminder writer behavior, Terminal fallback behavior, audio journal ingest, gateway, launchd, live config, or live sends.
- No gateway restart, no launchd edit, no live iMessage/Photon send, no Reminders/Notes/Close/Monarch/Telegram/Calendar/WHOOP/finance mutation, no sebOS repo edit, and no push/merge/rebase/stash/commit.

Docs/context read:
- `hermes-boundary-migration` Unit 3 facade reference.
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md` Unit 6 update.
- Relevant Photon adapter and Photon intent-gate tests.

State verification before edits:
- Hermes repo branch: `clean-stock`; existing dirty worktree preserved.
- sebOS repo branch: `main`; existing dirty worktree preserved and not edited in Unit 7.
- Unit 1 workspace and archive verified present:
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z`
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z.tar.gz`

Files changed by Unit 7:
- Updated `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py` with `add_reminder(...)`.
- Updated `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py` with `_intent_reminder_payload(...)`, `_add_reminder(...)`, and `_reminder_payload_args(...)`; natural reminder intent now uses `_add_reminder(...)`.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_intent_gate.py` with natural reminder facade delegation and fallback coverage.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_rules.py` to keep tests hermetic by defaulting the plugin boundary loader to unavailable unless explicitly overridden.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_photon_boundary.py` with `add_reminder` CLI-contract coverage.
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`.

Behavior migrated:
- Natural reminder intent still computes title/due/location/proximity fields inside Photon exactly as before.
- `_try_intent_gate(...)` now turns those fields into a reminder payload and calls `_add_reminder(payload)`.
- `_add_reminder(...)` tries `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py::add_reminder(...)` first.
- If the plugin boundary is unavailable or raises, Photon falls back to the old `_run_sebos_json("sebos-add-reminder", ..., timeout=45.0)` behavior via `_reminder_payload_args(...)`.
- Reminder success/failure reply and tapback behavior remains unchanged.

Tests run and results:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py -q -o 'addopts='
# first run: 2 failed, 41 passed because live plugin boundary was no longer default-mocked in test_sebos_rules.py; fixed tests to keep boundary unavailable unless explicitly overridden.
# final: 43 passed in 1.80s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.07s

cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 38 passed in 1.57s

cd /Users/clawdolf/.hermes/hermes-agent
python -m py_compile plugins/platforms/photon/adapter.py /Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py tests/plugins/platforms/photon/test_intent_gate.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py
# passed
```

Static verification run:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
rg -n "sebos-render-mission-control|sebos-route-command|sebos-add-reminder|sebos-journal-pending-prompt|sebos-ingest-journal|_run_sebos_json|photon_boundary|render_mission_control|active_journal_prompt_date|add_reminder|_add_reminder|_route_explicit_sebos_command" plugins/platforms/photon/adapter.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py /Users/clawdolf/.hermes/plugins/hermes-sebos
```
Result summary:
- Plugin facade now owns direct `sebos-add-reminder` CLI construction for natural reminder writer execution.
- Photon adapter still contains `_run_sebos_json` for fallback plus the unmigrated audio journal ingest path.
- Natural reminder date/defaulting remains in Photon by design for this slice.

Rollback notes:
- Revert Unit 7 changes to `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`.
- Revert Unit 7 changes to `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py`.
- Revert Unit 7 additions in `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_intent_gate.py`, `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_rules.py`, and `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_photon_boundary.py`.
- Existing Photon `_run_sebos_json` fallback remains, so runtime rollback is low-risk.

Remaining Photon/sebOS boundary debt:
- `_run_sebos_json` remains in Photon as fallback and for unmigrated audio path.
- Audio journal ingest still calls sebOS directly.
- Photon still owns natural reminder date/defaulting semantics; this was intentionally preserved for Unit 7.
- Tests still encode old boundary behavior for the unmigrated audio path until it moves.

Next recommended single slice:
- Move audio journal ingest execution through the facade with fallback, while keeping Photon responsible only for transport-side attachment detection, cache recovery, inbox file retention, and tapback/send mechanics. Do not change transcription or sebOS journal semantics.

Blockers or decisions needed from Seb:
- No approval needed for rollback.
- Seb approval is required before audio journal ingest migration, MCP work, reminder writer Terminal fallback changes, gateway restart/live smoke, launchd edits, live sends, external mutations, or any push/merge/rebase/stash/commit.

## Unit 8 audio journal ingest boundary slice update — 2026-06-22

Scope executed:
- Implemented the approved final Photon/sebOS subprocess slice: moved audio journal ingest execution through the existing `hermes-sebos` Photon facade with fallback.
- Kept Photon responsible for transport-side attachment detection, marker-only cache recovery, audio MIME normalization, copying/retaining the attachment into sebOS inbox, payload JSON creation/deletion, tapback, and quiet-send mechanics.
- Did not change transcription behavior, sebOS journal semantics, active prompt probing, reminder writer behavior, gateway, launchd, live config, or live sends.
- No gateway restart, no launchd edit, no live iMessage/Photon send, no Reminders/Notes/Close/Monarch/Telegram/Calendar/WHOOP/finance mutation, no sebOS repo edit, and no push/merge/rebase/stash/commit.

Docs/context read:
- `hermes-boundary-migration` Unit 3 facade reference.
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md` Unit 7 update.
- Relevant Photon adapter and Photon intent-gate tests.

State verification before edits:
- Hermes repo branch: `clean-stock`; existing dirty worktree preserved.
- sebOS repo branch: `main`; existing dirty worktree preserved and not edited in Unit 8.
- Unit 1 workspace and archive verified present:
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z`
  - `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z.tar.gz`

Files changed by Unit 8:
- Updated `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py` with `ingest_journal(...)`.
- Updated `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py` with `_ingest_journal_payload(...)`; audio journal ingest now uses that helper.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_intent_gate.py` with audio ingest facade delegation and fallback coverage.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_photon_boundary.py` with `ingest_journal` CLI-contract coverage.
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`.

Behavior migrated:
- `_try_ingest_audio_journal_reply(...)` still builds the exact same Photon-side JSON payload file in the sebOS audio inbox.
- Instead of calling `_run_sebos_json("sebos-ingest-journal", ...)` directly, Photon now calls `_ingest_journal_payload(tmp_name, sender_id=sender_id)`.
- `_ingest_journal_payload(...)` tries `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py::ingest_journal(...)` first.
- If the plugin boundary is unavailable or raises, Photon falls back to old `_run_sebos_json("sebos-ingest-journal", tmp_name, "--source", "photon", "--sender", sender_id, timeout=360.0)` behavior.
- Audio success/failure reply and tapback behavior remains unchanged.

Tests run and results:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py -q -o 'addopts='
# 46 passed in 1.88s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.07s

cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 40 passed in 1.64s

cd /Users/clawdolf/.hermes/hermes-agent
python -m py_compile plugins/platforms/photon/adapter.py /Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py tests/plugins/platforms/photon/test_intent_gate.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py
# passed
```

Static verification run:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
rg -n "sebos-render-mission-control|sebos-route-command|sebos-add-reminder|sebos-journal-pending-prompt|sebos-ingest-journal|_run_sebos_json|photon_boundary|render_mission_control|active_journal_prompt_date|add_reminder|ingest_journal|_ingest_journal_payload|_route_explicit_sebos_command" plugins/platforms/photon/adapter.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py /Users/clawdolf/.hermes/plugins/hermes-sebos
```
Result summary:
- `hermes-sebos` facade now owns CLI construction for Photon sebOS route command, board render, active journal prompt probe, reminder writer, and journal ingest.
- Photon adapter still contains `_run_sebos_json` only as fallback and local subprocess compatibility layer.
- Static grep hits are expected for fallback code and tests.

Rollback notes:
- Revert Unit 8 changes to `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`.
- Revert Unit 8 changes to `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py`.
- Revert Unit 8 additions in `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_intent_gate.py` and `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_photon_boundary.py`.
- Existing Photon `_run_sebos_json` fallback remains, so runtime rollback is low-risk.

Remaining Photon/sebOS boundary debt:
- `_run_sebos_json` remains in Photon as fallback until Seb approves removing or narrowing it.
- Photon still owns natural reminder date/defaulting semantics, audio attachment detection, audio payload composition, inbox retention, tapback/send behavior, and all iMessage transport concerns by design.
- `hermes-sebos` facade is file-loaded from the user plugin path and not registered as a live tool.

Next recommended single slice:
- Stop here for implementation. Run a review/audit slice next: inspect all Photon -> sebOS subprocess usage, confirm only fallback paths remain, then decide whether to remove/narrow `_run_sebos_json` or leave it as rollback guard.

Blockers or decisions needed from Seb:
- No approval needed for rollback.
- Seb approval is required before any fallback removal, MCP work, gateway restart/live smoke, launchd edits, live sends, external mutations, or any push/merge/rebase/stash/commit.

## Unit 9 Photon/sebOS subprocess audit — 2026-06-22

Scope executed:
- Ran the approved review/audit slice only. No implementation behavior change was made.
- Inspected Photon adapter, `hermes-sebos` Photon facade, and focused Photon tests for direct sebOS subprocess usage.
- Confirmed all Photon-to-sebOS CLI invocations are now facade-first with old `_run_sebos_json` fallback, or in plugin-owned `photon_boundary.py`.
- Did not remove/narrow fallback, restart gateway, edit launchd/live config, send live messages, mutate Apple data, edit sebOS repo, or push/merge/rebase/stash/commit.

Docs/context read:
- `hermes-boundary-migration` Unit 3 facade reference.
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md` Unit 8 update.
- Relevant Photon adapter sidecar/subprocess section for non-sebOS subprocess classification.

State verification before audit:
- Hermes repo branch: `clean-stock`; existing dirty worktree preserved.
- sebOS repo branch: `main`; existing dirty worktree preserved and not edited in Unit 9.

Audit commands run:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python - <<'PY'
# AST scan for calls to _run_sebos_json and facade helper methods in Photon adapter
PY

cd /Users/clawdolf/.hermes/hermes-agent
rg -n "create_subprocess_exec|subprocess\.|_run_sebos_json\(|sebos-[a-z-]+|_load_sebos_photon_boundary|photon_boundary" plugins/platforms/photon/adapter.py /Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py
```

Audit result:
- `plugins/platforms/photon/adapter.py::_route_explicit_sebos_command` calls plugin `route_text_command(...)`; fallback calls `_run_sebos_json("sebos-route-command", ...)`.
- `plugins/platforms/photon/adapter.py::_render_mission_control` calls plugin `render_mission_control(...)`; fallback calls `_run_sebos_json("sebos-render-mission-control", ...)`.
- `plugins/platforms/photon/adapter.py::_active_journal_prompt_result` calls plugin `active_journal_prompt_date(...)`; fallback calls `_run_sebos_json("sebos-journal-pending-prompt", ...)`.
- `plugins/platforms/photon/adapter.py::_add_reminder` calls plugin `add_reminder(...)`; fallback calls `_run_sebos_json(*_reminder_payload_args(...))` for `sebos-add-reminder`.
- `plugins/platforms/photon/adapter.py::_ingest_journal_payload` calls plugin `ingest_journal(...)`; fallback calls `_run_sebos_json("sebos-ingest-journal", ...)`.
- No other Photon adapter calls to `_run_sebos_json(...)` were found.
- `photon_boundary.py` is the only direct `asyncio.create_subprocess_exec(...)` sebOS owner in the plugin facade, and constructs all five sebOS CLIs listed above.
- Other `subprocess.run/Popen` hits in Photon adapter are Photon sidecar lifecycle/port/Spectrum patch operations (`lsof`, `ps`, Node sidecar), not sebOS calls and not part of the sebOS boundary debt.

Tests run and results:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py -q -o 'addopts='
# 46 passed in 1.87s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.07s
```

Files changed by Unit 9:
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md` only.

Decision recommendation:
- Leave `_run_sebos_json` in Photon for now as the explicit rollback/fallback guard.
- If Seb wants another slice, narrow `_run_sebos_json` to a private fallback-only method with an allowlist of the five migrated sebOS commands, rather than deleting it outright.

Remaining Photon/sebOS boundary debt:
- Runtime fallback path remains in Photon by design.
- Photon still owns transport semantics: iMessage parsing, audio cache recovery, attachment/payload composition, tapback/send behavior, and natural reminder date/defaulting.
- `hermes-sebos` facade remains file-loaded from the user plugin path and not registered as a live tool.

Next recommended single slice:
- If approved, narrow `_run_sebos_json` into a guarded fallback helper with a five-command allowlist and tests that prevent new arbitrary sebOS subprocess calls from being added to Photon.

Blockers or decisions needed from Seb:
- No approval needed for rollback.
- Seb approval is required before fallback narrowing/removal, MCP work, gateway restart/live smoke, launchd edits, live sends, external mutations, or any push/merge/rebase/stash/commit.

## Unit 10 fallback allowlist narrowing — 2026-06-22

Scope executed:
- Implemented the approved fallback narrowing slice.
- Added a five-command allowlist to Photon `_run_sebos_json(...)` so fallback can only execute the migrated sebOS CLI commands.
- Added tests that lock the allowlist and fail if new literal sebOS fallback calls are added outside the allowlist.
- Did not remove fallback, restart gateway, edit launchd/live config, send live messages, mutate Apple data, edit sebOS repo, or push/merge/rebase/stash/commit.

State verification before edits:
- Hermes repo branch: `clean-stock`; existing dirty worktree preserved.
- sebOS repo branch: `main`; existing dirty worktree preserved and not edited in Unit 10.
- Baseline before edits passed:
  - Hermes plugin-inclusive focused run: `46 passed in 1.93s`.
  - sebOS router: `46 passed in 0.07s`.

Files changed by Unit 10:
- Updated `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py` with `_SEBOS_FALLBACK_COMMAND_ALLOWLIST` and `_run_sebos_json(...)` rejection for non-allowlisted commands.
- Updated `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_rules.py` with allowlist exactness, rejection, and static literal-call coverage.
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`.

Allowlisted fallback commands:
- `sebos-route-command`
- `sebos-render-mission-control`
- `sebos-journal-pending-prompt`
- `sebos-add-reminder`
- `sebos-ingest-journal`

Behavior changed:
- `_run_sebos_json(...)` now returns a structured error for missing command args:
  - `status=error`, `error_layer=router`, `error=missing sebOS command`, `returncode=127`.
- `_run_sebos_json(...)` now rejects non-allowlisted commands before resolving an executable:
  - `status=error`, `error_layer=router`, `error=sebOS fallback command not allowed`, `returncode=126`.
- Existing facade fallback behavior for the five migrated commands is preserved.

Tests run and results:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py -q -o 'addopts='
# 49 passed in 1.98s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.07s

cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 43 passed in 1.76s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.06s

cd /Users/clawdolf/.hermes/hermes-agent
python -m py_compile plugins/platforms/photon/adapter.py /Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py tests/plugins/platforms/photon/test_intent_gate.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py
# passed
```

Static verification run:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
rg -n "_SEBOS_FALLBACK_COMMAND_ALLOWLIST|sebOS fallback command not allowed|_run_sebos_json\(|sebos-route-command|sebos-render-mission-control|sebos-journal-pending-prompt|sebos-add-reminder|sebos-ingest-journal|sebos-[a-z-]+" plugins/platforms/photon/adapter.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py /Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py
```
Result summary:
- Static grep shows only the five allowed sebOS commands in Photon fallback code/tests and plugin facade contract tests.
- `sebos-dangerous-new-command` appears only in the rejection test.

Rollback notes:
- Revert Unit 10 changes to `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py` and `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_rules.py`.
- Existing plugin facade helpers remain independent of this allowlist slice.

Remaining Photon/sebOS boundary debt:
- `_run_sebos_json(...)` remains in Photon as a guarded rollback/fallback path.
- Photon still owns transport semantics by design: iMessage parsing, audio cache recovery, attachment/payload composition, tapback/send behavior, and natural reminder date/defaulting.
- `hermes-sebos` facade remains file-loaded from the user plugin path and not registered as a live tool.

Next recommended single slice:
- Stop implementation here. Next should be packaging/review only: prepare a concise commit/PR-sized diff summary and decide whether to commit the boundary migration as one unit or split by migration slice.

Blockers or decisions needed from Seb:
- No approval needed for rollback.
- Seb approval is required before commits, pushes, PRs, fallback removal, MCP work, gateway restart/live smoke, launchd edits, live sends, external mutations, or any destructive cleanup.

## Unit 11 packaging / commit plan — 2026-06-22

Scope executed:
- Ran the approved packaging/review slice only.
- Prepared a commit/PR-sized summary and split recommendation.
- Did not commit, push, open a PR, restart gateway, edit launchd/live config, send live messages, mutate Apple data, edit sebOS repo, or run destructive cleanup.

State verification:
- Hermes repo branch: `clean-stock`.
- sebOS repo branch: `main`.
- Hermes worktree has broad existing migration changes beyond the Photon/sebOS slice; packaging must avoid accidental unrelated commits.
- `hermes-sebos` facade file is outside the Hermes repo at `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`, size 5250 bytes.

Focused boundary files for this package:
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py` (external user plugin file, not tracked by Hermes repo).
- `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py` (`274 insertions, 101 deletions` in current repo diff).
- `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_rules.py` (`169 insertions, 3 deletions` in current repo diff).
- `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_intent_gate.py` (`408 insertions, 0 deletions` in current repo diff).
- `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_photon_boundary.py` (untracked new test file).
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md` (untracked migration log).

Verification run during packaging:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py -q -o 'addopts='
# 49 passed in 1.96s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.06s
```

Recommended commit strategy:
- Do not commit the entire dirty worktree as one blob. There are broad unrelated boundary/migration changes already present, and the `hermes-sebos` facade lives outside the Hermes repo.
- Package this Photon/sebOS boundary migration as a dedicated commit/PR slice containing only:
  - Photon adapter facade-first routing and allowlisted fallback guard.
  - Focused Photon tests and plugin-boundary tests.
  - Migration handoff docs if the repo should retain migration evidence.
- Treat `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py` separately because it is a user plugin artifact outside the Hermes repo. If this needs version control, copy it into an explicit repo-owned plugin fixture/location in a separate approved packaging step rather than silently adding external profile state.

Suggested commit title if committed later:
- `refactor(photon): route sebOS calls through hermes-sebos facade`

Suggested PR summary:
- Adds a plugin-owned `hermes-sebos` Photon facade for sebOS CLI execution.
- Routes Photon explicit commands, board/now/next, active journal prompt probing, natural note/journal/board routing, natural reminder writer, and audio journal ingest through the facade first.
- Preserves old Photon `_run_sebos_json` behavior as fallback, then narrows fallback with a five-command allowlist.
- Adds hermetic tests for facade delegation, fallback parity, allowlist enforcement, and plugin CLI contracts.
- Leaves Photon-owned transport responsibilities intact: iMessage parsing, audio attachment/cache handling, payload creation/deletion, tapbacks, quiet replies, and reminder date/defaulting.

Suggested PR test block:
```bash
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py tests/plugins/platforms/photon/test_sebos_photon_boundary.py -q -o 'addopts='
# 49 passed

cd /Users/clawdolf/.hermes/sebos && python3 -m pytest tests/test_command_router.py -q
# 46 passed
```

Remaining packaging decision:
- Seb needs to choose whether to preserve `MIGRATION_HANDOFF.md` and the boundary design docs in the repo commit, or keep them as local migration artifacts only.
- If committing, stage paths explicitly. Do not use `git add -A` from the dirty Hermes repo.

Blockers or decisions needed from Seb:
- Approval required before any commit/push/PR.
- Decision needed: include migration docs/handoff in repo, or keep docs local and commit only code/tests.

## Unit 12 hermes-sebos plugin packaging / durability — 2026-06-21 20:56 MDT

Scope executed:
- Ran the approved plugin packaging/durability-only unit.
- Did not de-domain more Photon behavior.
- Did not restart gateway, edit launchd, send iMessages/live Photon messages, mutate Reminders/Notes/Close/Monarch/Telegram/Apple data, push, merge, rebase, or force-push.

Docs read:
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_PLAN.md`
- `/Users/clawdolf/.hermes/hermes-agent/BOUNDARY_RULES.md`
- `/Users/clawdolf/.hermes/hermes-agent/UNIT2_BOUNDARY_DESIGN.md`
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/plugin.yaml`
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/tools.py`
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`
- Hermes plugin docs: local `website/docs/user-guide/features/plugins.md` and live `https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins`.

State verification:
- Hermes repo is a git repo on `clean-stock`; it still has broad existing dirty migration work unrelated to this plugin packaging unit.
- sebOS repo is a git repo on `main`; it still has existing dirty sebOS migration work unrelated to this plugin packaging unit.
- `/Users/clawdolf/.hermes/plugins/hermes-sebos` was not a git repo before this unit.

Tracking/package option chosen:
- Initialized `/Users/clawdolf/.hermes/plugins/hermes-sebos` as its own local git repository.
- Reason: Hermes docs define user plugins as directories under `~/.hermes/plugins/`; keeping the plugin in place makes the live adapter dependency durable without moving live files, changing Hermes core/config, or depending on project-local plugin enablement.
- Did not move files into Hermes core because official docs support user plugins at the existing path and moving would expand live/runtime scope.
- Did not only snapshot into the Unit 1 export because that would preserve an artifact but leave the live plugin file untracked.

Plugin package now includes:
- `.gitignore`
- `README.md`
- `__init__.py`
- `plugin.yaml`
- `tools.py`
- `photon_boundary.py`

Files changed in plugin repo:
- Added `/Users/clawdolf/.hermes/plugins/hermes-sebos/.gitignore` to ignore bytecode/cache noise.
- Added `/Users/clawdolf/.hermes/plugins/hermes-sebos/README.md` documenting the plugin package and Photon boundary facade.
- Updated `/Users/clawdolf/.hermes/plugins/hermes-sebos/plugin.yaml` description to mention the Photon-facing sebOS CLI compatibility facade.

Plugin commit created:
```bash
cd /Users/clawdolf/.hermes/plugins/hermes-sebos
git commit -m "package Photon sebOS boundary facade"
# 0df6693 package Photon sebOS boundary facade
```

Verification run:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 43 passed in 1.84s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.07s

cd /Users/clawdolf/.hermes/plugins/hermes-sebos
python -m py_compile __init__.py tools.py photon_boundary.py
# passed
```

Rollback notes:
- To undo only this packaging unit, remove the plugin repo metadata with `rm -rf /Users/clawdolf/.hermes/plugins/hermes-sebos/.git` and revert the README/plugin.yaml/.gitignore changes if desired.
- Do not remove `photon_boundary.py` unless also rolling back the committed Hermes Photon adapter facade changes.
- Existing Photon fallback remains guarded and low-risk if the facade cannot load.

Remaining Photon/sebOS boundary debt:
- Photon still imports the user plugin facade by fixed path and retains guarded fallback `_run_sebos_json(...)` for rollback.
- The plugin facade is local-only, tracked in a local git repo, not pushed to a remote.
- No live gateway/plugin reload was performed, so runtime processes still use whatever code they had already loaded until next normal restart.

Next recommended single slice:
- Review and reconcile the broad existing dirty Hermes/sebOS migration work that remains outside this plugin repo, then decide whether to push/open PRs. No more behavior migration before that cleanup/review pass.

Blockers or decisions needed from Seb:
- No blocker for local durability: the plugin facade is now tracked in its own local git repo.
- Approval required before pushing the plugin repo anywhere, adding a remote, opening PRs, restarting gateway/live smoke, changing core/plugin loading, deleting files, or removing fallback.

## Unit 13 dirty-worktree review / reconcile pass — 2026-06-21 21:01 MDT

Scope executed:
- Ran the approved review/reconcile unit only.
- Verified current git state in Hermes, sebOS, and the local `hermes-sebos` plugin repo.
- Reviewed and categorized existing dirty Hermes/sebOS work without pushing, opening PRs, restarting gateway, editing launchd, sending messages, or touching external systems.
- Made one test-only sebOS reconciliation patch after review exposed failing tests from the existing `remindctl` absolute-path change.

Current repo state:
- Hermes repo: branch `clean-stock`, HEAD `612ddef34 refactor(photon): route sebOS calls through hermes-sebos facade`, dirty worktree remains.
- sebOS repo: branch `main`, HEAD `ac989e6 Generalize coarse IP location in briefs`, dirty worktree remains.
- `hermes-sebos` plugin repo: branch `main`, HEAD `0df6693 package Photon sebOS boundary facade`; clean except ignored `__pycache__/`.

Hermes dirty work categorized:
1. `sebos_event` plugin migration:
   - `tools/sebos_event.py` deleted from core.
   - `hermes_cli/plugins.py`, `tools/registry.py`, `toolsets.py`, `tests/test_toolsets.py`, `tests/tools/test_sebos_event.py` add plugin opt-in wiring so `hermes-sebos` can provide `sebos_event` across messaging/core-family toolsets.
   - Recommendation: package as a dedicated commit after explicit review, because this is core/toolset behavior and broader than Photon boundary work.
2. Athena goals injection:
   - `agent/agent_init.py`, `agent/prompt_builder.py`, `agent/system_prompt.py`, `tests/agent/test_prompt_builder.py`, `tests/agent/test_system_prompt.py` inject compact sebOS `athena_goals.json` into prompt context.
   - Recommendation: package as its own local-Athena feature commit, not mixed with plugin migration.
3. Generic platform capability hooks / Photon inbox hygiene:
   - `gateway/platform_registry.py`, `gateway/run.py`, `gateway/outbound_sanitize.py`, `tests/gateway/test_platform_capabilities.py`, `tests/gateway/test_telegram_noise_filter.py` move clean-inbox and outbound sanitizer behavior into `PlatformEntry` capabilities.
   - Recommendation: package separately as an upstreamable generic gateway extension point, then keep Photon-specific usage in platform plugin code.
4. Session/platform cleanup and Photon guard fixes:
   - `gateway/session.py`, `tests/gateway/test_session.py`, `tests/plugins/platforms/photon/test_shared_cloud_guard.py` remove stale iMessage prompt leakage and update shared-cloud auth expectation to Basic auth.
   - Recommendation: split into small bugfix commits, not mixed with migration infrastructure.
5. Migration docs:
   - `MIGRATION_HANDOFF.md` updated by Units 12 and 13.
   - Recommendation: either keep local-only or commit as migration evidence in a docs-only commit. Do not bury it inside runtime code commits.

sebOS dirty work categorized:
1. Command-router behavior additions:
   - `lib/command_router.py`, `tests/test_command_router.py`, and untracked `bin/sebos-journal-pending-prompt` add reminders-read intent, broader `where was I` variants, default note appender, and active journal prompt CLI.
   - Recommendation: split active-journal prompt CLI from reminders-read/default-note behavior. The prompt CLI supports the Photon boundary migration; reminders-read/default-note are live domain behavior and need separate review.
2. Reminders executable path hardening:
   - `lib/reminders.py` uses `shutil.which("remindctl") or "/opt/homebrew/bin/remindctl"` for launchd/Hermes stripped-PATH contexts.
   - `tests/test_reminders.py` was updated in this unit to accept either `remindctl` or an absolute path by checking `Path(args[0]).name`.
   - Recommendation: package as a small sebOS reliability bugfix commit.

Verification run:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/agent/test_prompt_builder.py tests/agent/test_system_prompt.py tests/gateway/test_session.py tests/gateway/test_telegram_noise_filter.py tests/gateway/test_platform_capabilities.py tests/plugins/platforms/photon/test_shared_cloud_guard.py tests/test_toolsets.py tests/tools/test_sebos_event.py tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py -q -o 'addopts='
# 338 passed, 1 skipped in 12.85s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py tests/test_reminders.py -q
# 54 passed in 0.31s

cd /Users/clawdolf/.hermes/sebos
python3 -m py_compile lib/command_router.py lib/reminders.py tests/test_reminders.py bin/sebos-journal-pending-prompt
# passed
```

Reconciliation change made in this unit:
- `/Users/clawdolf/.hermes/sebos/tests/test_reminders.py` now uses a local `_cmd_name(args)` helper so tests remain valid after `lib/reminders.py` switches from bare `remindctl` to an absolute executable path in stripped-PATH contexts.

Recommended commit order:
1. sebOS reliability bugfix: `lib/reminders.py` + `tests/test_reminders.py` only.
2. sebOS active-journal prompt CLI: `bin/sebos-journal-pending-prompt` + focused `command_router`/tests if separable.
3. Hermes generic plugin opt-in toolset support + core `sebos_event` deletion, paired with the already tracked `hermes-sebos` plugin repo commit.
4. Hermes generic platform capability hooks / outbound sanitizer.
5. Athena goals injection.
6. Small gateway/Photon bugfixes.
7. Migration docs commit or local-only handoff decision.

Blockers or decisions needed from Seb:
- No blocker for local tests: reviewed suites are green after the sebOS test reconciliation.
- Approval required before staging/committing any of the above slices, adding remotes, pushing, opening PRs, restarting gateway, live smoke tests, deleting files, or removing fallback.
- Recommended next single unit: package the smallest low-risk sebOS reliability bugfix (`lib/reminders.py` + `tests/test_reminders.py`) as a local commit. It is independent and already verified.

## Unit 14 sebOS reminders reliability commit — 2026-06-21 21:06 MDT

Scope executed:
- Ran the approved smallest low-risk sebOS reliability unit only.
- Staged and committed only `/Users/clawdolf/.hermes/sebos/lib/reminders.py` and `/Users/clawdolf/.hermes/sebos/tests/test_reminders.py`.
- Did not stage command-router changes, `bin/sebos-journal-pending-prompt`, Hermes changes, push, open a PR, restart gateway, edit launchd, send messages, or mutate Apple data.

Behavior packaged:
- `lib/reminders.py` resolves `remindctl` via `shutil.which("remindctl")` and falls back to `/opt/homebrew/bin/remindctl` for stripped-PATH launchd/Hermes contexts.
- `tests/test_reminders.py` asserts the command contract by basename, so either `remindctl` or an absolute executable path remains valid.

Verification run:
```bash
cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_reminders.py -q
# 8 passed in 0.24s

python3 -m pytest tests/test_command_router.py tests/test_reminders.py -q
# 54 passed in 0.31s

python3 -m py_compile lib/reminders.py tests/test_reminders.py
# passed

git diff --cached --check
# passed
```

Commit created:
```bash
cd /Users/clawdolf/.hermes/sebos
git commit -m "fix(reminders): resolve remindctl in stripped PATH contexts"
# 8508131 fix(reminders): resolve remindctl in stripped PATH contexts
```

Remaining sebOS dirty work:
- `lib/command_router.py`
- `tests/test_command_router.py`
- untracked `bin/sebos-journal-pending-prompt`

Next recommended single unit:
- Package active-journal prompt CLI separately if separable: `bin/sebos-journal-pending-prompt` plus only the command-router/test changes required for the Photon active journal prompt boundary. Keep reminders-read/default-note behavior out unless review proves it is inseparable.

Blockers or decisions needed from Seb:
- No blocker for this commit.
- Approval required before staging/committing the remaining sebOS command-router work, pushing, opening PRs, restarting gateway, live smoke tests, deleting files, or changing Apple/Reminders/Notes behavior.

## Unit 15 sebOS active-journal prompt CLI commit — 2026-06-21 21:11 MDT

Scope executed:
- Ran the approved active-journal prompt CLI packaging unit.
- Confirmed the CLI could be separated from unrelated command-router behavior.
- Staged and committed only `/Users/clawdolf/.hermes/sebos/bin/sebos-journal-pending-prompt` and `/Users/clawdolf/.hermes/sebos/tests/test_journal_pending_prompt_cli.py`.
- Did not stage remaining `lib/command_router.py` or `tests/test_command_router.py` changes.
- Did not push, open a PR, restart gateway, edit launchd, send messages, or mutate Apple/Reminders/Notes data.

Behavior packaged:
- Added read-only `sebos-journal-pending-prompt` CLI.
- Given `--at` and optional `--db`, it returns JSON `{"date": "YYYY-MM-DD"}` when an inbound message falls inside the latest journal prompt reply window, otherwise `{"date": null}`.
- Uses delivered_at first, then created_at, with the existing six-hour reply window.
- Invalid timestamp returns structured JSON error and exit code 2.

Verification run:
```bash
cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_journal_pending_prompt_cli.py -q
# 4 passed in 0.37s

python3 -m pytest tests/test_journal_pending_prompt_cli.py tests/test_journal.py -q
# 63 passed in 2.63s

python3 -m py_compile bin/sebos-journal-pending-prompt tests/test_journal_pending_prompt_cli.py
# passed

git diff --cached --check
# passed
```

Commit created:
```bash
cd /Users/clawdolf/.hermes/sebos
git commit -m "feat(journal): add pending prompt CLI"
# cbdadca feat(journal): add pending prompt CLI
```

Remaining sebOS dirty work:
- `lib/command_router.py`
- `tests/test_command_router.py`

Next recommended single unit:
- Review the remaining command-router diff and split it into the smallest safe behavior package. Current candidates are reminders-read intent / broader where-was-I matching and default Apple Notes appender. The default note appender touches live Apple Notes behavior, so I recommend review-only first, then commit only if you explicitly approve that live behavior change.

Blockers or decisions needed from Seb:
- No blocker for the active-journal prompt CLI commit.
- Approval required before staging/committing remaining command-router behavior, especially any default Apple Notes write path, pushing, opening PRs, restarting gateway, live smoke tests, deleting files, or changing Apple/Reminders/Notes behavior.

## Unit 16 remaining sebOS command-router review — 2026-06-21 21:13 MDT

Scope executed:
- Ran review-only on the remaining sebOS dirty diff.
- Did not edit, stage, commit, push, restart gateway, send messages, or touch Apple/Reminders/Notes data.

Remaining dirty files reviewed:
- `/Users/clawdolf/.hermes/sebos/lib/command_router.py`
- `/Users/clawdolf/.hermes/sebos/tests/test_command_router.py`

Diff clusters found:
1. Safer/read-only command intent cluster:
   - Adds casual-prefix stripping (`hey`, `hi`, `yo`, `ok`, `okay`, `athena`) before command classification.
   - Broadens `where was/am I` variants to include `where am I on my tasks` and `what am I doing`.
   - Adds read-only `INTENT_REMINDERS_READ` and a handler for reminder summary reads.
   - Uses `reminders.run_remindctl(...)` and degrades to empty unavailable sections on errors.
   - Tests cover reminder-read classification and read-only routing with injected `reminder_reader`.
   - Risk: low to moderate. It is read-only but does expand command recognition, which can intercept phrases that might previously fall through to Athena/Hermes.
2. Live Apple Notes write cluster:
   - Adds `_default_note_appender(...)` with AppleScript writes into Mission Control Apple Notes and sebOS event tracking.
   - Changes note routing with no injected appender from staged dry-run to live write when `write_enabled=True`.
   - Tests mock `_default_note_appender`, so they do not exercise real Apple Notes.
   - Risk: high. This changes live Apple Notes behavior and should not be bundled with the read-only command improvements.
3. Shared signature/plumbing cluster:
   - Adds optional `reminder_reader` through `_dispatch`, `route_text`, and `route_audio_transcript`.
   - This belongs with the reminders-read cluster.

Verification run:
```bash
cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.08s

python3 -m pytest tests/test_command_router.py tests/test_reminders.py tests/test_journal_pending_prompt_cli.py -q
# 58 passed in 0.66s

python3 -m py_compile lib/command_router.py tests/test_command_router.py
# passed

python3 - <<'PY'
from lib import command_router as cr
for text in ['what reminders do I have', 'where am I on my tasks', 'note this under Ideas: test']:
    intent = cr.classify_text_intent(text)
    print(text, '->', intent.kind)
PY
# what reminders do I have -> reminders_read
# where am I on my tasks -> where_was_i
# note this under Ideas: test -> note
```

Recommendation:
- Do not commit the remaining diff as-is.
- Next single unit should split out and commit only the read-only command intent cluster:
  - casual-prefix stripping,
  - broader where-was-I variants,
  - reminders-read intent/handler,
  - `reminder_reader` plumbing,
  - associated tests.
- Leave `_default_note_appender(...)` and the note behavior change uncommitted until Seb explicitly approves live Apple Notes write behavior.

Blockers or decisions needed from Seb:
- Approval required before editing the diff to separate clusters and commit the read-only command intent package.
- Separate explicit approval required before any default Apple Notes write path is committed or exercised live.

## Unit 17 sebOS read-only command intent commit — 2026-06-21 21:22 MDT

Scope executed:
- Split the remaining command-router diff and removed the live Apple Notes default appender behavior from the dirty state.
- Kept only the read-only command intent package:
  - casual-prefix stripping before command classification,
  - broader `where was/am I` variants,
  - read-only `INTENT_REMINDERS_READ`,
  - reminder summary handler using `reminders.run_remindctl(...)` with unavailable fallback sections,
  - `reminder_reader` plumbing through text/audio route entrypoints,
  - tests for classification and read-only routing.
- Preserved no-appender note behavior as staged dry-run with `no_appender_wired`.
- Did not push, open a PR, restart gateway, edit launchd, send messages, or touch Apple/Reminders/Notes data.

Verification run:
```bash
cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
# 46 passed in 0.11s

python3 -m pytest tests/test_command_router.py tests/test_reminders.py tests/test_journal_pending_prompt_cli.py -q
# 58 passed in 0.66s

python3 -m py_compile lib/command_router.py tests/test_command_router.py
# passed

python3 - <<'PY'
from lib import command_router as cr
checks = ['what reminders do I have', 'hey what reminders do I have', 'where am I on my tasks', 'what am I doing']
for text in checks:
    print(text, '->', cr.classify_text_intent(text).kind)
res = cr.route_text('note this under Ideas: keep staged', dry_run=False, write_enabled=True)
print('note-no-appender', res['status'], res['mutated'], res.get('details', {}).get('reason'))
PY
# what reminders do I have -> reminders_read
# hey what reminders do I have -> reminders_read
# where am I on my tasks -> where_was_i
# what am I doing -> where_was_i
# note-no-appender dry_run False no_appender_wired

git diff --cached --check
# passed
```

Static safety checks:
```bash
rg -n "_default_note_appender|osascript|subprocess.run\(" lib/command_router.py tests/test_command_router.py || true
# no matches
```

Commit created:
```bash
cd /Users/clawdolf/.hermes/sebos
git commit -m "feat(router): add read-only reminder command intents"
# 2dc2647 feat(router): add read-only reminder command intents
```

Remaining sebOS dirty work:
- None in `/Users/clawdolf/.hermes/sebos` after this commit.

Next recommended single unit:
- Commit or otherwise package the Hermes `MIGRATION_HANDOFF.md` updates so the migration record is not stranded as a dirty file, then run a final repo status sweep across Hermes, sebOS, and `hermes-sebos`.

Blockers or decisions needed from Seb:
- Approval required before staging/committing Hermes `MIGRATION_HANDOFF.md`, pushing, opening PRs, restarting gateway, live smoke tests, or adding any Apple Notes default write path.

## Unit 18 remaining Hermes dirty-work review + Apple provider-order audit — 2026-06-21 21:35 MDT

Scope executed:
- Ran the approved review/sorting unit only.
- Included Apple Calendar/Reminders provider-order audit.
- Findings only: no implementation, staging, commit, push, gateway restart, launchd edit, live send, or Apple-data mutation.
- Read-only `event --help` / `remindctl --help` probes were run; read-only `event reminders list --json` and `event calendar list --json` probes were run to verify provider capability. Personal item contents were not copied into this handoff.

Current repo state:
- Hermes repo: branch `clean-stock`, HEAD `7984b418e docs(migration): record boundary packaging units`, dirty runtime work remains.
- sebOS repo: branch `main`, HEAD `2dc2647 feat(router): add read-only reminder command intents`, clean.
- `hermes-sebos` plugin repo: branch `main`, HEAD `0df6693 package Photon sebOS boundary facade`, clean except ignored `__pycache__/`.

Remaining Hermes dirty work classified:
1. `sebos_event` plugin migration / messaging opt-in tooling:
   - Files: `hermes_cli/plugins.py`, `tools/registry.py`, `toolsets.py`, `tools/sebos_event.py` deletion, `tests/test_toolsets.py`, `tests/tools/test_sebos_event.py`.
   - Moves the `sebos_event` tool out of Hermes core and into the tracked `hermes-sebos` user plugin, with a generic `include_in_messaging_toolsets=True` registry/toolset opt-in.
   - Risk: medium. This is generic core/toolset behavior plus a local plugin dependency. It is the best next commit candidate because it completes the plugin boundary migration and removes Seb-specific tool code from core.
   - Needs review: confirm plugin is loaded before messaging toolset resolution in all runtimes, and that missing plugin fails as absent tool rather than breaking startup.
2. Athena goals injection:
   - Files: `agent/agent_init.py`, `agent/prompt_builder.py`, `agent/system_prompt.py`, `tests/agent/test_prompt_builder.py`, `tests/agent/test_system_prompt.py`.
   - Injects sebOS `athena_goals.json` as prompt context.
   - Risk: medium-high for upstreamability. It is Seb/Athena-specific and belongs in profile/plugin/config if possible, not generic Hermes core, unless kept as local patch.
3. Generic platform capability hooks / clean inbox / outbound sanitizer:
   - Files: `gateway/platform_registry.py`, `gateway/run.py`, `gateway/outbound_sanitize.py`, `tests/gateway/test_platform_capabilities.py`, `tests/gateway/test_telegram_noise_filter.py`.
   - Replaces hardcoded Photon clean-inbox/final-response sanitizer branches with PlatformEntry capabilities.
   - Risk: medium. Generic and upstreamable in shape, but affects gateway outbound delivery for all platforms with registered capabilities. Good separate package after `sebos_event` migration.
4. Session/platform cleanup and Photon shared-cloud guard fixes:
   - Files: `gateway/session.py`, `tests/gateway/test_session.py`, `tests/plugins/platforms/photon/test_shared_cloud_guard.py`.
   - Removes stale iMessage guidance from session prompt and updates Photon shared-cloud auth expectation from Bearer to Basic id:secret.
   - Risk: low-medium. Should split into two bugfix commits if possible: session prompt cleanup and shared-cloud Basic auth test/behavior alignment.
5. Migration docs:
   - `MIGRATION_HANDOFF.md` is modified by this review-only unit.
   - Risk: low. Commit as docs-only after Seb approval if the review record should be tracked.

Provider-order audit findings:
- Account context was safe for read-only CLI probes: `shell_user=clawdolf`, `home=/Users/clawdolf`, `console_user=clawdolf`.
- `event` exists at `/opt/homebrew/bin/event`; `remindctl` exists at `/opt/homebrew/bin/remindctl`.
- `event reminders list --help` confirms read support with `--json`, optional `--list`, and optional completed-reminder inclusion.
- `event calendar list --help` confirms Calendar read support with `--json`, `--start`, `--end`, and optional calendar filter.
- Read-only probe `event reminders list --json` returned JSON successfully, proving `event` can read reminders on this Mac.
- Read-only probe `event calendar list --start <today> --end <tomorrow> --json` returned JSON successfully, proving `event` can read Calendar on this Mac.
- Focused provider tests passed: `tests/test_reminder_writer.py tests/test_calendars.py tests/test_note_reminder.py` → `28 passed in 1.80s`.
- Syntax check passed for `lib/reminder_writer.py`, `lib/reminders.py`, `lib/calendars.py`, `lib/calendar_writer.py`, `lib/note_reminder.py`.

Provider-order verdict:
- Calendar reads: already correct. `lib/calendars.py` uses `event calendar list --json` primary in `auto`, with read-only local Calendar SQLite fallback. Strict `SEBOS_CALENDAR_READER=event` blocks instead of falling back.
- Calendar writes: already correct. `lib/calendar_writer.py` uses `event calendar create/update/delete` only. No remindctl path applies.
- Reminder writes: already correct. `lib/reminder_writer.py` uses provider order `event → remindctl` for `provider="auto"`. Advanced/native fields do not degrade to remindctl unless explicitly allowed.
- Reminder reads: should be changed in a future unit. `lib/reminders.py` currently uses `remindctl` primary, then JXA/osascript, then read-only Apple Reminders SQLite fallback. Since `event reminders list --json` works on this Mac, the intended next provider-order unit is to make reminder reads `event` primary, with `remindctl` fallback, then JXA/SQLite fallbacks.
- Reminder delete/match reads: also still use `remindctl show all --json` in `lib/reminder_writer.py` for delete matching. Future provider-order cleanup should consider `event reminders list --json` for matching before `remindctl`, or document why delete remains remindctl-backed.
- User-facing copy: no provider names should leak through Photon/Athena. Provider/tool names should stay in logs/details/handoff/debug only. Photon should keep routing to plugin/sebOS boundary and never choose provider order itself.

Verification run:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/agent/test_prompt_builder.py tests/agent/test_system_prompt.py tests/gateway/test_session.py tests/gateway/test_telegram_noise_filter.py tests/gateway/test_platform_capabilities.py tests/plugins/platforms/photon/test_shared_cloud_guard.py tests/test_toolsets.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 299 passed, 1 skipped in 11.47s

python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='
# 43 passed in 1.80s

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py tests/test_reminders.py tests/test_journal_pending_prompt_cli.py -q
# 58 passed in 0.64s

python3 -m pytest tests/test_reminder_writer.py tests/test_calendars.py tests/test_note_reminder.py -q
# 28 passed in 1.80s
```

Next recommended single unit:
- Package only the Hermes `sebos_event` plugin migration / messaging opt-in tooling: `hermes_cli/plugins.py`, `tools/registry.py`, `toolsets.py`, deletion of `tools/sebos_event.py`, `tests/test_toolsets.py`, and `tests/tools/test_sebos_event.py`. Do not mix Athena goals or gateway platform hooks into that commit.

Next provider-order unit after Hermes sorting:
- Implement reminder reads as `event` primary with `remindctl` fallback in sebOS, then update tests. Keep the provider choice inside sebOS; do not expose it to Photon or user-facing copy.

Blockers or decisions needed from Seb:
- Approval required before any implementation, staging, commit, push, gateway restart, launchd edit, live smoke test, iMessage send, or Apple-data mutation.
- Explicit approval required before the future reminder-read provider-order implementation because it changes Apple Reminders read provider order, even though it should remain read-only.

## Unit 19 reminder provider-order implementation — 2026-06-21 22:08 MDT

Scope executed:
- Implemented Seb-approved provider-order change: `event` is now primary over `remindctl` for the remaining Reminders read/match paths.
- No code was staged or committed. No push, gateway restart, launchd edit, live send, or Apple-data mutation.
- Live Apple operation was read-only: `reminders.collect(...)` wrote only to a temporary sebOS DB and read Reminders through `event`.

Files changed:
- `/Users/clawdolf/.hermes/sebos/lib/reminders.py`
  - Added `run_event_all(...)` for `event reminders list --json`.
  - `collect(...)` now tries `event` once, buckets into `today` / `overdue` / `week`, then falls back to `remindctl`, JXA/osascript, then read-only SQLite.
  - Normalizes EventKit-style fields like `externalId`, `dueDate`, `list`, and `isCompleted`.
- `/Users/clawdolf/.hermes/sebos/lib/reminder_writer.py`
  - Delete matching now lists incomplete reminders through `event reminders list --json` first, with `remindctl show all --json` fallback.
  - Delete execution now tries `event reminders delete --id <id>` first, with `remindctl delete <id> --force` fallback.
- `/Users/clawdolf/.hermes/sebos/lib/command_router.py`
  - Default reminders-read command path now uses `event` first, with `remindctl` fallback, while preserving injected `reminder_reader` behavior for tests/callers.
- `/Users/clawdolf/.hermes/sebos/tests/test_reminders.py`
  - Updated collection tests to prove event-primary behavior and fallback to remindctl/JXA.
- `/Users/clawdolf/.hermes/sebos/tests/test_reminder_writer.py`
  - Added event-primary delete list/delete test and preserved legacy remindctl fallback tests.
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`
  - This handoff entry.

Verification run:
```bash
cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_reminders.py tests/test_reminder_writer.py tests/test_command_router.py -q
# 73 passed in 0.40s

python3 -m pytest tests/test_command_router.py tests/test_reminders.py tests/test_reminder_writer.py tests/test_note_reminder.py tests/test_calendars.py tests/test_journal_pending_prompt_cli.py -q
# 88 passed in 2.45s

python3 -m py_compile lib/reminders.py lib/reminder_writer.py lib/command_router.py tests/test_reminders.py tests/test_reminder_writer.py
# passed, no output

python3 -m pytest -q
# 546 passed in 36.53s
```

Read-only live provider check:
```bash
cd /Users/clawdolf/.hermes/sebos
python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from lib import reminders
with TemporaryDirectory() as td:
    result = reminders.collect(Path(td) / 'sebos.db')
print({'status': result['status'], 'sources': result['sources'], 'counts': result['counts']})
PY
# {'status': 'ok', 'sources': {'today': 'event', 'overdue': 'event', 'week': 'event'}, 'counts': {'today': 2, 'overdue': 0, 'week': 6}}
```

Behavior migrated:
- Calendar reads/writes were already event-primary.
- Reminder writes were already event-primary.
- Reminder collection/read paths are now event-primary.
- Command-router reminders-read fallback path is now event-primary.
- Reminder delete matching and delete command execution are now event-primary.
- `remindctl` remains fallback for older or denied EventKit/event environments.

Rollback notes:
- Revert changes to `lib/reminders.py`, `lib/reminder_writer.py`, `lib/command_router.py`, `tests/test_reminders.py`, and `tests/test_reminder_writer.py`.
- This returns Reminder read/match/delete paths to remindctl-primary behavior.
- No Apple data was changed by this unit, so runtime rollback is code-only.

Remaining debt:
- Provider/tool names still appear in sebOS structured outputs/tests/debug details; keep them out of Photon/Athena user-facing copy.
- `remindctl` fallback remains intentionally for rollback and compatibility.
- Handoff docs are dirty in Hermes and runtime provider-order code is dirty in sebOS; commit packaging needs separate approval.

Next recommended single unit:
- Stage and commit only the sebOS provider-order runtime package: `lib/reminders.py`, `lib/reminder_writer.py`, `lib/command_router.py`, `tests/test_reminders.py`, and `tests/test_reminder_writer.py`. Keep Hermes `MIGRATION_HANDOFF.md` as a separate docs commit.

Blockers or decisions needed from Seb:
- Approval required before staging/committing the sebOS provider-order package, committing the Hermes handoff doc, pushing, opening PRs, restarting gateway, live smoke tests, launchd edits, or any Apple-data mutation.
