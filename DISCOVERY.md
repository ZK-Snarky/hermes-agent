# DISCOVERY.md

Scope: read-only discovery and classification for the Athena/Hermes/sebOS/Photon migration. No implementation, no gateway restart, no live iMessage, no launchd change.

## Branch and status summary

### Hermes repo

Path: `/Users/clawdolf/.hermes/hermes-agent`

Commands run:

```bash
cd /Users/clawdolf/.hermes/hermes-agent
git branch --show-current
git status --short
git diff --stat
git diff --name-status
```

Observed branch: `clean-stock`

Dirty worktree:

```text
 M agent/agent_init.py
 M agent/prompt_builder.py
 M agent/system_prompt.py
 M gateway/platform_registry.py
 M gateway/run.py
 M gateway/session.py
 M hermes_cli/plugins.py
 M plugins/platforms/photon/adapter.py
 M tests/agent/test_prompt_builder.py
 M tests/agent/test_system_prompt.py
 M tests/gateway/test_session.py
 M tests/gateway/test_telegram_noise_filter.py
 M tests/plugins/platforms/photon/test_intent_gate.py
 M tests/plugins/platforms/photon/test_shared_cloud_guard.py
 M tests/test_toolsets.py
 M tests/tools/test_sebos_event.py
 M tools/registry.py
D  tools/sebos_event.py
 M toolsets.py
?? gateway/outbound_sanitize.py
?? tests/gateway/test_platform_capabilities.py
```

Diff stat: 18 tracked files changed, 552 insertions, 112 deletions.

### sebOS repo

Path: `/Users/clawdolf/.hermes/sebos`

Observed branch: `main`

Dirty worktree:

```text
 M lib/command_router.py
 M lib/reminders.py
 M tests/test_command_router.py
?? bin/sebos-journal-pending-prompt
```

Diff stat: 3 tracked files changed, 213 insertions, 27 deletions.

### sebOS plugin

Path: `/Users/clawdolf/.hermes/plugins/hermes-sebos`

`git status` failed because this directory is not a git repository. Treat it as active runtime plugin code without repo-local rollback until exported or committed elsewhere.

## Current test evidence

```bash
cd /Users/clawdolf/.hermes/hermes-agent
python -m pytest tests/plugins/platforms/photon/test_sebos_rules.py tests/plugins/platforms/photon/test_intent_gate.py tests/test_toolsets.py tests/tools/test_sebos_event.py -q -o 'addopts='
```

Result: `60 passed in 2.33s`.

```bash
cd /Users/clawdolf/.hermes/sebos
python3 -m pytest tests/test_command_router.py -q
```

Result: `46 passed in 0.07s`.

Environment probe:

```text
whoami -> clawdolf
stat -f%Su /dev/console -> clawdolf
gui domain OK
```

## File classification

| file | classification | evidence |
|---|---|---|
| `tools/sebos_event.py` | MOVE_TO_PLUGIN | Deleted from core. Docs: custom/local tools should use plugins (`DOCS_EVIDENCE: Custom tools`). Plugin registers `sebos_event` at `/Users/clawdolf/.hermes/plugins/hermes-sebos/__init__.py:21-32`. Inference: deletion is correct only if plugin loads reliably. |
| `toolsets.py` | KEEP_IN_CORE or UPSTREAMABLE_GENERIC | Adds plugin-tool inclusion into core-family toolsets at `toolsets.py:576-588`, `:724-729`; docs support toolsets and plugin-registered toolsets (`DOCS_EVIDENCE: Toolsets`). Risk: name `include_in_messaging_toolsets` may actually affect `_HERMES_CORE_FAMILY`, not only messaging. |
| `tools/registry.py` | KEEP_IN_CORE or UPSTREAMABLE_GENERIC | Adds `include_in_messaging_toolsets` to `ToolEntry` and `registry.register`, `tools/registry.py:80-105`, `:248-277`; docs support registry fields generally but not this exact flag. Needs maintainer decision/upstream framing. |
| `plugins/platforms/photon/adapter.py` | MOVE_TO_PHOTON_TRANSPORT_ONLY, MOVE_DOMAIN_OUT | Official adapter docs define transport adapter role. Current file hardcodes sebOS paths `adapter.py:92-96`, runs sebOS subprocess `:388-424`, calls `sebos-route-command --write` `:745-753`, `:1119-1127`, direct reminder writer `:1091-1096`, audio journal ingestion `:669-680`, and short-circuits before Hermes `:1687-1709`. |
| `gateway/platform_registry.py` | KEEP_IN_CORE if generic | Adds platform capabilities such as clean-inbox/sanitizer/hints; platform registration docs support platform metadata (`DOCS_EVIDENCE: Platform plugin path`). Source fields `platform_registry.py:100-177`. Generic capability is upstreamable if not Photon/Seb-specific. |
| `gateway/outbound_sanitize.py` | KEEP_IN_CORE if generic, else MOVE_TO_PLATFORM | Untracked. Generic redaction/suppression may belong in gateway core if cross-platform; Photon-specific phrases should live in Photon adapter or plugin. Source: `gateway/outbound_sanitize.py:1-33`; gateway use `gateway/run.py:343-380`. |
| `gateway/run.py` | KEEP_IN_CORE for generic capability, REVERT_IN_CORE for Seb-specific | Uses platform capabilities/sanitizer and suppresses clean-inbox status/progress `gateway/run.py:343-401`, home-channel nag `:9362-9373`. If branches are generic platform registry behavior, keep/upstream. If Photon hardcodes remain, move/revert. |
| `gateway/session.py` | UNKNOWN | Modified; subagent saw `gateway/session.py` modified and test changes. Needs line-level diff review before implementation. Likely session/platform metadata. |
| `hermes_cli/plugins.py` | KEEP_IN_CORE if generic | Modified to support plugin/platform surfacing. Need inspect diff before implementation. Docs support plugin management commands. |
| `agent/agent_init.py` | MOVE_TO_CONFIG_OR_PLUGIN for Athena goals | Reads sebOS goals file at `agent/agent_init.py:1273-1295`; docs support config/profile and context provider plugins, not hardcoded sebOS. Inference: current implementation works but is local fork debt unless plugin/config context owns it. |
| `agent/prompt_builder.py` | MOVE_TO_CONFIG_OR_PLUGIN if Seb-specific | Modified prompt assembly. Docs: memory injected at session start; skills/config/context engine supported. Need classify exact diff. Athena goals/context should avoid hardcoded core. |
| `agent/system_prompt.py` | KEEP_IN_CORE for platform hints; MOVE_TO_CONFIG_OR_PLUGIN for Athena | Platform hints from registry `agent/system_prompt.py:382-400`; Athena goals block included `:421-426`. Platform hint support can be generic; Athena goals injection is local. |
| `tests/agent/test_prompt_builder.py` | TEST_ONLY | Covers prompt injection/platform behavior. Keep or adjust to target boundary. |
| `tests/agent/test_system_prompt.py` | TEST_ONLY | Covers platform hints/goals. Keep generic tests; move local Athena tests to plugin/config if migration moves code. |
| `tests/gateway/test_session.py` | TEST_ONLY | Verify session behavior. Keep if generic. |
| `tests/gateway/test_telegram_noise_filter.py` | TEST_ONLY | May cover clean-inbox/noise filtering. Generic gateway tests can remain. |
| `tests/gateway/test_platform_capabilities.py` | TEST_ONLY | Untracked. Likely supports generic platform capability contract. Keep if core capability accepted. |
| `tests/plugins/platforms/photon/test_intent_gate.py` | TEST_ONLY, later MOVE_DOMAIN_TESTS | Current tests prove existing Photon sebOS routing. If moving domain out, preserve behavior in plugin/MCP/sebOS tests and leave adapter tests for transport handoff. |
| `tests/plugins/platforms/photon/test_sebos_rules.py` | TEST_ONLY, later MOVE_DOMAIN_TESTS | Valid regression for current issue, but it may lock domain policy into Photon adapter unless rewritten around boundary. |
| `tests/plugins/platforms/photon/test_shared_cloud_guard.py` | TEST_ONLY | Photon transport/auth safety. Keep in Photon adapter tests. |
| `tests/test_toolsets.py` | TEST_ONLY | Verifies toolset registry behavior. Keep if generic toolset change stays. |
| `tests/tools/test_sebos_event.py` | TEST_ONLY, MOVE_TO_PLUGIN_TEST | If `sebos_event` is plugin-owned, test should live with plugin or test plugin discovery, not core tool module. |
| `lib/command_router.py` | MOVE_TO_SEBOS | sebOS owns deterministic local domain routing. Source doc says dry-run default prevents unintended writes `lib/command_router.py:3-7`; API defaults dry-run/no-write `:1370-1378`; handlers perform writes when enabled `:606-617`, `:688-705`, `:1180-1257`. |
| `lib/reminders.py` | MOVE_TO_SEBOS | sebOS owns Apple Reminders read semantics. Source resolves `remindctl` path `lib/reminders.py:80-88`, JXA fallback `:99-124`, read-only SQLite fallback `:137-148`, fallback order `:246-304`. |
| `lib/reminder_writer.py` | MOVE_TO_SEBOS but HARDEN | sebOS owns write semantics. Source uses subprocess `:22-30`, Terminal fallback `:33-48`, provider order `:380-388`, command execution `:415-437`. High-risk local side-effect boundary. |
| `bin/sebos-journal-pending-prompt` | MOVE_TO_SEBOS | Untracked sebOS CLI. Needs inspection before implementation. |
| `/Users/clawdolf/.hermes/plugins/hermes-sebos/plugin.yaml` | MOVE_TO_PLUGIN | Plugin surface should be the Hermes boundary for native sebOS tools. Need export/versioning because no git repo. |
| `/Users/clawdolf/.hermes/plugins/hermes-sebos/tools.py` | MOVE_TO_PLUGIN | Plugin writes events into sebOS inbox `tools.py:219-227`, default path `:74-75`. Good narrow boundary, but path/profile handling needs review. |

## Boundary-violation hotspots ranked

1. HIGH: Photon adapter directly shells into sebOS and owns reminder/note/journal/board routing. Evidence: `adapter.py:92-96`, `:388-424`, `:669-680`, `:745-753`, `:1091-1096`, `:1119-1127`, `:1687-1709`. Official adapter docs describe adapter as transport normalization/send boundary, not personal OS policy.
2. HIGH: Photon intent gate can mutate sebOS before Hermes/Athena tool layer sees the message. Evidence: config/env flags `adapter.py:249-255`, classifier prompt `:943-969`, writes `:1091-1127`, pre-agent short circuit `:1687-1707`.
3. HIGH: sebOS reminder writer Terminal fallback launches executable `.command` files via macOS `open`. Evidence: `lib/reminder_writer.py:33-48`, defaults `:84-100`, `:336-357`. This may be acceptable as sebOS-owned local fallback, but it should never be exposed as Photon adapter plumbing or user-facing error copy.
4. MEDIUM: `include_in_messaging_toolsets` is core bridge behavior that may expose plugin tools to `_HERMES_CORE_FAMILY`, not only messaging. Evidence: `toolsets.py:576-588`, `:724-729`; `tools/registry.py:80-105`, `:248-277`.
5. MEDIUM: Athena goals injection currently lives in core prompt assembly. Evidence: `agent/agent_init.py:1273-1295`, `agent/system_prompt.py:421-426`. Target likely config/context-provider/plugin rather than hardcoded core.
6. MEDIUM: outbound sanitizer location is unresolved. Source: `gateway/outbound_sanitize.py:1-33`, `gateway/run.py:343-380`, Photon registration `adapter.py:2739-2744`. Generic redaction belongs in gateway; Photon-specific “clean inbox”/copy policy should be platform capability or plugin.
7. LOW/MEDIUM: Reminder reads still use `remindctl`, JXA, and SQLite fallback. Since read-only and sebOS-owned, this is acceptable collector behavior if user copy never leaks tool names.

## Stale language and tooling risks

- `remindctl`: acceptable inside sebOS collectors/writer fallback if hidden behind sebOS API. Risk if Photon/Hermes replies mention it or adapter directly depends on it. Recent fix added absolute fallback `/opt/homebrew/bin/remindctl`; source supports path resolution in `lib/reminders.py:80-88`.
- `shell-not-exposed`: no grep matches found in Hermes/sebOS/plugin. The bad copy may come from model response under missing tool surface, not static string.
- `tool-denial`: no grep matches found in Hermes/sebOS/plugin.
- generic tool denial: must be handled by routing and sanitizer. User-facing Photon replies should never mention shell, local PATH, remindctl, or tool exposure.
- old Photon test behavior: `test 123` exact no relevant hits; `test123` only generic fixtures. No active hardcoded old ack found in greps.
- launchd PATH: current sebOS `lib/reminders.py` uses absolute candidate `/opt/homebrew/bin/remindctl`; tests passed. Keep launchd stripped PATH regression.

## Open questions for Seb

- Should the first implementation unit remove all sebOS routing from Photon at once, or create a compatibility shim in plugin/MCP first and then flip Photon over?
- Does Seb want `hermes-sebos` to stay as a user plugin only, or should broader sebOS be exposed as an MCP server with resources/prompts?
- Is the Terminal fallback in `reminder_writer.py` still acceptable, or should it be disabled from any non-interactive/Photon path?
- Should Athena goals injection be accepted as local fork debt temporarily while Photon is de-domained, or moved in the first implementation unit?
- Should `include_in_messaging_toolsets` be prepared as upstream PR, or treated as local-only bridge pending maintainer decision?
