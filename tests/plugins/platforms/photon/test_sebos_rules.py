from __future__ import annotations

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageType
from plugins.platforms.photon.adapter import PhotonAdapter


def _make_adapter(monkeypatch: pytest.MonkeyPatch, extra: dict | None = None) -> PhotonAdapter:
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    cfg = PlatformConfig(enabled=True, token="", extra=extra or {"sebos_rules": True})
    return PhotonAdapter(cfg)


@pytest.mark.asyncio
async def test_sebos_rules_unknown_falls_through_to_assistant(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert calls[0][0][:4] == ("sebos-route-command", "--text", "-", "--write")
    assert calls[0][1] == "random normal chat"
    assert sent == []


@pytest.mark.asyncio
async def test_sebos_rules_journal_routes_and_replies_once(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)

    async def fake_run(*args, stdin=None, timeout=20.0):
        return {"intent": "journal", "status": "ok", "reply": "Journal saved."}

    sent = []

    async def fake_send(space_id: str, text: str) -> None:
        sent.append((space_id, text))

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
    assert sent == [("space-1", "Journal saved.")]


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
async def test_sebos_rules_audio_wins_before_text(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    adapter = _make_adapter(monkeypatch)
    audio = tmp_path / "clip.m4a"
    audio.write_bytes(b"fake-audio")
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append(args)
        return {"status": "ok"}

    sent = []

    async def fake_send(space_id: str, text: str) -> None:
        sent.append((space_id, text))

    monkeypatch.setattr(adapter, "_run_sebos_json", fake_run)
    monkeypatch.setattr(adapter, "_send_quiet", fake_send)

    result = await adapter._handle_sebos_rules(
        space_id="space-1",
        message_id="msg-1",
        text="h: ignore this caption",
        mtype=MessageType.VOICE,
        media_urls=[str(audio)],
        media_types=["audio/mp4"],
    )

    assert result == "handled"
    assert calls[0][0] == "sebos-photon-ingest-audio"
    assert sent == [("space-1", "Audio saved.")]
