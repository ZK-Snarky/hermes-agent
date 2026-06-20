"""Threaded iMessage session tests for PhotonAdapter."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageEvent
from plugins.platforms.photon.adapter import PhotonAdapter


def _make_adapter(
    monkeypatch: pytest.MonkeyPatch, *, sebos_rules: bool = False
) -> PhotonAdapter:
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    cfg = PlatformConfig(enabled=True, token="", extra={"sebos_rules": sebos_rules})
    return PhotonAdapter(cfg)


def _capture_sidecar(adapter: PhotonAdapter) -> List[Tuple[str, Dict[str, Any]]]:
    calls: List[Tuple[str, Dict[str, Any]]] = []

    async def _fake_call(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        calls.append((path, body))
        return {"ok": True, "messageId": "bot-msg-1"}

    adapter._sidecar_call = _fake_call  # type: ignore[assignment]
    return calls


def _capture_handled(
    adapter: PhotonAdapter, monkeypatch: pytest.MonkeyPatch
) -> List[MessageEvent]:
    captured: List[MessageEvent] = []

    async def fake_handle(event: MessageEvent) -> None:
        captured.append(event)

    monkeypatch.setattr(adapter, "handle_message", fake_handle)
    return captured


def _text_event(
    text: str,
    *,
    message_id: str = "user-msg-1",
    reply_to: str | None = None,
    thread_root: str | None = None,
) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "messageId": message_id,
        "platform": "iMessage",
        "space": {"id": "+155****4567", "type": "dm", "phone": "+155****4567"},
        "sender": {"id": "+155****4567"},
        "content": {"type": "text", "text": text},
        "timestamp": "2026-06-20T10:00:00.000Z",
    }
    if reply_to:
        event["replyToMessageId"] = reply_to
    if thread_root:
        event["threadRootMessageId"] = thread_root
    return event


@pytest.mark.asyncio
async def test_send_passes_reply_to_sidecar_and_maps_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    calls = _capture_sidecar(adapter)

    result = await adapter.send("+155****4567", "reply body", reply_to="root-msg-1")

    assert result.success is True
    assert calls == [
        (
            "/send",
            {
                "spaceId": "+155****4567",
                "text": "reply body",
                "replyToMessageId": "root-msg-1",
                "format": "markdown",
            },
        )
    ]
    assert adapter._sent_thread_roots["bot-msg-1"] == "root-msg-1"


@pytest.mark.asyncio
async def test_t_prefix_starts_thread_session_and_strips_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch, sebos_rules=True)
    captured = _capture_handled(adapter, monkeypatch)

    await adapter._dispatch_inbound(_text_event("t: think this through", message_id="root-1"))

    assert len(captured) == 1
    event = captured[0]
    assert event.text == "think this through"
    assert event.message_id == "root-1"
    assert event.source.thread_id == "root-1"


@pytest.mark.asyncio
async def test_reply_to_bot_message_resumes_thread_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch, sebos_rules=True)
    captured = _capture_handled(adapter, monkeypatch)
    adapter._sent_thread_roots["bot-msg-1"] = "root-1"

    await adapter._dispatch_inbound(
        _text_event("continue", message_id="user-reply-1", reply_to="bot-msg-1")
    )

    assert len(captured) == 1
    event = captured[0]
    assert event.text == "continue"
    assert event.reply_to_message_id == "bot-msg-1"
    assert event.source.thread_id == "root-1"


@pytest.mark.asyncio
async def test_main_chat_plain_text_stays_command_rail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch, sebos_rules=True)
    captured = _capture_handled(adapter, monkeypatch)
    quiet: List[Tuple[str, str]] = []

    async def fake_quiet(chat_id: str, text: str) -> None:
        quiet.append((chat_id, text))

    monkeypatch.setattr(adapter, "_send_quiet", fake_quiet)

    await adapter._dispatch_inbound(_text_event("what do you think?"))

    assert captured == []
    assert quiet == [
        (
            "+155****4567",
            "Use t: for chat. Use j:, remind me, note this, or board for Mission Control.",
        )
    ]


@pytest.mark.asyncio
async def test_t_plus_continues_last_thread_when_native_metadata_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch, sebos_rules=True)
    captured = _capture_handled(adapter, monkeypatch)
    adapter._last_thread_root_by_chat["+155****4567"] = "root-1"

    await adapter._dispatch_inbound(_text_event("t+ second thought", message_id="user-msg-2"))

    assert len(captured) == 1
    event = captured[0]
    assert event.text == "second thought"
    assert event.source.thread_id == "root-1"
