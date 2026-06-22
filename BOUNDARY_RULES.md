# BOUNDARY_RULES.md

Each rule includes evidence or is labeled local convention/inference.

1. Photon adapter must not contain sebOS/Athena domain policy unless an official Photon/Hermes doc explicitly requires that policy at the platform layer.
   - Evidence: platform adapter docs define adapter flow and methods as connect/disconnect/send/typing/chat info/inbound `handle_message` (`adding-platform-adapters.md:15-30`). Photon docs define sidecar transport (`photon.md:23-40`).
   - Status: official docs + inference.

2. Photon adapter must not directly shell out to sebOS commands for reminders, notes, journal, board, or goals in the target state.
   - Evidence: plugin/MCP docs provide documented extension points for tools outside core (`plugins.md:94-116`, `mcp.md:7-20`). Current direct calls are in `adapter.py:388-424`, `:745-753`, `:1091-1096`, `:1119-1127`.
   - Status: inference from official docs + local convention.
   - Exception: temporary compatibility shim allowed only inside a migration unit with tests and removal target.

3. Hermes core must not hardcode Seb/Athena/sebOS-specific behavior.
   - Evidence: docs recommend plugins for custom tools (`adding-tools.md:9-21`); local AGENTS says core is narrow and capability lives at edges. Current concern: goals injection `agent/agent_init.py:1273-1295`, `agent/system_prompt.py:421-426`.
   - Status: official docs + source + local convention.

4. sebOS owns Apple Reminders/Notes/Calendar semantics.
   - Evidence: sebOS source owns reminders read fallback `lib/reminders.py:80-304`, writer provider order `lib/reminder_writer.py:239-437`, command router write gates `lib/command_router.py:606-705`.
   - Status: source + local convention.

5. Hermes should call sebOS through documented plugin/MCP/tool boundaries.
   - Evidence: plugin docs `plugins.md:94-116`; MCP docs `mcp.md:7-20`, `:347-537`; tools runtime docs `tools-runtime.md:122-151`.
   - Status: official docs.

6. User-facing Photon replies must never mention raw shell, `remindctl`, local PATH, TCC stack traces, CLI exposure, or tool exposure unless Seb explicitly asks for debug output.
   - Evidence: clean-inbox/sanitizer currently exists in source `gateway/run.py:343-380`, `adapter.py:100-120`; bad-copy risk from audit. Official docs do not define this UX; it is local convention.
   - Status: local convention, supported by source direction.

7. Reminder writes remain event/sebOS-primary where current code supports it.
   - Evidence: `lib/reminder_writer.py:239-285` event args; `:288-294` remindctl fallback; `:380-388` provider order.
   - Status: source + local convention.

8. Reminder reads may use `remindctl` only behind sebOS read abstraction; audit whether read path should become an MCP/plugin resource instead of Photon shelling.
   - Evidence: `lib/reminders.py:80-88` absolute `remindctl` fallback; `:99-124` JXA; `:137-148` read-only SQLite fallback; `:246-304` fallback order.
   - Status: source + inference.

9. Every local Hermes core patch must be classified as upstreamable, temporary, moved, reverted, or accepted local fork debt before update/rebase.
   - Evidence: Hermes boundary migration skill; official docs support plugin/MCP/config alternatives. Current dirty core files listed in `DISCOVERY.md`.
   - Status: local convention + docs basis.

10. Every migration unit must be reversible and tested.
    - Evidence: contribution guidance in `AGENTS.md`; tests run in this audit passed. Migration plan must include rollback steps and commands.
    - Status: source/local convention.

11. Generic platform behavior can live in Hermes core only if it is not Photon/Seb-specific.
    - Evidence: platform registry docs and current `gateway/platform_registry.py:100-177`; gateway usage `gateway/run.py:343-401`.
    - Status: inference from official platform docs.

12. Outbound sanitizer split: generic redaction/suppression can be core; Photon/Athena copy policy belongs in platform capability or plugin; sebOS errors should be normalized before they reach user copy.
    - Evidence: untracked `gateway/outbound_sanitize.py:1-33`, Photon sanitizer `adapter.py:100-120`, gateway platform registry use.
    - Status: inference, needs maintainer decision.

13. launchd and Hermes cron must not duplicate sebOS live sends.
    - Evidence: official cron docs define gateway fresh-agent jobs (`cron.md:201-258`); local sebOS skill documents launchd `com.sebos.*` jobs and duplicate scheduler risk.
    - Status: local convention + official cron docs.

14. Photon/Spectrum SDK-level changes require reading official Photon docs and installed package source/types first.
    - Evidence: `AGENTS.md` non-negotiable external SDK rule; Photon official index at https://docs.photon.codes/llms.txt.
    - Status: source + official Photon docs index.

15. Tests must assert behavior at the new boundary, not preserve the old boundary leak.
    - Evidence: current Photon tests passed but may encode domain policy in adapter; official docs support plugin/MCP boundaries.
    - Status: inference.
