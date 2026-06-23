"""Natural-language intent gate tests for PhotonAdapter."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageEvent
from plugins.platforms.photon import adapter as adapter_module
from plugins.platforms.photon.adapter import PhotonAdapter


def _make_adapter(monkeypatch: pytest.MonkeyPatch) -> PhotonAdapter:
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    monkeypatch.setenv("PHOTON_ALLOWED_USERS", "+155****4567")
    monkeypatch.setattr(adapter_module, "_photon_auth_env_value", lambda key: os.getenv(key, ""))
    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: None)
    cfg = PlatformConfig(
        enabled=True,
        token="",
        extra={
            "sebos_rules": True,
            "intent_gate": True,
            "intent_gate_provider": "openai-codex",
            "intent_gate_model": "gpt-5.5",
        },
    )
    return PhotonAdapter(cfg)


def _capture_handled(
    adapter: PhotonAdapter, monkeypatch: pytest.MonkeyPatch
) -> List[MessageEvent]:
    captured: List[MessageEvent] = []

    async def fake_handle(event: MessageEvent) -> None:
        captured.append(event)

    monkeypatch.setattr(adapter, "handle_message", fake_handle)
    return captured


def _text_event(text: str, *, message_id: str = "user-msg-1") -> Dict[str, Any]:
    return {
        "messageId": message_id,
        "platform": "iMessage",
        "space": {"id": "+155****4567", "type": "dm", "phone": "+155****4567"},
        "sender": {"id": "+155****4567"},
        "content": {"type": "text", "text": text},
        "timestamp": "2026-06-20T10:00:00.000Z",
    }


@pytest.mark.asyncio
async def test_unauthorized_dispatch_skips_pre_gateway_sebos_shortcuts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    monkeypatch.setenv("PHOTON_ALLOWED_USERS", "+155****0000")
    monkeypatch.setattr(adapter_module, "_photon_auth_env_value", lambda key: os.getenv(key, ""))
    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: None)
    adapter = PhotonAdapter(
        PlatformConfig(enabled=True, token="", extra={"sebos_rules": True, "intent_gate": True})
    )
    captured = _capture_handled(adapter, monkeypatch)

    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("unauthorized sender must not reach sebOS shortcut path")

    monkeypatch.setattr(adapter, "_try_ingest_audio_journal_reply", forbidden)
    monkeypatch.setattr(adapter, "_try_intent_gate", forbidden)
    monkeypatch.setattr(adapter, "_handle_sebos_rules", forbidden)

    await adapter._dispatch_inbound(_text_event("board"))

    assert len(captured) == 1
    assert captured[0].text == "board"


def test_sebos_preauth_normalizes_photon_sender_and_space_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    monkeypatch.setenv("PHOTON_ALLOWED_USERS", "+155****4567")
    monkeypatch.setattr(adapter_module, "_photon_auth_env_value", lambda key: os.getenv(key, ""))
    adapter = PhotonAdapter(PlatformConfig(enabled=True, token="", extra={}))

    assert adapter._is_photon_user_allowed_for_sebos(sender_id="any;-;+155****4567")
    assert adapter._is_photon_user_allowed_for_sebos(space_phone="+155****4567")
    assert adapter._is_photon_user_allowed_for_sebos(space_id="iMessage;-;+155****4567")
    assert not adapter._is_photon_user_allowed_for_sebos(sender_id="+155****0000")


def test_reminder_update_phrase_is_routed_to_sebos_router() -> None:
    assert PhotonAdapter._looks_like_sebos_command(
        "hey can you adjust llc reminder to next wednesday"
    )


@pytest.mark.asyncio
async def test_reminder_update_phrase_dispatches_to_sebos_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    captured = _capture_handled(adapter, monkeypatch)
    routed: List[str] = []
    quiet: List[Tuple[str, str, str | None]] = []

    async def fake_route(text: str):
        routed.append(text)
        return {
            "status": "ok",
            "intent": "reminder_update",
            "reply": "Reminder updated: File LLC paperwork (2026-06-24 09:00).",
            "mutated": True,
        }

    async def fake_ack(chat_id: str, message_id: str | None, emoji: str) -> bool:
        return False

    async def fake_quiet(chat_id: str, text: str, *, reply_to: str | None = None) -> None:
        quiet.append((chat_id, text, reply_to))

    monkeypatch.setattr(adapter, "_route_explicit_sebos_command", fake_route)
    monkeypatch.setattr(adapter, "_send_ack_reaction", fake_ack)
    monkeypatch.setattr(adapter, "_send_quiet", fake_quiet)

    await adapter._dispatch_inbound(_text_event("hey can you adjust llc reminder to next wednesday"))

    assert captured == []
    assert routed == ["hey can you adjust llc reminder to next wednesday"]
    assert quiet == [("+155****4567", "Reminder updated: File LLC paperwork (2026-06-24 09:00).", "user-msg-1")]


@pytest.mark.asyncio
async def test_natural_reminder_high_confidence_routes_to_sebos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    captured = _capture_handled(adapter, monkeypatch)
    routed: List[str] = []
    quiet: List[Tuple[str, str, str | None]] = []

    async def fake_classify(text: str, *, timestamp) -> Dict[str, Any]:
        return {
            "intent": "reminder",
            "confidence": 0.95,
            "needs_clarification": False,
            "title": "call Turner",
            "due_datetime": "2026-06-22 09:00",
        }

    async def fake_run(*args: str, stdin: str | None = None, timeout: float = 20.0):
        # The journal-reply probe runs first on every inbound message; it now
        # goes through the sebOS CLI boundary. No active prompt here, so it
        # reports no date and the message proceeds to intent routing.
        if args and args[0] == "sebos-journal-pending-prompt":
            return {"date": None}
        routed.append(" ".join(args))
        return {
            "status": "ok",
            "title": "call Turner",
            "due": "2026-06-22 09:00",
        }

    async def fake_ack(chat_id: str, message_id: str | None, emoji: str) -> bool:
        return False

    async def fake_quiet(chat_id: str, text: str, *, reply_to: str | None = None) -> None:
        quiet.append((chat_id, text, reply_to))

    monkeypatch.setattr(adapter, "_classify_natural_intent", fake_classify)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_ack_reaction", fake_ack)
    monkeypatch.setattr(adapter, "_send_quiet", fake_quiet)

    await adapter._dispatch_inbound(_text_event("remind me Monday at 9 to call Turner"))

    assert captured == []
    assert routed == ["sebos-add-reminder call Turner --due 2026-06-22 09:00"]
    assert quiet == [("+155****4567", "Reminder added: call Turner (2026-06-22 09:00).", "user-msg-1")]


@pytest.mark.asyncio
async def test_natural_reminder_routes_through_boundary_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    reminder_calls: List[Tuple[str, str | None, str | None, str | None, str | None, str | None, str | None, float]] = []
    quiet: List[Tuple[str, str, str | None]] = []

    async def fake_classify(text: str, *, timestamp) -> Dict[str, Any]:
        return {
            "intent": "reminder",
            "confidence": 0.95,
            "needs_clarification": False,
            "title": "call Turner",
            "due_datetime": "2026-06-22 09:00",
        }

    class FakeBoundary:
        async def add_reminder(
            self,
            title: str,
            *,
            due: str | None = None,
            location: str | None = None,
            latitude: str | None = None,
            longitude: str | None = None,
            radius: str | None = None,
            proximity: str | None = None,
            timeout: float = 45.0,
        ):
            reminder_calls.append((title, due, location, latitude, longitude, radius, proximity, timeout))
            return {"status": "ok", "title": title, "due": due}

    async def fake_run(*args: str, stdin: str | None = None, timeout: float = 20.0):
        raise AssertionError("natural reminder writer should use plugin boundary first")

    async def fake_ack(chat_id: str, message_id: str | None, emoji: str) -> bool:
        return False

    async def fake_quiet(chat_id: str, text: str, *, reply_to: str | None = None) -> None:
        quiet.append((chat_id, text, reply_to))

    monkeypatch.setattr(adapter, "_classify_natural_intent", fake_classify)
    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: FakeBoundary())
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_ack_reaction", fake_ack)
    monkeypatch.setattr(adapter, "_send_quiet", fake_quiet)

    result = await adapter._try_intent_gate(
        space_id="space-1",
        message_id="msg-1",
        text="remind me Monday at 9 to call Turner",
        mtype=adapter_module.MessageType.TEXT,
        timestamp=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
    )

    assert result == "handled"
    assert reminder_calls == [("call Turner", "2026-06-22 09:00", None, None, None, None, None, 45.0)]
    assert quiet == [("space-1", "Reminder added: call Turner (2026-06-22 09:00).", "msg-1")]


@pytest.mark.asyncio
async def test_natural_reminder_writer_falls_back_to_old_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    calls: List[Tuple[Tuple[str, ...], str | None, float]] = []

    async def fake_classify(text: str, *, timestamp) -> Dict[str, Any]:
        return {
            "intent": "reminder",
            "confidence": 0.95,
            "needs_clarification": False,
            "title": "call Turner",
            "due_datetime": "2026-06-22 09:00",
        }

    async def fake_run(*args: str, stdin: str | None = None, timeout: float = 20.0):
        calls.append((args, stdin, timeout))
        return {"status": "ok", "title": "call Turner", "due": "2026-06-22 09:00"}

    async def fake_ack(chat_id: str, message_id: str | None, emoji: str) -> bool:
        return True

    monkeypatch.setattr(adapter, "_classify_natural_intent", fake_classify)
    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: None)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_ack_reaction", fake_ack)

    result = await adapter._try_intent_gate(
        space_id="space-1",
        message_id="msg-1",
        text="remind me Monday at 9 to call Turner",
        mtype=adapter_module.MessageType.TEXT,
        timestamp=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
    )

    assert result == "handled"
    assert calls == [(("sebos-add-reminder", "call Turner", "--due", "2026-06-22 09:00"), None, 45.0)]


@pytest.mark.asyncio
async def test_active_journal_prompt_date_uses_boundary_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    calls: List[Tuple[str, str | None, float]] = []

    class FakeBoundary:
        async def active_journal_prompt_date(self, at: str, *, db_path: str | None = None, timeout: float = 20.0):
            calls.append((at, db_path, timeout))
            return {"date": "2026-06-20"}

    async def fake_run(*args: str, stdin: str | None = None, timeout: float = 20.0):
        raise AssertionError("active journal prompt should use plugin boundary first")

    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: FakeBoundary())
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)

    message_dt = datetime(2026, 6, 20, 22, 0, tzinfo=timezone.utc)
    result = await adapter._active_journal_prompt_date(message_dt)

    assert result == "2026-06-20"
    assert calls == [(message_dt.isoformat(), str(adapter_module._SEBOS_DB_PATH), 20.0)]


@pytest.mark.asyncio
async def test_active_journal_prompt_date_falls_back_to_old_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    calls: List[Tuple[Tuple[str, ...], str | None, float]] = []

    async def fake_run(*args: str, stdin: str | None = None, timeout: float = 20.0):
        calls.append((args, stdin, timeout))
        return {"date": "2026-06-20"}

    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: None)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)

    message_dt = datetime(2026, 6, 20, 22, 0, tzinfo=timezone.utc)
    result = await adapter._active_journal_prompt_date(message_dt)

    assert result == "2026-06-20"
    assert calls == [
        (
            (
                "sebos-journal-pending-prompt",
                "--at",
                message_dt.isoformat(),
                "--db",
                str(adapter_module._SEBOS_DB_PATH),
                "--json",
            ),
            None,
            20.0,
        )
    ]


@pytest.mark.asyncio
async def test_active_journal_prompt_date_none_when_no_active_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)

    async def fake_run(*args: str, stdin: str | None = None, timeout: float = 20.0):
        return {"date": None}

    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)

    result = await adapter._active_journal_prompt_date(
        datetime(2026, 6, 20, 22, 0, tzinfo=timezone.utc)
    )
    assert result is None


@pytest.mark.asyncio
async def test_audio_journal_ingest_routes_through_boundary_facade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    adapter = _make_adapter(monkeypatch)
    audio = tmp_path / "Audio Message.caf"
    audio.write_bytes(b"fake-audio")
    ingests: List[Tuple[str, str, str | None, float, Dict[str, Any], str | None]] = []
    acks: List[Tuple[str, str | None, str]] = []

    class FakeBoundary:
        async def ingest_journal(
            self,
            payload_path: str,
            *,
            source: str = "photon",
            sender: str | None = None,
            timeout: float = 360.0,
            date: str | None = None,
        ):
            with open(payload_path, encoding="utf-8") as fh:
                payload = json.load(fh)
            ingests.append((payload_path, source, sender, timeout, payload, date))
            return {"inserted": 1, "transcribed_ok": 1}

    async def fake_prompt_date(message_dt: datetime) -> str:
        return "2026-06-20"

    async def fake_copy(path: str, message_id: str | None) -> str:
        return path

    async def fake_run(*args: str, stdin: str | None = None, timeout: float = 20.0):
        raise AssertionError("audio journal ingest should use plugin boundary first")

    async def fake_ack(chat_id: str, message_id: str | None, emoji: str) -> bool:
        acks.append((chat_id, message_id, emoji))
        return True

    monkeypatch.setattr(adapter, "_active_journal_prompt_date", fake_prompt_date)
    monkeypatch.setattr(adapter, "_copy_audio_to_sebos_inbox", fake_copy)
    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: FakeBoundary())
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_ack_reaction", fake_ack)

    handled = await adapter._try_ingest_audio_journal_reply(
        space_id="space-1",
        sender_id="+15555550100",
        message_id="msg-1",
        text="",
        timestamp=datetime(2026, 6, 20, 22, 0, tzinfo=timezone.utc),
        media_urls=[str(audio)],
        media_types=[""],
    )

    assert handled is True
    assert len(ingests) == 1
    payload_path, source, sender, timeout, payload, date = ingests[0]
    assert source == "photon"
    assert sender == "+15555550100"
    assert timeout == 360.0
    assert date == "2026-06-20"
    assert payload_path.endswith(".json")
    attachment = payload["messages"][0]["attachments"][0]
    assert attachment["path"] == str(audio)
    assert attachment["mimeType"] == "audio/x-caf"
    assert acks == [("space-1", "msg-1", "❤️")]


@pytest.mark.asyncio
async def test_audio_journal_ingest_falls_back_to_old_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    adapter = _make_adapter(monkeypatch)
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"fake-audio")
    calls: List[Tuple[Tuple[str, ...], str | None, float]] = []
    sent: List[Tuple[str, str]] = []

    async def fake_prompt_date(message_dt: datetime) -> str:
        return "2026-06-20"

    async def fake_copy(path: str, message_id: str | None) -> str:
        return path

    async def fake_run(*args: str, stdin: str | None = None, timeout: float = 20.0):
        calls.append((args, stdin, timeout))
        return {"inserted": 1, "transcribed_ok": 0}

    async def fake_quiet(chat_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(adapter, "_active_journal_prompt_date", fake_prompt_date)
    monkeypatch.setattr(adapter, "_copy_audio_to_sebos_inbox", fake_copy)
    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: None)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_quiet)

    handled = await adapter._try_ingest_audio_journal_reply(
        space_id="space-1",
        sender_id="+15555550100",
        message_id="msg-1",
        text="",
        timestamp=datetime(2026, 6, 20, 22, 0, tzinfo=timezone.utc),
        media_urls=[str(audio)],
        media_types=["audio/mp4"],
    )

    assert handled is True
    assert len(calls) == 1
    args, stdin, timeout = calls[0]
    assert args[0] == "sebos-ingest-journal"
    assert args[2:] == ("--source", "photon", "--sender", "+15555550100", "--date", "2026-06-20")
    assert stdin is None
    assert timeout == 360.0
    assert sent == [("space-1", "Audio received, but transcription failed.")]


@pytest.mark.asyncio
async def test_audio_journal_ingests_without_active_prompt_instead_of_chat_fallthrough(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    adapter = _make_adapter(monkeypatch)
    audio = tmp_path / "clip.caf"
    audio.write_bytes(b"fake-audio")
    calls: List[Tuple[Tuple[str, ...], str | None, float]] = []
    acks: List[Tuple[str, str | None, str]] = []

    async def no_prompt(message_dt: datetime) -> None:
        return None

    async def fake_copy(path: str, message_id: str | None) -> str:
        return path

    async def fake_run(*args: str, stdin: str | None = None, timeout: float = 20.0):
        calls.append((args, stdin, timeout))
        return {"inserted": 1, "transcribed_ok": 1}

    async def fake_ack(chat_id: str, message_id: str | None, emoji: str) -> bool:
        acks.append((chat_id, message_id, emoji))
        return True

    monkeypatch.setattr(adapter, "_active_journal_prompt_date", no_prompt)
    monkeypatch.setattr(adapter, "_copy_audio_to_sebos_inbox", fake_copy)
    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: None)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_ack_reaction", fake_ack)

    handled = await adapter._try_ingest_audio_journal_reply(
        space_id="space-1",
        sender_id="+155****0100",
        message_id="msg-1",
        text="(voice)",
        timestamp=datetime(2026, 6, 23, 9, 10, tzinfo=timezone.utc),
        media_urls=[str(audio)],
        media_types=["audio/x-caf"],
    )

    assert handled is True
    args, _, _ = calls[0]
    assert "--date" not in args
    assert acks == [("space-1", "msg-1", "❤️")]


@pytest.mark.asyncio
async def test_intent_gate_note_routes_through_boundary_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    boundary_calls: List[Tuple[str, bool, str | None, str, float]] = []
    sent: List[Tuple[str, str, str | None]] = []

    async def fake_classify(text: str, *, timestamp) -> Dict[str, Any]:
        return {
            "intent": "note",
            "confidence": 0.95,
            "needs_clarification": False,
            "body": "test body",
            "target": "Business",
        }

    class FakeBoundary:
        async def route_text_command(
            self,
            text: str,
            *,
            write: bool = True,
            db_path: str | None = None,
            channel: str = "imessage",
            timeout: float = 45.0,
        ):
            boundary_calls.append((text, write, db_path, channel, timeout))
            return {"intent": "note", "status": "ok", "reply": "Note saved."}

    async def fake_run(*args: str, stdin: str | None = None, timeout: float = 20.0):
        raise AssertionError("natural note routing should use plugin boundary first")

    async def fake_quiet(chat_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((chat_id, text, reply_to))

    monkeypatch.setattr(adapter, "_classify_natural_intent", fake_classify)
    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: FakeBoundary())
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_quiet)

    result = await adapter._try_intent_gate(
        space_id="space-1",
        message_id="msg-1",
        text="note this under Business: test body",
        mtype=adapter_module.MessageType.TEXT,
        timestamp=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
    )

    assert result == "handled"
    assert boundary_calls == [
        (
            "note this under Business: test body",
            True,
            str(adapter_module._SEBOS_DB_PATH),
            "imessage",
            45.0,
        )
    ]
    assert sent == [("space-1", "Note saved.", "msg-1")]


@pytest.mark.asyncio
async def test_intent_gate_note_fallback_preserves_no_appender_fallthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    calls: List[Tuple[Tuple[str, ...], str | None, float]] = []
    sent: List[Tuple[str, str, str | None]] = []

    async def fake_classify(text: str, *, timestamp) -> Dict[str, Any]:
        return {
            "intent": "note",
            "confidence": 0.95,
            "needs_clarification": False,
            "body": "test body",
            "target": "Business",
        }

    async def fake_run(*args: str, stdin: str | None = None, timeout: float = 20.0):
        calls.append((args, stdin, timeout))
        return {"status": "dry_run", "details": {"reason": "no_appender_wired"}}

    async def fake_quiet(chat_id: str, text: str, *, reply_to: str | None = None) -> None:
        sent.append((chat_id, text, reply_to))

    monkeypatch.setattr(adapter, "_classify_natural_intent", fake_classify)
    monkeypatch.setattr(adapter_module, "_load_sebos_photon_boundary", lambda: None)
    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_quiet)

    result = await adapter._try_intent_gate(
        space_id="space-1",
        message_id="msg-1",
        text="note this under Business: test body",
        mtype=adapter_module.MessageType.TEXT,
        timestamp=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
    )

    assert result is None
    assert calls == [
        (
            ("sebos-route-command", "--text", "-", "--write", "--db", str(adapter_module._SEBOS_DB_PATH), "--json"),
            "note this under Business: test body",
            45.0,
        )
    ]
    assert sent == []


@pytest.mark.asyncio
async def test_low_confidence_intent_falls_through_to_hermes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    captured = _capture_handled(adapter, monkeypatch)

    async def fake_classify(text: str, *, timestamp) -> Dict[str, Any]:
        return {"intent": "reminder", "confidence": 0.42, "needs_clarification": False}

    monkeypatch.setattr(adapter, "_classify_natural_intent", fake_classify)

    await adapter._dispatch_inbound(_text_event("remind me about the thing maybe"))

    assert len(captured) == 1
    assert captured[0].text == "remind me about the thing maybe"


@pytest.mark.asyncio
async def test_intent_gate_clarification_replies_in_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    captured = _capture_handled(adapter, monkeypatch)
    quiet: List[Tuple[str, str, str | None]] = []

    async def fake_classify(text: str, *, timestamp) -> Dict[str, Any]:
        return {
            "intent": "reminder",
            "confidence": 0.9,
            "needs_clarification": True,
            "clarification": "When should I remind you?",
        }

    async def fake_quiet(chat_id: str, text: str, *, reply_to: str | None = None) -> None:
        quiet.append((chat_id, text, reply_to))

    monkeypatch.setattr(adapter, "_classify_natural_intent", fake_classify)
    monkeypatch.setattr(adapter, "_send_quiet", fake_quiet)

    await adapter._dispatch_inbound(_text_event("remind me to call Turner"))

    assert captured == []
    assert quiet == [("+155****4567", "When should I remind you?", "user-msg-1")]


def test_intent_to_sebos_text_normalizes_note_and_journal() -> None:
    assert PhotonAdapter._intent_to_sebos_text(
        {"intent": "note", "body": "test body", "target": "Business"}
    ) == "note this under Business: test body"
    assert PhotonAdapter._intent_to_sebos_text(
        {"intent": "journal", "body": "kept the promise"}
    ) == "j: kept the promise"


def test_intent_reminder_args_default_date_only_or_implicit_midnight_to_9am() -> None:
    assert PhotonAdapter._intent_reminder_args(
        {"intent": "reminder", "title": "File LLC paperwork", "due_datetime": "2026-06-22 00:00"},
        "remind me on Monday to file LLC paperwork",
    ) == ["sebos-add-reminder", "File LLC paperwork", "--due", "2026-06-22 09:00"]
    assert PhotonAdapter._intent_reminder_args(
        {"intent": "reminder", "title": "File LLC paperwork", "due_datetime": "2026-06-22"},
        "remind me Monday to file LLC paperwork",
    ) == ["sebos-add-reminder", "File LLC paperwork", "--due", "2026-06-22 09:00"]


def test_intent_reminder_args_preserves_explicit_midnight_and_location() -> None:
    assert PhotonAdapter._intent_reminder_args(
        {
            "intent": "reminder",
            "title": "Bring badge",
            "due_datetime": "2026-06-22 00:00",
            "location_name": "Office",
            "latitude": "40.7608",
            "longitude": "-111.8910",
            "radius_meters": "150",
            "proximity": "enter",
        },
        "remind me at midnight when I get to the office to bring badge",
    ) == [
        "sebos-add-reminder",
        "Bring badge",
        "--due",
        "2026-06-22 00:00",
        "--location",
        "Office",
        "--latitude",
        "40.7608",
        "--longitude",
        "-111.8910",
        "--radius",
        "150",
        "--proximity",
        "enter",
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("remind me Monday", {"due_datetime": "2026-06-22 09:00"}),
        ("remind me next Thursday afternoon", {"due_datetime": "2026-06-25 14:00"}),
        ("remind me in 2 Fridays", {"due_datetime": "2026-07-03 09:00"}),
        ("remind me tomorrow morning", {"due_datetime": "2026-06-21 09:00"}),
        (
            "remind me when I get to the office",
            {"location_name": "Office", "proximity": "enter"},
        ),
        (
            "remind me when I leave the office",
            {"location_name": "Office", "proximity": "leave"},
        ),
    ],
)
def test_deterministic_natural_reminder_matrix_supported(
    text: str,
    expected: Dict[str, str],
) -> None:
    parsed = PhotonAdapter._deterministic_natural_reminder_intent(
        text,
        timestamp=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
    )

    assert parsed is not None
    assert parsed["intent"] == "reminder"
    assert parsed["needs_clarification"] is False
    assert parsed["title"] == "Reminder"
    for key, value in expected.items():
        assert parsed[key] == value
    if parsed.get("due_datetime"):
        assert not parsed["due_datetime"].endswith("00:00")


@pytest.mark.parametrize(
    ("text", "clarifier_fragment"),
    [
        ("remind me after my meeting", "after your meeting"),
        ("remind me when I get to the shop", "Which location"),
    ],
)
def test_deterministic_natural_reminder_matrix_clarifies_unsupported(
    text: str,
    clarifier_fragment: str,
) -> None:
    parsed = PhotonAdapter._deterministic_natural_reminder_intent(
        text,
        timestamp=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
    )

    assert parsed is not None
    assert parsed["intent"] == "reminder"
    assert parsed["needs_clarification"] is True
    assert clarifier_fragment in parsed["clarification"]
