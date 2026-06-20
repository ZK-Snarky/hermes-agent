"""Safety guard tests for Photon shared-cloud iMessage.

Photon shared-pool iMessage can emit server-side fallback texts when the
project's gRPC stream is unavailable. The adapter must fail closed unless the
operator explicitly opts into unsafe diagnostics.
"""
from __future__ import annotations

from typing import Any

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.photon import adapter as photon_adapter
from plugins.platforms.photon.adapter import PhotonAdapter


def _make_adapter(monkeypatch: pytest.MonkeyPatch) -> PhotonAdapter:
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    monkeypatch.delenv("PHOTON_ALLOW_SHARED_UNSAFE", raising=False)
    return PhotonAdapter(PlatformConfig(enabled=True, token="", extra={}))


class _Resp:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class _TypeClient:
    response = _Resp(200, {"data": {"type": "shared"}})
    calls: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append({"init": kwargs})

    async def __aenter__(self) -> "_TypeClient":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def get(self, url: str, **kwargs: Any) -> _Resp:
        self.calls.append({"url": url, "kwargs": kwargs})
        return self.response


@pytest.mark.asyncio
async def test_shared_cloud_project_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    _TypeClient.response = _Resp(200, {"data": {"type": "shared"}})
    _TypeClient.calls = []
    monkeypatch.setattr(photon_adapter.httpx, "AsyncClient", _TypeClient)

    assert await adapter._assert_cloud_project_safe() is False

    assert adapter.fatal_error_code == "SHARED_CLOUD_UNSAFE"
    assert adapter.fatal_error_retryable is False
    assert "server-side fallback/offline texts" in (adapter.fatal_error_message or "")
    assert _TypeClient.calls[-1]["kwargs"]["headers"]["Authorization"] == "Bearer test-project-secret"


@pytest.mark.asyncio
async def test_connect_fails_closed_when_project_type_is_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    _TypeClient.response = _Resp(200, {"data": {"type": "shared"}})
    _TypeClient.calls = []
    monkeypatch.setattr(photon_adapter.httpx, "AsyncClient", _TypeClient)

    assert await adapter.connect() is False
    assert adapter.fatal_error_code == "SHARED_CLOUD_UNSAFE"


@pytest.mark.asyncio
async def test_dedicated_project_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(monkeypatch)
    _TypeClient.response = _Resp(200, {"data": {"type": "dedicated"}})
    _TypeClient.calls = []
    monkeypatch.setattr(photon_adapter.httpx, "AsyncClient", _TypeClient)

    assert await adapter._assert_cloud_project_safe() is True
    assert adapter.fatal_error_code is None


@pytest.mark.asyncio
async def test_shared_cloud_can_only_boot_with_explicit_unsafe_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    monkeypatch.setenv("PHOTON_ALLOW_SHARED_UNSAFE", "true")
    _TypeClient.response = _Resp(200, {"data": {"type": "shared"}})
    _TypeClient.calls = []
    monkeypatch.setattr(photon_adapter.httpx, "AsyncClient", _TypeClient)

    assert await adapter._assert_cloud_project_safe() is True
    assert adapter.fatal_error_code is None


@pytest.mark.asyncio
async def test_imessage_type_check_http_failure_allows_sidecar_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter(monkeypatch)
    _TypeClient.response = _Resp(503, {"error": "unavailable"})
    _TypeClient.calls = []
    monkeypatch.setattr(photon_adapter.httpx, "AsyncClient", _TypeClient)

    assert await adapter._assert_cloud_project_safe() is True
    assert adapter.fatal_error_code is None
