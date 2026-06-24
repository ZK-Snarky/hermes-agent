from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageType
from plugins.platforms.photon import adapter as adapter_module
from plugins.platforms.photon.adapter import PhotonAdapter


def _make_adapter(monkeypatch: pytest.MonkeyPatch, extra: dict | None = None) -> PhotonAdapter:
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: None)
    cfg = PlatformConfig(enabled=True, token="", extra=extra or {"sebos_rules": True})
    return PhotonAdapter(cfg)


def test_sebos_fallback_allowlist_is_exact() -> None:
    assert adapter_module._SEBOS_FALLBACK_COMMAND_ALLOWLIST == frozenset(
        {
            "sebos-route-command",
            "sebos-board-query",
            "sebos-render-mission-control",
            "sebos-journal-pending-prompt",
            "sebos-add-reminder",
            "sebos-ingest-journal",
        }
    )


@pytest.mark.asyncio
async def test_run_sebos_json_rejects_non_allowlisted_command(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    result = await adapter._run_sebos_json("sebos-dangerous-new-command")

    assert result == {
        "status": "error",
        "error_layer": "router",
        "error": "sebOS fallback command not allowed",
        "returncode": 126,
    }


def test_photon_adapter_has_no_non_allowlisted_literal_sebos_fallback_calls() -> None:
    adapter_path = Path(adapter_module.__file__)
    tree = ast.parse(adapter_path.read_text())
    illegal: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "_run_sebos_json":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        command = node.args[0].value
        if isinstance(command, str) and command.startswith("sebos-"):
            if command not in adapter_module._SEBOS_FALLBACK_COMMAND_ALLOWLIST:
                illegal.append((node.lineno, command))
    assert illegal == []


@pytest.mark.asyncio
async def test_sebos_rules_unknown_text_falls_through_to_hermes(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"intent": "unknown", "status": "ok", "reply": ""}

    sent = []

    async def fake_send(space_id: str, text: str) -> None:
        sent.append((space_id, text))

    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="random normal chat",
        mtype=MessageType.TEXT,
        media_urls=[],
        media_types=[],
    )

    assert result is None
    assert calls == []
    assert sent == []


@pytest.mark.asyncio
async def test_sebos_rules_board_routes_through_boundary_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    boundary_calls = []

    class FakeBoundary:
        async def board_query(self, command: str, *, timeout=25.0):
            boundary_calls.append((command, timeout))
            return {"status": "ok", "body": "BOARD\n\nNOW\n- call lead\n\nNEXT\n- prep"}

    async def fake_run(*args, stdin=None, timeout=20.0):
        raise AssertionError("board should use plugin boundary first")

    sent = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: FakeBoundary())
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="board",
        mtype=MessageType.TEXT,
        media_urls=[],
        media_types=[],
    )

    assert result == "handled"
    assert boundary_calls == [("snapshot", 25.0)]
    assert sent == [("space-1", "BOARD\n\nNOW\n- call lead\n\nNEXT\n- prep", "msg-1")]


@pytest.mark.asyncio
async def test_sebos_rules_next_falls_back_to_old_mission_control_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"status": "ok", "next": ["prep", "follow up"]}

    sent = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: None)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="next",
        mtype=MessageType.TEXT,
        media_urls=[],
        media_types=[],
    )

    assert result == "handled"
    assert calls == [(("sebos-board-query", "--json", "next"), None, 25.0)]
    assert sent == [("space-1", "- prep\n- follow up", "msg-1")]


@pytest.mark.asyncio
async def test_sebos_rules_natural_agenda_routes_to_sebos_not_hermes(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    boundary_calls = []

    class FakeBoundary:
        async def route_text_command(self, text, *, write=True, db_path=None, channel="imessage", timeout=45.0):
            boundary_calls.append((text, write, db_path, channel, timeout))
            return {
                "intent": "board_next",
                "status": "ok",
                "reply": "Falconnect: verify Re-Engage Safe to Export",
            }

    sent = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: FakeBoundary())
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="Whats next on the agenda for falconnect",
        mtype=MessageType.TEXT,
        media_urls=[],
        media_types=[],
    )

    assert result == "handled"
    assert boundary_calls == [
        (
            "Whats next on the agenda for falconnect",
            True,
            str(adapter_module._SEBOS_DB_PATH),
            "imessage",
            45.0,
        )
    ]
    assert sent == [("space-1", "Falconnect: verify Re-Engage Safe to Export", "msg-1")]


@pytest.mark.asyncio
async def test_sebos_rules_calendar_and_location_route_to_board_context(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    calls = []

    async def fake_route(text, *, write=True, db_path=None, channel="imessage", timeout=45.0):
        calls.append(text)
        if "calendar" in text.lower():
            return {"intent": "calendar_read", "status": "ok", "reply": "Calendar: lead call"}
        return {"intent": "location_read", "status": "ok", "reply": "Last location: Home."}

    class FakeBoundary:
        route_text_command = staticmethod(fake_route)

    sent = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: FakeBoundary())
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)

    for text in ("what's on my calendar?", "where am I?"):
        assert await adapter._handle_sebos_rules(
            space_id="space-1",
            message_id="msg-1",
            text=text,
            mtype=MessageType.TEXT,
            media_urls=[],
            media_types=[],
        ) == "handled"

    assert calls == ["what's on my calendar?", "where am I?"]
    assert sent == [
        ("space-1", "Calendar: lead call", "msg-1"),
        ("space-1", "Last location: Home.", "msg-1"),
    ]


@pytest.mark.asyncio
async def test_sebos_rules_explicit_command_routes_through_boundary_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    boundary_calls = []

    class FakeBoundary:
        async def route_text_command(self, text, *, write=True, db_path=None, channel="imessage", timeout=45.0):
            boundary_calls.append((text, write, db_path, channel, timeout))
            return {"intent": "reminder", "status": "ok", "reply": "Reminder set."}

    async def fake_run(*args, stdin=None, timeout=20.0):
        raise AssertionError("explicit commands should use plugin boundary first")

    sent = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: FakeBoundary())
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="reminder: tomorrow at 9 call Chaz",
        mtype=MessageType.TEXT,
        media_urls=[],
        media_types=[],
    )

    assert result == "handled"
    assert boundary_calls == [
        (
            "reminder: tomorrow at 9 call Chaz",
            True,
            str(adapter_module._SEBOS_DB_PATH),
            "imessage",
            45.0,
        )
    ]
    assert sent == [("space-1", "Reminder set.", "msg-1")]


@pytest.mark.asyncio
async def test_sebos_rules_explicit_command_falls_back_to_old_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"intent": "reminder", "status": "ok", "reply": "Reminder set."}

    sent = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: None)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="reminder: tomorrow at 9 call Chaz",
        mtype=MessageType.TEXT,
        media_urls=[],
        media_types=[],
    )

    assert result == "handled"
    assert calls == [
        (
            ("sebos-route-command", "--text", "-", "--write", "--db", str(adapter_module._SEBOS_DB_PATH), "--json"),
            "reminder: tomorrow at 9 call Chaz",
            45.0,
        )
    ]
    assert sent == [("space-1", "Reminder set.", "msg-1")]


@pytest.mark.asyncio
async def test_sebos_rules_blocked_reminder_update_sends_clean_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit regression: the live-failing 'adjust llc reminder ...' phrase,
    when Reminders access is blocked, must reach iMessage as clean copy and
    never leak 'Terminal fallback timed out' or any raw command/stderr text."""
    adapter = _make_adapter(monkeypatch)

    class FakeBoundary:
        async def route_text_command(self, text, *, write=True, db_path=None, channel="imessage", timeout=45.0):
            # Shape now produced by the fixed sebOS command_router for a
            # permission-blocked update: clean reply, raw details kept for logs.
            return {
                "intent": "reminder_update",
                "status": "error",
                "error_layer": "reminders",
                "reply": "I can't reach Reminders right now — access is blocked on the Mac, so nothing was changed.",
                "details": {
                    "writer": {
                        "status": "permission_denied",
                        "list_outcome": {"returncode": 124, "stderr": "Terminal fallback timed out"},
                    }
                },
            }

    sent = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: FakeBoundary())
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="hey can you adjust llc reminder to next wednesday",
        mtype=MessageType.TEXT,
        media_urls=[],
        media_types=[],
    )

    assert result == "handled"
    assert len(sent) == 1
    body = sent[0][1].lower()
    assert "access is blocked" in body
    for leak in ("terminal fallback", "remindctl", "access denied", "returncode", "traceback", "stderr"):
        assert leak not in body


@pytest.mark.asyncio
async def test_send_quiet_sanitizes_internal_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    """_send_quiet must run the outbound sanitizer so sebOS rule replies get
    the same secret-redaction / internal-notice scrub as gateway replies."""
    adapter = _make_adapter(monkeypatch)
    captured = []

    class _Ok:
        success = True
        error = None

    async def fake_retry(chat_id, text, *, reply_to=None, max_retries=3, base_delay=2.0):
        captured.append(text)
        return _Ok()

    monkeypatch.setattr(adapter, "_send_with_retry", fake_retry)
    await adapter._send_quiet("space-1", "internal tool_call chatter leaked")
    assert captured == ["Received."]


@pytest.mark.asyncio
async def test_sebos_rules_natural_reminder_add_routes_to_sebos_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the LLM intent gate disabled, a deterministic 'remind me ...' add
    routes through the single sebOS command_router (which owns date reasoning
    and one-shot clarification), not the dead Athena path."""
    adapter = _make_adapter(monkeypatch)
    routed = []

    class FakeBoundary:
        async def route_text_command(self, text, *, write=True, db_path=None, channel="imessage", timeout=45.0):
            routed.append(text)
            return {"intent": "reminder", "status": "ok", "mutated": True, "reply": "Reminder added: file llc paperwork (monday at 9am)."}

    sent = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    # No ack reaction for this adapter, so the reply is sent as text.
    async def no_ack(*args, **kwargs):
        return False

    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: FakeBoundary())
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)
    monkeypatch.setattr(adapter, "_send_ack_reaction", no_ack)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="remind me monday to file llc paperwork",
        mtype=MessageType.TEXT,
        media_urls=[],
        media_types=[],
    )

    assert result == "handled"
    assert routed == ["remind me monday to file llc paperwork"]
    assert sent and "reminder added" in sent[0][1].lower()


@pytest.mark.asyncio
async def test_sebos_rules_journal_routes_and_replies_once(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)

    async def fake_run(*args, stdin=None, timeout=20.0):
        return {"intent": "journal", "status": "ok", "reply": "Journal saved."}

    sent = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: None)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="j: done working",
        mtype=MessageType.TEXT,
        media_urls=[],
        media_types=[],
    )

    assert result == "handled"
    assert sent == [("space-1", "Journal saved.", "msg-1")]


@pytest.mark.asyncio
async def test_sebos_rules_explicit_assistant_escape_hatch(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)

    async def fake_run(*args, stdin=None, timeout=20.0):
        raise AssertionError("sebOS router should not run for explicit assistant escape hatch")

    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="h: answer normally",
        mtype=MessageType.TEXT,
        media_urls=[],
        media_types=[],
    )

    assert result == "answer normally"


@pytest.mark.asyncio
async def test_sebos_rules_audio_falls_through_to_hermes(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    adapter = _make_adapter(monkeypatch)
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"fake-audio")

    async def fake_run(*args, stdin=None, timeout=20.0):
        raise AssertionError("audio should not short-circuit through sebOS router")

    async def fake_send(space_id: str, text: str) -> None:
        raise AssertionError("audio should not send a deterministic sebOS ack")

    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="h: caption should not override audio",
        mtype=MessageType.VOICE,
        media_urls=[str(audio)],
        media_types=["audio/mp4"],
    )

    assert result is None



def test_intent_due_datetime_defaults_date_only_and_midnight_to_9am() -> None:
    assert (
        PhotonAdapter._intent_due_datetime(
            {"due_datetime": "2026-06-22"},
            "remind me on monday to file LLC paperwork",
        )
        == "2026-06-22 09:00"
    )
    assert (
        PhotonAdapter._intent_due_datetime(
            {"due_datetime": "2026-06-22 00:00"},
            "remind me monday to file LLC paperwork",
        )
        == "2026-06-22 09:00"
    )
    assert (
        PhotonAdapter._intent_due_datetime(
            {"due_datetime": "2026-06-22 00:00"},
            "remind me monday at midnight to file LLC paperwork",
        )
        == "2026-06-22 00:00"
    )


@pytest.mark.asyncio
async def test_intent_gate_reminder_uses_9am_due_and_prefers_thumb_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(
        monkeypatch,
        {"sebos_rules": True, "intent_gate": True, "ack_reactions": True},
    )

    async def fake_classify(text: str, *, timestamp: datetime):
        return {
            "intent": "reminder",
            "confidence": 0.99,
            "needs_clarification": False,
            "title": "File LLC paperwork",
            "due_datetime": "2026-06-22 00:00",
        }

    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"status": "ok", "title": "File LLC paperwork", "due": "2026-06-22 09:00"}

    sent = []
    acks = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    async def fake_ack(space_id: str, message_id: str | None, emoji: str) -> bool:
        acks.append((space_id, message_id, emoji))
        return True

    monkeypatch.setattr(adapter, "_classify_natural_intent", fake_classify)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)
    monkeypatch.setattr(adapter, "_send_ack_reaction", fake_ack)

    result = await adapter._try_intent_gate(
        space_id="space-1",
        message_id="msg-1",
        text="remind me on monday to file LLC paperwork",
        mtype=MessageType.TEXT,
        timestamp=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
    )

    assert result == "handled"
    assert calls == [
        (
            ("sebos-add-reminder", "File LLC paperwork", "--due", "2026-06-22 09:00"),
            None,
            45.0,
        )
    ]
    assert acks == [("space-1", "msg-1", "👍")]
    assert sent == []


@pytest.mark.asyncio
async def test_intent_gate_reminder_tapback_failure_falls_back_to_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(
        monkeypatch,
        {"sebos_rules": True, "intent_gate": True, "ack_reactions": True},
    )

    async def fake_classify(text: str, *, timestamp: datetime):
        return {
            "intent": "reminder",
            "confidence": 0.99,
            "needs_clarification": False,
            "title": "File LLC paperwork",
            "due_datetime": "2026-06-22 09:00",
        }

    async def fake_run(*args, stdin=None, timeout=20.0):
        return {"status": "ok", "title": "File LLC paperwork", "due": "2026-06-22 09:00"}

    sent = []
    acks = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    async def fake_ack(space_id: str, message_id: str | None, emoji: str) -> bool:
        acks.append((space_id, message_id, emoji))
        return False

    monkeypatch.setattr(adapter, "_classify_natural_intent", fake_classify)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)
    monkeypatch.setattr(adapter, "_send_ack_reaction", fake_ack)

    result = await adapter._try_intent_gate(
        space_id="space-1",
        message_id="msg-1",
        text="remind me monday to file LLC paperwork",
        mtype=MessageType.TEXT,
        timestamp=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
    )

    assert result == "handled"
    assert acks == [("space-1", "msg-1", "👍")]
    assert sent == [("space-1", "Reminder added: File LLC paperwork (2026-06-22 09:00).", "msg-1")]


@pytest.mark.asyncio
async def test_intent_gate_reminder_writer_failure_does_not_success_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(
        monkeypatch,
        {"sebos_rules": True, "intent_gate": True, "ack_reactions": True},
    )

    async def fake_classify(text: str, *, timestamp: datetime):
        return {
            "intent": "reminder",
            "confidence": 0.99,
            "needs_clarification": False,
            "title": "File LLC paperwork",
            "due_datetime": "2026-06-22 09:00",
        }

    async def fake_run(*args, stdin=None, timeout=20.0):
        return {"status": "error", "error": "calendar unavailable"}

    sent = []
    acks = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

    async def fake_ack(space_id: str, message_id: str | None, emoji: str) -> bool:
        acks.append((space_id, message_id, emoji))
        return True

    monkeypatch.setattr(adapter, "_classify_natural_intent", fake_classify)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)
    monkeypatch.setattr(adapter, "_send_ack_reaction", fake_ack)

    result = await adapter._try_intent_gate(
        space_id="space-1",
        message_id="msg-1",
        text="remind me monday to file LLC paperwork",
        mtype=MessageType.TEXT,
        timestamp=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
    )

    assert result == "handled"
    assert acks == []
    assert sent == [("space-1", "Reminder failed: calendar unavailable.", "msg-1")]
