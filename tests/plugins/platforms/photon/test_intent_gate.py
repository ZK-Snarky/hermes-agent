"""Natural-language intent gate tests for PhotonAdapter."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageEvent
from plugins.platforms.photon.adapter import PhotonAdapter


def _make_adapter(monkeypatch: pytest.MonkeyPatch) -> PhotonAdapter:
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
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
