"""Regression tests for gateway /model support of config.yaml custom_providers."""

import yaml
import pytest

from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource


def _make_runner():
    runner = object.__new__(GatewayRunner)
    runner.adapters = {}
    runner._voice_mode = {}
    runner._session_model_overrides = {}
    setattr(runner, "_pending_model_notes", {})
    setattr(runner, "_evict_cached_agent", lambda session_key: None)
    return runner


def _make_event(text="/model"):
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="12345", chat_type="dm"),
    )


@pytest.mark.asyncio
async def test_handle_model_command_lists_saved_custom_provider(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": {
                    "default": "gpt-5.4",
                    "provider": "openai-codex",
                    "base_url": "https://chatgpt.com/backend-api/codex",
                },
                "providers": {},
                "custom_providers": [
                    {
                        "name": "Local (127.0.0.1:4141)",
                        "base_url": "http://127.0.0.1:4141/v1",
                        "model": "rotator-openrouter-coding",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    import gateway.run as gateway_run

    monkeypatch.setattr(gateway_run, "_hermes_home", hermes_home)
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda: {})

    result = await _make_runner()._handle_model_command(_make_event())

    assert result is not None
    assert "Local (127.0.0.1:4141)" in result
    assert "custom:local-(127.0.0.1:4141)" in result
    assert "rotator-openrouter-coding" in result


@pytest.mark.asyncio
async def test_model_gab_shortcut_switches_to_arya_session_only(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    config_path = hermes_home / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "model": {"default": "gpt-5.5", "provider": "openai-codex"},
                "providers": {},
                "custom_providers": [
                    {
                        "name": "gab",
                        "base_url": "https://gab.ai/v1",
                        "key_env": "GAB_AI_API_KEY",
                        "api_mode": "chat_completions",
                        "model": "arya",
                        "models": {"arya": {"context_length": 128000}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    import gateway.run as gateway_run

    monkeypatch.setattr(gateway_run, "_hermes_home", hermes_home)
    monkeypatch.setattr("hermes_constants.get_hermes_home", lambda: hermes_home)
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: hermes_home)
    monkeypatch.setenv("GAB_AI_API_KEY", "test-key")
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda: {})

    runner = _make_runner()
    result = await runner._handle_model_command(_make_event("/model gab"))

    assert result is not None
    assert "arya" in result
    assert "Provider: gab" in result
    override = next(iter(runner._session_model_overrides.values()))
    assert override["model"] == "arya"
    assert override["provider"] == "custom:gab"
    persisted = yaml.safe_load(config_path.read_text())
    assert persisted["model"] == {"default": "gpt-5.5", "provider": "openai-codex"}
