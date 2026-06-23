from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_PLUGIN_BOUNDARY = Path.home() / ".hermes" / "plugins" / "hermes-sebos" / "photon_boundary.py"


def _load_boundary_module():
    spec = importlib.util.spec_from_file_location("hermes_sebos_photon_boundary_test", _PLUGIN_BOUNDARY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_run_sebos_json_missing_command_is_structured_error() -> None:
    boundary = _load_boundary_module()

    result = await boundary.run_sebos_json("definitely-not-a-sebos-command")

    assert result["status"] == "error"
    assert result["error_layer"] == "router"
    assert result["returncode"] == 127
    assert "missing sebOS command" in result["error"]


@pytest.mark.asyncio
async def test_route_text_command_builds_legacy_cli_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _load_boundary_module()
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"status": "ok", "intent": "reminder", "reply": "Reminder set.", "returncode": 0}

    monkeypatch.setattr(boundary, "run_sebos_json", fake_run)

    result = await boundary.route_text_command(
        "reminder: tomorrow at 9 call Chaz",
        write=True,
        db_path="/tmp/sebos.db",
        channel="imessage",
        timeout=45.0,
    )

    assert result["reply"] == "Reminder set."
    assert calls == [
        (
            ("sebos-route-command", "--text", "-", "--write", "--db", "/tmp/sebos.db", "--json"),
            "reminder: tomorrow at 9 call Chaz",
            45.0,
        )
    ]


@pytest.mark.asyncio
async def test_render_mission_control_builds_legacy_cli_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _load_boundary_module()
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"status": "ok", "body": "BOARD", "returncode": 0}

    monkeypatch.setattr(boundary, "run_sebos_json", fake_run)

    result = await boundary.render_mission_control(dry_run=True, timeout=25.0)

    assert result["body"] == "BOARD"
    assert calls == [
        (
            ("sebos-render-mission-control", "--dry-run", "--json"),
            None,
            25.0,
        )
    ]


@pytest.mark.asyncio
async def test_board_query_builds_live_board_cli_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _load_boundary_module()
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"status": "ok", "next": ["Falconnect: verify Re-Engage"], "returncode": 0}

    monkeypatch.setattr(boundary, "run_sebos_json", fake_run)

    result = await boundary.board_query("next", "--lane", "Falconnect", timeout=25.0)

    assert result["next"] == ["Falconnect: verify Re-Engage"]
    assert calls == [
        (
            ("sebos-board-query", "--json", "next", "--lane", "Falconnect"),
            None,
            25.0,
        )
    ]


@pytest.mark.asyncio
async def test_active_journal_prompt_date_builds_legacy_cli_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _load_boundary_module()
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"status": "ok", "date": "2026-06-20", "returncode": 0}

    monkeypatch.setattr(boundary, "run_sebos_json", fake_run)

    result = await boundary.active_journal_prompt_date(
        "2026-06-20T22:00:00+00:00",
        db_path="/tmp/sebos.db",
        timeout=20.0,
    )

    assert result["date"] == "2026-06-20"
    assert calls == [
        (
            (
                "sebos-journal-pending-prompt",
                "--at",
                "2026-06-20T22:00:00+00:00",
                "--db",
                "/tmp/sebos.db",
                "--json",
            ),
            None,
            20.0,
        )
    ]


@pytest.mark.asyncio
async def test_add_reminder_builds_legacy_cli_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _load_boundary_module()
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"status": "ok", "title": "Bring badge", "returncode": 0}

    monkeypatch.setattr(boundary, "run_sebos_json", fake_run)

    result = await boundary.add_reminder(
        "Bring badge",
        due="2026-06-22 00:00",
        location="Office",
        latitude="40.7608",
        longitude="-111.8910",
        radius="150",
        proximity="enter",
        timeout=45.0,
    )

    assert result["title"] == "Bring badge"
    assert calls == [
        (
            (
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
            ),
            None,
            45.0,
        )
    ]


@pytest.mark.asyncio
async def test_update_reminder_builds_legacy_cli_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _load_boundary_module()
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"status": "ok", "title": "File LLC paperwork", "returncode": 0}

    monkeypatch.setattr(boundary, "run_sebos_json", fake_run)

    result = await boundary.update_reminder(
        "llc",
        due="2026-06-24 09:00",
        timeout=45.0,
    )

    assert result["title"] == "File LLC paperwork"
    assert calls == [
        (
            (
                "sebos-update-reminder",
                "llc",
                "--due",
                "2026-06-24 09:00",
            ),
            None,
            45.0,
        )
    ]


@pytest.mark.asyncio
async def test_ingest_journal_builds_legacy_cli_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _load_boundary_module()
    calls = []

    async def fake_run(*args, stdin=None, timeout=20.0):
        calls.append((args, stdin, timeout))
        return {"inserted": 1, "transcribed_ok": 1, "returncode": 0}

    monkeypatch.setattr(boundary, "run_sebos_json", fake_run)

    result = await boundary.ingest_journal(
        "/tmp/payload.json",
        source="photon",
        sender="+15555550100",
        timeout=360.0,
    )

    assert result["inserted"] == 1
    assert calls == [
        (
            (
                "sebos-ingest-journal",
                "/tmp/payload.json",
                "--source",
                "photon",
                "--sender",
                "+15555550100",
            ),
            None,
            360.0,
        )
    ]
