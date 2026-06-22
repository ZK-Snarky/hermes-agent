# UNIT2_BOUNDARY_DESIGN.md

Scope: Unit 2 boundary design only. No behavior changes. No Photon de-domain. No gateway restart, launchd edit, live iMessage send, or external data mutation.

## Inputs verified

- Unit 1 workspace exists: `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z`.
- Unit 1 archive exists: `/Users/clawdolf/.hermes/tmp/athena-boundary-unit1-20260622T014308Z.tar.gz`.
- Hermes repo branch during Unit 2: `clean-stock`.
- sebOS repo branch during Unit 2: `main`.
- Existing dirty worktrees were preserved. Unit 2 only writes migration docs.

## A. Current coupling map

### 1. Hardcoded sebOS filesystem paths in Photon

- file:line: `plugins/platforms/photon/adapter.py:92-96`
- behavior: Photon defines `_SEBOS_ROOT`, `_SEBOS_BIN_DIR`, `_SEBOS_DB_PATH`, `_SEBOS_AUDIO_INBOX`, and document cache paths using `Path.home()`.
- current call path: module constants -> `_run_sebos_json`, `_mission_control_text`, `_active_journal_prompt_date`, `_copy_audio_to_sebos_inbox`, `_try_ingest_audio_journal_reply`, `_handle_sebos_rules`, `_try_intent_gate`.
- user-facing behavior it preserves: iMessage can reach sebOS command binaries, sebOS DB, Mission Control board rendering, journal prompt detection, reminder writes, and audio journal inbox without asking Athena to use a tool.
- boundary assessment: violates `BOUNDARY_RULES.md` rule 2 in target state because Photon directly knows sebOS paths and commands. It also conflicts with rule 3/profile safety because the path is hardcoded through home/profile assumptions.
- docs evidence: `DOCS_EVIDENCE.md:16-19` says platform adapters are transport and Photon is sidecar transport; `DOCS_EVIDENCE.md:7-15` says plugins/MCP are documented extension points for custom/local tools.

### 2. Photon-owned sebOS subprocess runner

- file:line: `plugins/platforms/photon/adapter.py:388-424`
- behavior: `_run_sebos_json` executes binaries under `_SEBOS_BIN_DIR`, passes optional stdin, parses stdout as JSON, attaches stderr/return code.
- current call path: Photon inbound handling -> `_try_ingest_audio_journal_reply` / `_try_intent_gate` / `_handle_sebos_rules` -> `_run_sebos_json` -> sebOS CLI.
- user-facing behavior it preserves: deterministic iMessage commands and some natural-language intents can return fast local replies or tapbacks without a full Hermes/Athena agent turn.
- boundary assessment: violates rule 2 in target state. This is a temporary compatibility shim only if documented with a removal target.
- docs evidence: `DOCS_EVIDENCE.md:12-18` supports tool/plugin/MCP dispatch and platform adapter transport responsibilities; `DOCS_EVIDENCE.md:32-33` labels the no-domain-in-Photon rule as inference plus local convention.

### 3. Mission Control board rendering in Photon

- file:line: `plugins/platforms/photon/adapter.py:443-474`, `729-743`
- behavior: `_mission_control_text` runs `sebos-render-mission-control --dry-run --json`; `_section_from_board` slices NOW/NEXT sections; `_handle_sebos_rules` sends board/now/next replies directly.
- current call path: iMessage text `board`, `now`, or `next` -> `_dispatch_inbound` -> `_handle_sebos_rules` -> `_mission_control_text` -> sebOS CLI -> `_send_quiet`.
- user-facing behavior it preserves: Seb can text `board`, `now`, or `next` and receive a concise Mission Control/Live Board reply in iMessage.
- boundary assessment: violates rule 2 because board/Mission Control is sebOS domain policy, not Photon transport. `_send_quiet` and reply threading are valid Photon transport mechanics, but selecting/rendering board content is not.
- docs evidence: `DOCS_EVIDENCE.md:16-19`; `TARGET_ARCHITECTURE.md:124-135` says board should route through plugin/MCP to sebOS renderer/status command.

### 4. Audio journal ingestion from Photon

- file:line: `plugins/platforms/photon/adapter.py:476-495`, `539-549`, `583-696`, `1676-1685`
- behavior: Photon checks active journal prompt date, recovers marker-only audio from document cache, copies audio into sebOS inbox, writes a temporary JSON payload, runs `sebos-ingest-journal`, and sends a heart tapback or text fallback.
- current call path: inbound audio/text marker -> `_dispatch_inbound` -> `_try_ingest_audio_journal_reply` -> `_active_journal_prompt_date` -> `_copy_audio_to_sebos_inbox` -> `sebos-ingest-journal` -> `_send_ack_reaction` / `_send_quiet`.
- user-facing behavior it preserves: responding to an active journal prompt with an iMessage voice note saves the journal audio/transcript and gets a quiet native acknowledgement.
- boundary assessment: mixed. Attachment/audio normalization and tapback are valid Photon transport. Active prompt detection, journal inbox layout, journal ingest payload, and sebOS CLI execution violate rule 2 in target state. Because audio behavior is higher risk, it should remain temporarily in Photon until a later dedicated slice.
- docs evidence: `DOCS_EVIDENCE.md:17-20` supports Photon messaging/attachments/reactions as transport; `TARGET_ARCHITECTURE.md:176-187` assigns transcript/journal semantics to sebOS/Athena boundary, not Photon.

### 5. Explicit sebOS command routing in Photon

- file:line: `plugins/platforms/photon/adapter.py:698-770`, `1151-1189`, `1698-1709`
- behavior: `_looks_like_sebos_command` strips casual prefixes and detects `j:`, `journal:`, `reminder:`, `note:`, suppression phrases, reminder queries, and task/board exact phrases. `_handle_sebos_rules` routes matching text to `sebos-route-command --write --json`, sends tapback/text, or falls through to Hermes.
- current call path: inbound text -> `_dispatch_inbound` -> `_handle_sebos_rules` -> `_looks_like_sebos_command` -> `_run_sebos_json("sebos-route-command", ...)` -> sebOS command router.
- user-facing behavior it preserves: deterministic iMessage commands such as `j: ...`, `note: ...`, `reminder: ...`, `what reminders do I have`, and `where was I` work without full agent latency, with casual prefix support like `hey what reminders do i have`.
- boundary assessment: violates rule 2 because Photon owns command recognition and shells to sebOS. It partially aligns with the target that unknown text falls through to Hermes, but the target owner should be plugin/sebOS boundary.
- docs evidence: `DOCS_EVIDENCE.md:18` says gateway message flow should go adapter -> gateway -> AIAgent unless command/session routing applies; `BOUNDARY_RULES.md:62-64` says tests must assert new boundary behavior, not old boundary leak.

### 6. Natural-language intent gate in Photon

- file:line: `plugins/platforms/photon/adapter.py:249-269`, `790-1149`, `1687-1697`
- behavior: Photon config enables `sebos_rules` and `intent_gate`; adapter classifies short iMessages via deterministic parser or auxiliary LLM prompt, converts intent to sebOS CLI args/text, writes reminders directly via `sebos-add-reminder`, routes note/journal/board via `sebos-route-command`, and sends tapbacks/replies.
- current call path: inbound text -> `_dispatch_inbound` -> `_try_intent_gate` -> `_classify_natural_intent` / `_deterministic_natural_reminder_intent` -> `_intent_reminder_args` or `_intent_to_sebos_text` -> `_run_sebos_json` -> sebOS CLI -> ack/text.
- user-facing behavior it preserves: `remind me Monday at 9 to call Turner`, high-confidence date-only reminders default to 9am, location reminders, natural note/journal/board intents, clarification replies, and low-confidence fall-through to Hermes.
- boundary assessment: highest violation. Photon owns Athena/sebOS semantic policy, date/location/defaulting, auxiliary LLM prompt, and write path. Tapback and threaded reply mechanics are transport and should stay in Photon.
- docs evidence: `DOCS_EVIDENCE.md:7-18` supports custom tools/plugins/MCP and transport-only platform adapters; `TARGET_ARCHITECTURE.md:111-122` assigns reminder write routing to Hermes/Athena tool boundary and sebOS writer.

### 7. Current Photon tests encode the old boundary

- file:line: `tests/plugins/platforms/photon/test_sebos_rules.py:52-80`, `205-260`; `tests/plugins/platforms/photon/test_intent_gate.py:53-99`, `102-128`, `194-242`
- behavior: tests monkeypatch `_run_sebos_json` and assert exact sebOS CLI names/args from Photon.
- current call path: unit tests instantiate `PhotonAdapter`, call `_handle_sebos_rules`, `_try_intent_gate`, or `_dispatch_inbound`, then assert direct CLI routing.
- user-facing behavior it preserves: deterministic command routing, 9am default, active journal prompt detection, note/journal normalization, and fall-through behavior.
- boundary assessment: useful regression coverage but currently locks the violation in place. Unit 3 must change tests for the chosen path so they assert Photon delegates to a boundary method/tool facade, not a raw sebOS CLI.
- docs evidence: `BOUNDARY_RULES.md:62-64`; `DOCS_EVIDENCE.md:16-18`.

### 8. Existing hermes-sebos plugin is narrow and event-only

- file:line: `/Users/clawdolf/.hermes/plugins/hermes-sebos/plugin.yaml:1-7`, `/Users/clawdolf/.hermes/plugins/hermes-sebos/__init__.py:21-32`, `/Users/clawdolf/.hermes/plugins/hermes-sebos/tools.py:74-75`, `219-227`, `260-269`
- behavior: plugin registers `sebos_event` only, writing one JSON event file into `~/.hermes/sebos/inbox/events`.
- current call path: Hermes tool registry -> plugin tool handler -> `tools.emit` -> sebOS event inbox.
- user-facing behavior it preserves: Athena can record high-signal operational events into sebOS without a core `tools/sebos_event.py` tool.
- boundary assessment: does not violate the rules. It proves the plugin boundary works, but it does not yet cover Photon route/reminder/board/note/journal capabilities.
- docs evidence: `DOCS_EVIDENCE.md:7-12` says user plugins can register tools/hooks and custom tools should use plugins.

### 9. sebOS command router and reminder modules already own domain semantics

- file:line: `/Users/clawdolf/.hermes/sebos/lib/command_router.py:1-37`, `53-96`, `588-857`, `1264-1401`; `/Users/clawdolf/.hermes/sebos/lib/reminders.py:80-99`, `232-349`; `/Users/clawdolf/.hermes/sebos/lib/reminder_writer.py:239-311`, `336-437`
- behavior: sebOS classifies commands, defaults to dry-run, dependency-injects writes, reads reminders through remindctl/JXA/SQLite fallback, and writes reminders through event/remindctl provider order.
- current call path: Photon currently calls sebOS CLI wrappers that eventually call these modules. Tests also call these modules directly in sebOS repo.
- user-facing behavior it preserves: board/read/write/note/journal/suppression semantics and structured result schema.
- boundary assessment: correct owner. Risk remains around Terminal fallback in `reminder_writer.py:33-48`, `84-100`, `336-357`; Unit 3 should not change that unless explicitly approved.
- docs evidence: `BOUNDARY_RULES.md:18-35`; `TARGET_ARCHITECTURE.md:40-50`.

## B. Proposed new boundary

Recommended design: plugin-owned Photon route facade that shells to sebOS CLI behind the `hermes-sebos` plugin, with the CLI still owned by sebOS. Do not introduce MCP in Unit 3.

Reasoning:

- It is the smallest behavior-preserving slice. Photon can delegate to a boundary without forcing a live MCP server/config change.
- Unit 1 already proved `hermes-sebos` is enabled and the registry can load plugin tools.
- Existing sebOS CLIs and `command_router.py` already return structured JSON. Unit 3 can wrap them rather than rewrite semantics.
- MCP is still the right future home for broader resources/prompts, but adding MCP config/server now would expand scope and create live config risk.
- Plugin tool calls are designed for model/tool dispatch. Photon adapter code cannot safely call a model tool as if it were the model. Unit 3 should introduce a plugin module/facade function imported by Photon, then later expose the same facade as plugin tools if needed.

Boundary shape:

- Owner: `hermes-sebos` plugin owns Hermes-side sebOS access shims.
- Execution authority: sebOS owns CLI behavior and Apple/local side effects.
- Photon responsibility: transport only, plus temporary call into the plugin facade while old behavior is preserved.
- Temporary debt: Photon still contains intent recognition during Unit 3 if needed; the selected slice should move only one low-risk path first.

### Proposed plugin module: `photon_boundary.py`

Target file in Unit 3: `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py`.

Core helper:

```python
async def run_sebos_json(*args: str, stdin: str | None = None, timeout: float = 20.0) -> dict[str, Any]
```

Input schema:

```json
{
  "args": ["sebos-route-command", "--text", "-", "--write", "--db", "/path/to/sebos.db", "--json"],
  "stdin": "optional text",
  "timeout": 20.0
}
```

Output schema:

```json
{
  "status": "ok|dry_run|needs_clarification|ignored|error|blocked|unknown",
  "intent": "board|where_was_i|reminders_read|journal|reminder|note|ask|clarify|unknown|...",
  "reply": "user-facing short copy when available",
  "mutated": false,
  "side_effects": [],
  "error_layer": "reminders|notes|journal|mission_control|router|null",
  "details": {},
  "returncode": 0,
  "stderr": "only for logs/debug; Photon must not show raw stderr"
}
```

Error behavior:

- Missing command: return `{"status":"error","error_layer":"router","error":"missing sebOS command: <name>","returncode":127}`.
- Timeout: kill process and return `{"status":"error","error_layer":"router","error":"sebOS command timed out: <name>","returncode":124}`.
- Invalid JSON: return `{"status":"error"}` if return code non-zero, otherwise `{"status":"ok","raw":"..."}`, preserving current `_run_sebos_json` compatibility.
- Photon must use generic user copy (`Could not handle that.`) and logs for raw errors. No shell/remindctl/PATH/tool-exposure copy.

Rollback plan:

- Revert Photon adapter import/delegation and plugin file additions.
- Existing `_run_sebos_json` path stays in place during Unit 3 as fallback.
- If plugin import fails, Photon falls back to existing local `_run_sebos_json` behavior in this slice.

### Behavior target 1: explicit sebOS command route, recommended Unit 3 slice

- current owner: Photon adapter.
- target owner: `hermes-sebos` plugin facade + sebOS `sebos-route-command`.
- target function/hook name: `hermes_sebos.photon_boundary.route_text_command` or, if import path is package-local, `plugins.hermes_sebos.photon_boundary.route_text_command` depending plugin loader path. Unit 3 must verify actual import path before editing Photon.
- proposed signature:

```python
async def route_text_command(text: str, *, write: bool, db_path: str | None = None, channel: str = "imessage", timeout: float = 45.0) -> dict[str, Any]
```

Input schema:

```json
{
  "text": "reminder: tomorrow at 9 call Chaz",
  "write": true,
  "db_path": "/Users/clawdolf/.hermes/sebos/sebos.db",
  "channel": "imessage",
  "timeout": 45.0
}
```

Output schema: exactly sebOS command router result plus `returncode` if from CLI.

Error behavior:

- Unknown/ignored/ask returns to Photon as non-handled so normal Hermes path can continue.
- `status=error` returns handled only when sebOS classified a deterministic intent and supplied failure copy. Photon may fall back to `Could not handle that.`.
- Raw stderr stays logs-only.

Test plan:

- Before change: run current Photon/sebOS focused tests.
- Add or update tests so `_handle_sebos_rules` delegates explicit commands to a boundary object/function, not `_run_sebos_json` directly.
- Preserve assertions for user-facing behavior: `reminder: tomorrow at 9 call Chaz` returns `handled` and sends `Reminder set.` in thread.
- Add fallback test: plugin boundary import/facade failure calls old `_run_sebos_json` path and still passes existing behavior.
- Add static test or grep check proving explicit route no longer calls raw `sebos-route-command` in `_handle_sebos_rules` except in fallback/debt function.

Rollback plan:

- Delete plugin facade file and revert Photon adapter changes. Because old runner remains, rollback is a clean diff revert.

### Behavior target 2: board/now/next rendering, leave until after explicit route

- current owner: Photon adapter.
- target owner: plugin facade function `render_mission_control` backed by sebOS CLI.
- input schema:

```json
{"view":"board|now|next","max_items":3,"dry_run":true,"timeout":25.0}
```

- output schema:

```json
{"status":"ok|error","reply":"...","body":"full Mission Control text","section":"NOW|NEXT|null","returncode":0}
```

- error behavior: unavailable board returns `Mission Control unavailable.` or generic copy; raw CLI errors logs-only.
- test plan: assert `board` still sends full board; `now`/`next` still slice sections. Move `_section_from_board` to plugin/sebOS later, not Unit 3.
- rollback plan: keep old `_mission_control_text` until the dedicated slice passes.

### Behavior target 3: active journal prompt probe, leave until after explicit route

- current owner: Photon adapter.
- target owner: plugin facade function `active_journal_prompt_date` backed by `sebos-journal-pending-prompt`.
- input schema:

```json
{"at":"2026-06-20T22:00:00+00:00","db_path":"/Users/clawdolf/.hermes/sebos/sebos.db"}
```

- output schema:

```json
{"status":"ok","date":"2026-06-20|null","returncode":0}
```

- error behavior: return no date on error so audio falls through to normal Hermes path.
- test plan: update `test_active_journal_prompt_date_uses_sebos_cli_boundary` to assert facade call instead of raw CLI args.
- rollback plan: old `_active_journal_prompt_date` remains until this slice.

### Behavior target 4: natural-language reminder write, leave until a later slice

- current owner: Photon adapter.
- target owner: likely sebOS plugin/MCP route intent/write API. Do not move in Unit 3.
- proposed function name: `route_natural_intent` or `add_reminder_from_intent`.
- input schema:

```json
{
  "kind":"reminder",
  "title":"File LLC paperwork",
  "due_datetime":"2026-06-22 09:00",
  "location_name":"Office",
  "latitude":"40.7608",
  "longitude":"-111.8910",
  "radius_meters":"150",
  "proximity":"enter",
  "original_text":"remind me Monday to file LLC paperwork",
  "channel":"imessage"
}
```

- output schema:

```json
{"status":"ok|error|needs_clarification","intent":"reminder","reply":"Reminder added: ...","mutated":true,"details":{"writer":{}}}
```

- error behavior: no success ack unless writer status is `ok`; permission/timeouts become `Reminder failed.` without raw tool names.
- test plan: preserve date default matrix and tapback behavior. Later move date/default parsing out of Photon only after parity tests exist.
- rollback plan: keep old `_intent_reminder_args` and `_try_intent_gate` until a separate approved unit.

### Behavior target 5: note/journal/board natural intent route, leave until after explicit route

- current owner: Photon adapter.
- target owner: plugin facade `route_text_command` backed by sebOS `route_text`/CLI.
- input schema:

```json
{"text":"note this under Business: test body","write":true,"channel":"imessage"}
```

- output schema: sebOS command router result.
- error behavior: `dry_run no_appender_wired` still falls through to Hermes for legacy compatibility.
- test plan: preserve `test_intent_to_sebos_text_normalizes_note_and_journal` until the intent text conversion is moved.
- rollback plan: old direct CLI path remains until parity proves safe.

### Behavior target 6: audio journal ingest, leave temporarily in Photon with documented debt

- current owner: Photon adapter.
- target owner: split transport from domain:
  - Photon: attachment detection, media recovery, tapback send.
  - sebOS/plugin/MCP: active prompt probe, inbox retention, ingestion.
- proposed function name later: `ingest_audio_journal_reply`.
- input schema later:

```json
{
  "message_id":"...",
  "space_id":"...",
  "sender_id":"...",
  "timestamp":"...",
  "text":"...",
  "media":[{"path":"/path/to/audio.caf","mime":"audio/x-caf"}],
  "source":"photon"
}
```

- output schema later:

```json
{"status":"ok|ignored|error","inserted":1,"transcribed_ok":1,"reply":"Audio journal saved.","ack_emoji":"❤️"}
```

- error behavior: ignored/no active prompt falls through; transcription failure returns clean copy.
- test plan later: no live send, synthetic audio fixtures only.
- rollback plan: current Photon path remains until a dedicated audio slice.

## C. Unit 3 smallest safe implementation slice

Recommended Unit 3 target: introduce `hermes-sebos` plugin Photon route facade in parallel and route only the explicit sebOS command path through it, with fallback to the old Photon runner.

Exact slice:

1. Add `/Users/clawdolf/.hermes/plugins/hermes-sebos/photon_boundary.py` with async `run_sebos_json` and `route_text_command`.
2. Update `/Users/clawdolf/.hermes/hermes-agent/plugins/platforms/photon/adapter.py` minimally:
   - add a private helper such as `_route_explicit_sebos_command` that tries the plugin facade first,
   - keep `_run_sebos_json` as fallback,
   - change only `_handle_sebos_rules` explicit-command branch (`adapter.py:745-754`) to use that helper,
   - do not touch board, now/next, audio journal, natural intent gate, sidecar, launch/config, or send mechanics.
3. Update `tests/plugins/platforms/photon/test_sebos_rules.py` only enough to prove:
   - explicit command delegates to the new helper/facade,
   - user-facing behavior remains identical,
   - fallback preserves old `_run_sebos_json` behavior if the plugin boundary is unavailable.
4. Add plugin unit tests if practical under the allowed file list in `UNIT3_IMPLEMENTATION_PROMPT.md`, but keep them hermetic with fake subprocess runners. No live Reminders/Notes/iMessages.
5. Run focused tests before and after.
6. Update `MIGRATION_HANDOFF.md` with files changed, tests, rollback notes, and remaining debt.

Why this slice:

- It reduces real boundary debt by moving one Photon -> sebOS CLI route behind a plugin-owned boundary.
- It does not remove the current working behavior.
- It avoids the most dangerous parts first: natural-language date parsing, reminder writes, audio journal ingest, and gateway/runtime config.
- It gives the next slice a pattern for board/journal/natural routing.

Expected remaining debt after Unit 3:

- `_run_sebos_json` remains in Photon as fallback and for other paths.
- Board/now/next still call sebOS directly.
- Active journal prompt and audio journal ingest still call sebOS directly.
- Natural intent gate still owns date/defaulting and direct reminder write.
- Tests still partially encode old Photon domain behavior until each path is migrated.

## D. Explicit no-go list for Unit 3

Unit 3 must not touch:

- Gateway restart, live gateway process, or sidecar process.
- launchd or any `com.sebos.*` job.
- Live iMessage send, live Photon send, Photon cloud/project settings, or auth credentials.
- Live Reminders, Notes, Close, Monarch, Telegram, Calendar, WHOOP, bank/finance, or Apple data mutation.
- Natural-language intent gate semantics, date parser, auxiliary LLM prompt, or reminder writer behavior.
- Board rendering behavior except if explicitly not selected for Unit 3.
- Audio journal ingest path.
- Athena goals/prompt injection.
- Core tool registry/toolsets/platform registry/gateway sanitizer.
- Push, merge, rebase, force-push, stash, or commit.
- Deleting old Photon fallback logic.
- Broad MCP server/config work.

## Unit 3 approval decision

No new Seb architecture decision is required before Unit 3 if Unit 3 is limited to the recommended plugin-facade explicit-command slice with fallback.

Seb approval is required before any scope expansion into:

- MCP server/config,
- reminder writer Terminal fallback changes,
- natural-language reminder write migration,
- audio journal migration,
- gateway restart/live smoke,
- any external mutation.
