from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# sebos_event moved out of Hermes core into the hermes-sebos user plugin. The
# plugin lives outside the repo (~/.hermes/plugins/hermes-sebos), so load its
# tools module by path. Skip cleanly if the plugin isn't installed.
_PLUGIN_TOOLS = Path.home() / ".hermes" / "plugins" / "hermes-sebos" / "tools.py"
if not _PLUGIN_TOOLS.exists():
    pytest.skip(
        "hermes-sebos plugin not installed; sebos_event lives in the plugin",
        allow_module_level=True,
    )
_spec = importlib.util.spec_from_file_location("hermes_sebos_tools_under_test", _PLUGIN_TOOLS)
sebos_event = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sebos_event)


def test_emit_writes_atomic_event_file_and_redacts_payload(tmp_path):
    inbox = tmp_path / "events"
    event_uid = sebos_event.emit(
        kind="decision.made",
        subject="Live Board rollout",
        summary="Decided to turn on the Live Board after dry-run review.",
        lane="Falconnect",
        payload={"api_key": "secret-value", "nested": {"token": "abc", "safe": "ok"}},
        ts="2026-06-19T20:40:00",
        inbox_dir=inbox,
    )

    files = list(inbox.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["event_uid"] == event_uid
    assert data["schema_version"] == 1
    assert data["kind"] == "decision.made"
    assert data["lane"] == "Falconnect"
    assert data["payload"]["api_key"] == "***redacted***"
    assert data["payload"]["nested"]["token"] == "***redacted***"
    assert data["payload"]["nested"]["safe"] == "ok"
    assert not list((inbox / ".tmp").glob("*.json"))


def test_emit_rejects_invalid_kind(tmp_path):
    try:
        sebos_event.emit(
            kind="chat.random",
            subject="Noise",
            summary="This should not land.",
            inbox_dir=tmp_path / "events",
        )
    except ValueError as exc:
        assert "invalid kind" in str(exc)
    else:
        raise AssertionError("invalid kind should raise")


def test_tool_handler_returns_json(tmp_path, monkeypatch):
    monkeypatch.setattr(sebos_event, "_default_inbox_dir", lambda: tmp_path / "events")
    raw = sebos_event.sebos_event_tool(
        {
            "kind": "task.completed",
            "subject": "Live Board smoke",
            "summary": "Verified the sebOS event helper writes a file.",
            "weight": 20,
        }
    )
    result = json.loads(raw)
    assert result["success"] is True
    assert result["event_uid"]
    assert len(list((tmp_path / "events").glob("*.json"))) == 1


def test_check_requirements_uses_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setattr(sebos_event, "get_hermes_home", lambda: tmp_path)
    assert sebos_event.check_sebos_event_requirements() is False
    (tmp_path / "sebos").mkdir()
    assert sebos_event.check_sebos_event_requirements() is True
