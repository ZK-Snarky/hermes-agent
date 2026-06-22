# TARGET_ARCHITECTURE.md

Status: proposed target architecture for migration. Evidence labels: official docs, source code, local convention, or inference.

## Responsibility map

### Hermes core

Responsibility: runtime, gateway runner, sessions, model/tool orchestration, central registry, generic toolset resolution, config/profile handling, memory/skills/cron frameworks, generic platform capability contracts.

Evidence:
- official docs: plugin docs say plugins extend Hermes without modifying core (`website/docs/user-guide/features/plugins.md:8-15`).
- official docs: tools runtime central registry and dispatch (`website/docs/developer-guide/tools-runtime.md:7-18`, `:122-151`).
- official docs: platform adapter architecture goes Platform Adapter -> Gateway Runner -> AIAgent (`website/docs/developer-guide/adding-platform-adapters.md:5-19`).
- source: current platform capability registry fields in `gateway/platform_registry.py:100-177`.

Confidence: high for generic responsibilities; medium for new platform-capability fields because local diff needs maintainer decision.

### Hermes plugin

Responsibility: local/native Hermes extension boundary for narrow sebOS tools, hooks, platform registration, slash commands, bundled skills, and injected context when docs support it.

Evidence:
- official docs: plugin context can register tools/hooks/slash commands/CLI commands/injected messages/bundled skills/platforms (`plugins.md:94-116`).
- source: `/Users/clawdolf/.hermes/plugins/hermes-sebos/__init__.py:21-32` registers `sebos_event`.
- source: `/Users/clawdolf/.hermes/plugins/hermes-sebos/tools.py:219-227` writes event JSON into sebOS inbox.

Confidence: high.

### MCP

Responsibility: broader external/local tool server boundary for sebOS capabilities that are numerous, resource-like, prompt-like, or should be filterable per tool/server.

Evidence:
- official docs: MCP connects Hermes to external tool servers and provides tools/resources/prompts/filtering (`mcp.md:7-20`, `:347-537`).
- official docs: configured MCP servers generate dynamic `mcp-<server>` toolsets (`toolsets-reference.md:119-134`).

Confidence: high. Exact sebOS MCP shape is inference and needs design approval.

### sebOS

Responsibility: local personal OS/domain subsystem: SQLite, goals, journal, Mission Control, Apple Notes/Reminders/Calendar semantics, Close/WHOOP/Monarch/location collectors, deterministic writes, launchd jobs, and local state.

Evidence:
- local convention: `sebos-architecture` skill and `hermes-compatible-sebos-boundaries.md:7-15` define sebOS as separate local subsystem.
- source: `lib/command_router.py:3-7` dry-run default; `:1370-1378` route defaults; write handlers `:606-617`, `:688-705`, `:1180-1257`.
- source: `lib/reminders.py:80-88`, `:99-124`, `:137-148`, `:246-304` owns Reminder read fallback stack.
- source: `lib/reminder_writer.py:239-294`, `:380-437` owns Reminder write provider order/execution.

Confidence: high for source-owned behaviors; medium for architectural wording because it is local convention.

### Photon

Responsibility: iMessage/Spectrum transport/front desk: sidecar lifecycle, inbound stream normalization, outbound send/reply/reaction/attachment/typing mechanics, allowlist/mention gating, retries, platform-specific formatting and generic clean failure copy.

Evidence:
- official Hermes docs: Photon sidecar long-lived stream, inbound NDJSON, outbound sidecar POST (`photon.md:23-40`).
- official Hermes docs: Photon auth/allowlist/group mention/attachments/env vars (`photon.md:84-143`, `:194-226`).
- official adapter docs: adapters implement connect/disconnect/send and forward inbound via `handle_message(event)` (`adding-platform-adapters.md:15-30`).
- Photon official index: Spectrum supports messages, reactions/replies, typing, iMessage connection/routing/features (https://docs.photon.codes/llms.txt, HTTP 200).

Confidence: high for transport duties; high that docs do not require sebOS policy in Photon; medium on provider-specific SDK details until deeper Photon docs/source are read before implementation.

### Athena

Responsibility: user-facing operator/persona, final judgment layer, synthesis, prioritization, decision quality, concise copy. Athena is not a separate runtime and should not become a second transport stack.

Evidence:
- local convention: `athena-hermes-goals-photon-operationalization-20260621.md:5-10` and `mission-control-apple-notes-reminders.md:5-15` define Athena as operator, Hermes as runtime, sebOS as state/action, Photon as transport.
- inference from official docs: Hermes provides runtime/platform/tools; persona can be config/SOUL/system prompt/skills/memory, not core code.

Confidence: medium. Official Hermes docs do not know Seb’s Athena persona.

### Config/profile/skills/memory

Responsibility: stable settings, platform config, profile isolation, procedural knowledge, and durable user/operator facts. Not a substitute for deterministic sebOS writes.

Evidence:
- official config docs: state under `~/.hermes`, precedence, secrets vs config (`configuration.md:7-60`).
- official profiles docs: independent configs/API keys/memory/sessions/skills/gateway state; `HERMES_HOME` (`profiles.md:5-13`, `:270-302`).
- official skills docs: progressive-disclosure knowledge docs (`skills.md:7-13`, `:74-121`).
- official memory docs: built-in memory injected at session start; writes appear next session (`memory.md:7-20`, `:32-64`).

Confidence: high.

### launchd vs Hermes cron

Responsibility: launchd owns local macOS scheduled collectors and deterministic sebOS routines. Hermes cron owns agent-scheduled reasoning jobs and message delivery through gateway.

Evidence:
- official cron docs: cron starts fresh agent sessions and delivers final responses through gateway (`cron.md:201-258`).
- local sebOS skill: launchd jobs for `com.sebos.*` collectors and prompts; duplicate scheduler warning.

Confidence: medium-high. Official Hermes docs define cron; local convention defines launchd ownership.

## Message flows

### 1. “hey what reminders do i have”

Target flow:
- Transport: Photon sidecar receives iMessage and adapter normalizes to `MessageEvent`.
- Routing: casual prefix stripped by sebOS/Hermes-compatible intent layer, not by hardcoded domain code in Photon long-term. Initial compatibility may call a plugin/MCP route.
- Boundary: Hermes calls `hermes-sebos` plugin or sebOS MCP `reminders_read` tool/resource.
- sebOS entrypoint: sebOS Reminders read abstraction, not raw adapter shell. Current implementation can use `lib/reminders.py` fallback stack.
- Reply: Athena/Hermes final copy says “Today…”/“This week…” without `remindctl`, shell, PATH, or tool exposure.
- Errors handled: sebOS/plugin/MCP returns structured failure; gateway/platform sanitizer hides raw plumbing.
- Never shown: `shell not exposed`, `remindctl`, `/opt/homebrew/bin`, TCC stack traces.

Evidence: Photon docs `photon.md:23-40`; platform flow `adding-platform-adapters.md:15-30`; sebOS read source `lib/reminders.py:80-304`; local test result `46 passed`.

### 2. “remind me tomorrow at 9 to file LLC paperwork”

Target flow:
- Transport: Photon normalizes inbound.
- Routing: high-confidence reminder write routed through Hermes/Athena tool call, plugin, or sebOS MCP; if ambiguity exists, Athena asks concise clarification.
- Boundary: tool call to sebOS reminder write, not Photon adapter subprocess.
- sebOS entrypoint: `lib/reminder_writer.py` or CLI wrapper with event-primary write and remindctl fallback if allowed.
- Reply: 👍 tapback or short success text; failure is non-technical.
- Errors handled: sebOS refuses ambiguous/unsafe writes; adapter handles transport send/reaction failures only.
- Never shown: provider command names unless Seb is debugging.

Evidence: plugin/MCP docs; sebOS writer source `lib/reminder_writer.py:239-294`, `:380-437`; local convention on reminder writes.

### 3. “board”

Target flow:
- Transport: Photon.
- Routing: deterministic read intent to sebOS board/status capability through plugin/MCP.
- Boundary: Hermes tool/plugin/MCP call.
- sebOS entrypoint: Mission Control/Live Board renderer/status command, not Photon-specific parsing.
- Reply: concise board projection.
- Errors handled: sebOS returns structured unavailable/stale state; Athena explains actionably.
- Never shown: SQLite paths, Apple Notes raw errors unless debugging.

Evidence: local convention in sebOS skill; official plugin/MCP extension points.

### 4. “note this…”

Target flow:
- Transport: Photon.
- Routing: clear note/journal write goes through Athena/tool boundary. If vague, normal Athena conversation or clarification.
- Boundary: plugin/MCP `note_write` or `journal_write`.
- sebOS entrypoint: Mission Control Apple Notes/journal command router.
- Reply: short success ack/tapback.
- Errors handled: sebOS write gate returns structured failure; user copy hides raw AppleScript/JXA/CLI names.
- Never shown: local file paths, command output, tool exposure.

Evidence: plugin/MCP docs; source `lib/command_router.py:606-617` and local Mission Control convention.

### 5. Normal conversation

Target flow:
- Transport: Photon.
- Routing: no deterministic local intent; pass to normal Gateway Runner/AIAgent.
- Boundary: normal model/tools as enabled for platform.
- sebOS entrypoint: none unless Athena calls tool.
- Reply: Athena operator style.
- Errors handled: gateway session/tool error path sanitized for clean inbox.
- Never shown: generic “tool not exposed” plumbing.

Evidence: gateway internals `gateway-internals.md:52-67`; platform docs.

### 6. Complex request requiring full Athena reasoning

Target flow:
- Transport: Photon.
- Routing: full Hermes/Athena session, not lightweight sebOS command router.
- Boundary: Athena may call plugin/MCP/core tools as needed.
- sebOS entrypoint: only for relevant local state/action.
- Reply: final judgment, concise but capable.
- Errors handled: tool failures summarized with next action.
- Never shown: raw traces, unless Seb explicitly asks for debug.

Evidence: official runtime/tool docs and Athena local convention.

### 7. Audio/journal input

Target flow:
- Transport: Photon/Spectrum attachment/voice handling.
- Routing: sidecar/adapter identifies audio transport shape; STT/transcript goes through Hermes/Athena or high-confidence journal gate depending active prompt window.
- Boundary: audio bytes cached/inboxed by transport; journal write through sebOS plugin/MCP/CLI boundary.
- sebOS entrypoint: journal ingestion or audio journal path.
- Reply: ❤️ or short “Audio journal saved” when saved; ask clarification or normal reply otherwise.
- Errors handled: audio recovery/attachment failures in transport; transcript/journal semantics in sebOS/Athena.
- Never shown: object replacement markers, cache paths, SDK internals.

Evidence: Photon docs attachments metadata/outbound support `photon.md:194-207`; Photon official index voice/attachments; local source current adapter audio ingestion `adapter.py:669-680`; local convention `photon-marker-audio-journal-recovery.md:18-39`.

## What official docs support

- Plugins and MCP are documented extension points for local/external tools.
- Platform adapters are documented as messaging transport adapters connected to gateway/AIAgent.
- Photon is documented as iMessage sidecar/transport, not a sebOS policy engine.
- Config/profiles/skills/memory/cron have documented roles.

## Local conventions

- Athena as persona/operator.
- sebOS as durable personal OS and Apple/local domain authority.
- Photon transport-only for Seb’s system.
- launchd owns sebOS local schedules.

## Unresolved

- Whether to implement sebOS as plugin-only, MCP-only, or hybrid.
- Whether `include_in_messaging_toolsets` should be upstreamed.
- Whether current Athena goals injection should move immediately or remain temporary local fork debt.
- Whether reminder writer Terminal fallback is acceptable in any non-interactive path.
