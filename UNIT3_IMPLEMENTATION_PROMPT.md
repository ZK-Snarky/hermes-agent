/goal Approved: implement Unit 3 smallest boundary slice only.

You are continuing the Athena/Hermes/sebOS/Photon boundary migration.

Mission:
Implement only the smallest safe Unit 3 slice from `/Users/clawdolf/.hermes/hermes-agent/UNIT2_BOUNDARY_DESIGN.md`: introduce a `hermes-sebos` plugin-owned Photon route facade in parallel, then route only the explicit Photon sebOS command path through it with fallback to the current Photon runner. Preserve behavior.

Read these first, before any edits:
- `/Users/clawdolf/.hermes/skills/devops/hermes-boundary-migration/SKILL.md`
- `/Users/clawdolf/.hermes/hermes-agent/DOCS_EVIDENCE.md`
- `/Users/clawdolf/.hermes/hermes-agent/DISCOVERY.md`
- `/Users/clawdolf/.hermes/hermes-agent/TARGET_ARCHITECTURE.md`
- `/Users/clawdolf/.hermes/hermes-agent/BOUNDARY_RULES.md`
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_PLAN.md`
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`
- `/Users/clawdolf/.hermes/hermes-agent/UNIT2_BOUNDARY_DESIGN.md`

First verify state, before edits:

```bash
cd /Users/clawdolf/.hermes/hermes-agent
git status --short
git branch --show-current
git diff --stat

cd /Users/clawdolf/.hermes/sebos
git status --short
git branch --show-current
git diff --stat

test -d /Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z && echo unit1-dir-ok
test -f /Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z.tar.gz && echo unit1-archive-ok
```

Run baseline tests before edits:

```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
```

Allowed implementation files:
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/__init__.py` only if needed to expose/import the facade cleanly, not to register new live tools unless tests prove no behavior change.
- `/Users/clawdolf/.hermes/plugins/hermes-sebos/plugin.yaml` only if needed to document the facade, not to change live enablement semantics.
- `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py`
- `/Users/clawdolf/.hermes/hermes-agent/tests/plugins/platforms/photon/test_sebos_rules.py`
- Optional hermetic plugin test file under `/Users/clawdolf/.hermes/hermes-agent/tests/` only if it can import the user plugin without changing live config.
- `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md`

Forbidden files/systems:
- Do not edit gateway code, tool registry, toolsets, agent prompt files, launchd, live config, credentials, Photon sidecar code, or sebOS domain code.
- Do not edit `/Users/clawdolf/.hermes/sebos/*` in Unit 3.
- Do not touch Reminders, Notes, Close, Monarch, Telegram, Calendar, WHOOP, finance/bank systems, or Apple data.
- Do not restart gateway.
- Do not edit launchd.
- Do not send iMessages or live Photon messages.
- Do not push, merge, rebase, force-push, stash, or commit.
- Do not de-domain all Photon logic.
- Do not change natural-language intent gate behavior, date parsing, reminder writer behavior, board rendering, active journal prompt/audio journal behavior, Athena goals injection, or outbound sanitizer.
- Stop and ask before any scope expansion.

Implementation requirements:

1. Create `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py` with hermetic, testable async helpers:
   - `run_sebos_json(*args: str, stdin: str | None = None, timeout: float = 20.0) -> dict[str, Any]`
   - `route_text_command(text: str, *, write: bool = True, db_path: str | None = None, channel: str = "imessage", timeout: float = 45.0) -> dict[str, Any]`

2. The facade must preserve the existing `_run_sebos_json` contract:
   - parse stdout JSON into a dict,
   - return raw text on non-JSON stdout,
   - include `stderr` when present,
   - include `returncode`,
   - return structured errors for missing command and timeout,
   - do not expose shell/remindctl/PATH/tool text as user-facing copy.

3. Update Photon adapter minimally:
   - Add a private helper that tries the plugin facade first for explicit sebOS commands.
   - Keep existing `_run_sebos_json` fallback.
   - Change only `_handle_sebos_rules` explicit command branch around `sebos-route-command` to call the new helper.
   - Preserve current ack/text behavior and fall-through behavior.

4. Tests:
   - Update `tests/plugins/platforms/photon/test_sebos_rules.py` so explicit command routing proves delegation through the new boundary helper/facade while preserving user-facing output.
   - Add a fallback test proving old `_run_sebos_json` behavior still works if the plugin boundary is unavailable.
   - Do not require live sebOS, live Photon, live Reminders, or live Notes.

5. After edits, run:

```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/tools/test_sebos_event.py -q -o 'addopts='

cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
```

6. Static verification after edits:

```bash
cd /Users/clawdolf/.hermes/hermes-agent
rg -n "sebos-route-command|sebos-add-reminder|sebos-journal-pending-prompt|sebos-ingest-journal|_run_sebos_json|photon_boundary" plugins/platforms/photon/adapter.py tests/plugins/platforms/photon/test_sebos_rules.py /Users/clawdolf/.hermes/plugins/hermes-sebos
```

7. Update `/Users/clawdolf/.hermes/hermes-agent/MIGRATION_HANDOFF.md` with:
   - Unit 3 completed or blocked,
   - docs read,
   - files changed,
   - exact tests run and results,
   - rollback notes,
   - remaining Photon/sebOS boundary debt,
   - next recommended single slice,
   - blockers or decisions needed from Seb.

Rollback notes to preserve:
- Revert changes to Photon adapter and tests.
- Remove `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py` if created.
- Existing Photon `_run_sebos_json` fallback should make runtime rollback low-risk.

Final response, 5 bullets max:
- files changed,
- tests passed/failed,
- exact behavior migrated,
- remaining debt,
- whether Seb needs approval for next slice.
