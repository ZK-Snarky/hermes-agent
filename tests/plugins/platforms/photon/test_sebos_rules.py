from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageType
from plugins.platforms.photon import adapter as adapter_module
from plugins.platforms.photon.adapter import PhotonAdapter


def _make_adapter(monkeypatch: pytest.MonkeyPatch, extra: dict | None = None) -> PhotonAdapter:
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    cfg = PlatformConfig(enabled=True, token="", extra=extra or {"sebos_rules": True})
    return PhotonAdapter(cfg)


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
async def test_sebos_rules_explicit_command_routes_to_sebos(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"intent": "reminder", "status": "ok", "reply": "Reminder set."}

    sent = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

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
    assert calls[0][0][:6] == ("sebos-route-command", "--text", "-", "--write", "--db", str(adapter_module._SEBOS_DB_PATH))
    assert calls[0][1] == "reminder: tomorrow at 9 call Chaz"
    assert sent == [("space-1", "Reminder set.", "msg-1")]


@pytest.mark.asyncio
async def test_sebos_rules_natural_reminder_goes_to_hermes_for_date_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)

    async def fake_run(*args, stdin=None, timeout=20.0):
        raise AssertionError("natural reminders need model/date reasoning before sebOS writes")

    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="remind me monday to file llc paperwork",
        mtype=MessageType.TEXT,
        media_urls=[],
        media_types=[],
    )

    assert result is None


@pytest.mark.asyncio
async def test_sebos_rules_journal_routes_and_replies_once(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)

    async def fake_run(*args, stdin=None, timeout=20.0):
        return {"intent": "journal", "status": "ok", "reply": "Journal saved."}

    sent = []

    async def fake_send(space_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((space_id, text, reply_to))

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
