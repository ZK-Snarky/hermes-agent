# MIGRATION_PLAN.md

Scope: ordered migration units P0-P6 plus bounded implementation units. Unit 1 freeze/export is complete. Unit 2 boundary design is complete. No code implementation unless Seb approves the exact next unit prompt.

## Unit 2: Boundary design for Unit 3

Status: complete.

Goal:
- Design the exact Unit 3 implementation plan for moving Photon sebOS/Athena policy behind the approved plugin/MCP/sebOS boundary without changing behavior.
- Pick the smallest safe Unit 3 slice.
- Produce a pasteable prompt for the next fresh implementation session.

Files written:
- `/Users/clawdolf/.hermes/hermes-agent/UNIT2_BOUNDARY_DESIGN.md`
- `/Users/clawdolf/.hermes/hermes-agent/UNIT3_IMPLEMENTATION_PROMPT.md`
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_PLAN.md`
- Updated `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`

Chosen design:
- Use the existing `hermes-sebos` user plugin as the near-term Hermes/sebOS boundary.
- Add a plugin-owned Photon route facade in parallel, backed by sebOS CLI wrappers.
- In Unit 3, route only the explicit sebOS command path through that facade, with fallback to the current Photon `_run_sebos_json` path.
- Do not introduce MCP in Unit 3. MCP remains a future option for broader resources/prompts/tools after the narrow plugin facade proves parity.

Recommended Unit 3 target:
- Create `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`.
- Minimally change `plugins/platforms/photon/adapter.py` so the explicit command branch around `sebos-route-command` delegates to the plugin facade first and falls back to old behavior.
- Update only focused Photon tests and handoff docs.

Unit 3 must not touch:
- gateway restart, launchd, live sends, live Reminders/Notes/Close/Monarch/Telegram/Apple data, push/merge/rebase/stash/commit, natural intent gate/date parser, board rendering, audio journal, Athena goals injection, gateway sanitizer, core tool registry/toolsets, or sebOS domain code.

Prompt path:
- `/Users/clawdolf/.hermes/hermes-agent/UNIT3_IMPLEMENTATION_PROMPT.md`

## P0: Freeze and protect update path

Goal:
- Preserve current local patches before any Hermes update/rebase.
- Create rollback point and evidence bundle.
- Do not implement until `DOCS_EVIDENCE.md`, `DISCOVERY.md`, `TARGET_ARCHITECTURE.md`, and `BOUNDARY_RULES.md` exist.

Docs basis:
- Configuration/profile docs: `configuration.md:7-60`, `profiles.md:5-13`, `profiles.md:270-302`.
- Plugin docs: `plugins.md:118-182`.
- Local boundary skill: freeze patches before update.

Files allowed:
- Documentation files only.
- Optional patch export under a migration workspace if approved.

Files forbidden:
- Any code file, launchd plist, gateway config, Photon sidecar, credentials.

Behavior to preserve:
- Current Photon/sebOS routing remains untouched.

Verification commands:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
git status --short
git diff --stat
git diff --name-status
cd /Users/clawdolf/.hermes/sebos
git status --short
git diff --stat
git diff --name-status
```

Rollback:
- None needed for docs-only. For later units, create a branch or stash/export patch first.

Seb approval gates:
- Required before stashing, committing, updating Hermes, or changing code.

Risk: low.

## P1: De-domain Photon adapter

Goal:
- Remove sebOS/Athena domain policy from Photon adapter unless docs prove it belongs there.
- Keep Photon transport-only: sidecar, auth, inbound normalization, outbound send/reply/reaction/attachment/typing/retry, clean formatting.
- Preserve behavior for reminder read/write, board, journal/note, and audio if present through a new boundary.
- Keep casual-prefix regression working.

Docs basis:
- Platform adapter docs `adding-platform-adapters.md:5-30`.
- Photon docs `photon.md:23-40`, `:84-143`, `:194-226`.
- Plugin/MCP docs `plugins.md:94-116`, `mcp.md:7-20`.

Files allowed:
- `plugins/platforms/photon/adapter.py` only for removing domain calls and keeping transport.
- Tests under `tests/plugins/platforms/photon/` for transport handoff and no raw plumbing copy.
- Boundary plugin/MCP files only if implementing the replacement in same unit is approved.

Files forbidden:
- `agent/*` prompt behavior, `tools/registry.py`, `toolsets.py`, gateway restart/launchd, live sends.

Behavior to preserve:
- “hey what reminders do i have” still routes correctly.
- “what reminders do I have” still routes correctly.
- “remind me tomorrow…” still writes only through approved sebOS gate.
- “board” and “note this…” still work.
- Audio/journal path remains functional if current code supports it.
- User copy does not mention shell/remindctl/tool exposure.

Verification commands:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py -q -o 'addopts='
cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
```

Rollback:
- Revert P1 diff or apply saved patch export.

Seb approval gates:
- Required before implementation.
- Required before any live iMessage send or gateway restart.

Risk: high because this touches user-facing iMessage routing.

## P2: Formalize sebOS boundary

Goal:
- Decide plugin vs MCP per capability.
- Keep `hermes-sebos` plugin for small native tools/hooks if docs support it.
- Consider sebOS MCP server for broader tools/resources/prompts:
  - `reminders_read`
  - `reminder_write`
  - `board/status`
  - `note/journal_write`
  - `goals/context`
  - `Mission Control render`

Docs basis:
- Plugin docs `plugins.md:94-116`.
- MCP docs `mcp.md:7-20`, `:347-537`; config docs `mcp-config-reference.md:15-160`.
- Current sebOS source: `lib/command_router.py`, `lib/reminders.py`, `lib/reminder_writer.py`.

Files allowed:
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/*`
- `/Users/clawdolf/.hermes/sebos/` new MCP/CLI wrapper files and tests, if approved.
- Hermes config docs only, not live config, unless approved.

Files forbidden:
- Hermes core registry/toolsets except if a generic upstream bridge is explicitly selected.
- Photon adapter domain logic.

Behavior to preserve:
- Structured event writes via `sebos_event`.
- Reminder read/write and board/note/journal behavior.

Verification commands:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/test_toolsets.py tests/tools/test_sebos_event.py -q -o 'addopts='
cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
```

Rollback:
- Disable MCP/plugin capability in config, revert code, restore direct compatibility shim only if needed and explicitly marked temporary.

Seb approval gates:
- Required before adding MCP server config or changing plugin enablement.

Risk: medium.

## P3: Clean Hermes core prompt/toolset patches

Goal:
- Move Athena goals/prompt injection out of core if official docs support config/profile/skills/plugin context instead.
- Classify `toolsets.py` and `tools/registry.py` changes as generic upstream feature vs local workaround.
- Decide whether `include_in_messaging_toolsets` should be upstreamed.

Docs basis:
- Config docs `configuration.md:7-60`, `:795-813`.
- Skills docs `skills.md:7-13`, `:74-121`.
- Plugin docs for injected messages/context `plugins.md:94-116`.
- Tools/toolsets docs `tools-runtime.md:25-68`, `toolsets-reference.md:119-153`.

Files allowed:
- `agent/agent_init.py`, `agent/prompt_builder.py`, `agent/system_prompt.py` for removing/moving local behavior.
- `toolsets.py`, `tools/registry.py` only for generic/upstream bridge cleanup.
- Associated tests.

Files forbidden:
- Photon sidecar, sebOS domain logic, launchd, live config.

Behavior to preserve:
- Athena goals still appear in Athena context through approved boundary.
- Plugin tools needed by messaging remain available in intended platforms.

Verification commands:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/agent/test_prompt_builder.py tests/agent/test_system_prompt.py tests/test_toolsets.py -q -o 'addopts='
```

Rollback:
- Revert core prompt/toolset diff and restore prior local injection temporarily.

Seb approval gates:
- Required before changing active prompt behavior.

Risk: medium-high because prompt context affects every session.

## P4: Outbound sanitization and platform behavior

Goal:
- Decide whether `outbound_sanitize` belongs in gateway core, plugin hook, or platform adapter.
- Keep only generic cross-platform behavior in core.
- Keep Photon/Athena clean-inbox copy policy as platform capability or local plugin policy.

Docs basis:
- Gateway/platform docs `adding-platform-adapters.md:117-200`.
- Gateway internals `gateway-internals.md:52-67`.
- Source: `gateway/outbound_sanitize.py:1-33`, `gateway/run.py:343-401`, `adapter.py:100-120`, `adapter.py:2739-2744`.

Files allowed:
- `gateway/outbound_sanitize.py`, `gateway/run.py`, `gateway/platform_registry.py`, platform adapter sanitizer registration, tests.

Files forbidden:
- sebOS domain code.

Behavior to preserve:
- Clean Photon output.
- No raw tool/path/plumbing leak to Seb.
- Generic gateway behavior stays generic.

Verification commands:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/gateway/test_platform_capabilities.py tests/gateway/test_telegram_noise_filter.py tests/plugins/platforms/photon/test_sebos_rules.py -q -o 'addopts='
```

Rollback:
- Disable platform sanitizer hook or revert gateway sanitizer diff.

Seb approval gates:
- Required before gateway restart/live test.

Risk: medium.

## P5: Tests and regression harness

Goal:
- Lock behavior without locking the wrong architecture.
- Add synthetic Photon inbound tests, no live send.
- Add launchd stripped PATH tests for sebOS route/remindctl fallback.

Required tests:
- “hey what reminders do i have”
- “what reminders do I have”
- “remind me tomorrow…”
- “board”
- “note this…”
- “where was I”
- “why do you suck” must not mention shell/remindctl/tool exposure
- launchd stripped PATH for remindctl/sebOS route
- synthetic Photon inbound event, no live send

Docs/source basis:
- Current test structure in `tests/plugins/platforms/photon/`, `tests/test_toolsets.py`, `tests/tools/test_sebos_event.py`, `sebos/tests/test_command_router.py`.
- Official platform docs support synthetic adapter event tests.

Files allowed:
- Test files only plus fixture helpers.

Files forbidden:
- Code unless test reveals blocker and Seb approves implementation.

Verification commands:
```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/test_toolsets.py tests/tools/test_sebos_event.py -q -o 'addopts='

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q

whoami
stat -f%Su /dev/console
launchctl print "gui/$(id -u)" >/dev/null 2>&1 && echo "gui domain OK" || echo "no gui domain"
```

Rollback:
- Revert tests that encode wrong boundary.

Seb approval gates:
- None for read-only tests. Required for tests that write live Reminders/Notes/iMessages.

Risk: low-medium.

## P6: Fresh review and handoff

Goal:
- Fresh-context reviewer audits implementation against `BOUNDARY_RULES.md` and `DOCS_EVIDENCE.md`.
- Update `MIGRATION_HANDOFF.md` every session.

Docs basis:
- Local boundary migration process; official docs are the review evidence baseline.

Files allowed:
- `MIGRATION_HANDOFF.md`, review notes, no code changes unless separate approved unit.

Files forbidden:
- Any implementation under review-only prompt.

Behavior to preserve:
- No new boundary drift.

Verification commands:
```bash
git -C /Users/clawdolf/.hermes/hermes-agent status --short
git -C /Users/clawdolf/.hermes/sebos status --short
```

Rollback:
- Revert implementation unit under review if blocking issue found.

Seb approval gates:
- Required before moving to next implementation unit if review finds high-risk ambiguity.

Risk: low.

## Recommended implementation sequence

1. Unit 1/P0 freeze/export current patches. Complete.
2. Unit 2 boundary design. Complete.
3. Unit 3 smallest implementation slice: plugin-owned Photon route facade plus explicit sebOS command delegation with fallback.
4. Next slice after Unit 3: board/now/next route through the same facade, or active journal prompt probe through the facade, depending test results.
5. Later P1: move remaining Photon domain calls to boundary while preserving tests.
6. P4 sanitize/generic platform behavior cleanup.
7. P3 prompt/toolset cleanup.
8. P5 regression harness expansion.
9. P6 fresh review.

Current next prompt path: `/Users/clawdolf/.hermes/hermes-agent/UNIT3_IMPLEMENTATION_PROMPT.md`.

Do not start P1 wholesale. De-domaining Photon without a proven plugin/sebOS boundary risks breaking the iMessage path.
