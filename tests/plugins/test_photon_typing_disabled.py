import pytest
from unittest.mock import AsyncMock

from gateway.config import PlatformConfig
from plugins.platforms.photon.adapter import PhotonAdapter


@pytest.mark.asyncio
async def test_photon_send_typing_is_hard_noop_even_when_config_enabled(monkeypatch):
    monkeypatch.setenv("PHOTON_TYPING_INDICATORS", "true")
    adapter = PhotonAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "project_id": "test-project",
                "project_secret": "test-secret",
                "typing_indicators": True,
            },
        )
    )
    adapter._sidecar_call = AsyncMock()

    await adapter.send_typing("any;-;+15551234567", metadata={"thread_id": "ignored"})

    assert adapter._typing_indicators_enabled is False
    adapter._sidecar_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_photon_stop_typing_is_hard_noop_even_when_config_enabled(monkeypatch):
    monkeypatch.setenv("PHOTON_TYPING_INDICATORS", "true")
    adapter = PhotonAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "project_id": "test-project",
                "project_secret": "test-secret",
                "typing_indicators": True,
            },
        )
    )
    adapter._sidecar_call = AsyncMock()

    await adapter.stop_typing("any;-;+15551234567")

    assert adapter._typing_indicators_enabled is False
    adapter._sidecar_call.assert_not_awaited()


def test_photon_sidecar_typing_endpoint_cannot_call_spectrum_typing():
    source = "plugins/platforms/photon/sidecar/index.mjs"
    text = open(source, encoding="utf-8").read()

    assert "typing: spectrumTyping" not in text
    assert "spectrumTyping" not in text
    assert "space.send(spectrumTyping" not in text
    assert "disabled: true" in text
