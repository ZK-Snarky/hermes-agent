"""Outbound-media tests for PhotonAdapter.

Photon ships outbound attachments via spectrum-ts' ``attachment()`` /
``voice()`` content builders, reached through the Node sidecar's
``/send-attachment`` endpoint. These tests stub ``_sidecar_call`` so we
can assert the endpoint + body shape each ``send_*`` override produces
without spawning Node or binding ports.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.photon import adapter as photon_adapter
from plugins.platforms.photon.adapter import PhotonAdapter


def _make_adapter(monkeypatch: pytest.MonkeyPatch) -> PhotonAdapter:
    monkeypatch.setenv("PHOTON_PROJECT_ID", "test-project-id")
    monkeypatch.setenv("PHOTON_PROJECT_SECRET", "test-project-secret")
    monkeypatch.delenv("PHOTON_WEBHOOK_SECRET", raising=False)
    cfg = PlatformConfig(enabled=True, token="", extra={})
    return PhotonAdapter(cfg)


def _capture_sidecar(adapter: PhotonAdapter) -> list[tuple[str, dict[str, Any]]]:
    """Replace ``_sidecar_call`` with a recorder that returns a fixed id."""
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _fake_call(path: str, body: dict[str, Any]) -> dict[str, Any]:
        calls.append((path, body))
        return {"ok": True, "messageId": "msg-123"}

    adapter._sidecar_call = _fake_call  # type: ignore[assignment]
    return calls


@pytest.fixture()
def real_file(tmp_path) -> str:
    p = tmp_path / "photo.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    return str(p)


def _patch_safe_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make path validation a passthrough so tmp files outside the cache pass."""
    monkeypatch.setattr(
        PhotonAdapter,
        "validate_media_delivery_path",
        staticmethod(lambda p: p if os.path.exists(p) else None),
    )


@pytest.mark.asyncio
async def test_send_image_file_hits_attachment_endpoint(
    monkeypatch: pytest.MonkeyPatch, real_file: str
) -> None:
    _patch_safe_path(monkeypatch)
    adapter = _make_adapter(monkeypatch)
    calls = _capture_sidecar(adapter)

    result = await adapter.send_image_file(
        "any;-;+15551234567", real_file, caption="look"
    )

    assert result.success is True
    assert result.message_id == "msg-123"
    assert len(calls) == 1
    path, body = calls[0]
    assert path == "/send-attachment"
    assert body["spaceId"] == "any;-;+15551234567"
    assert body["path"] == real_file
    assert body["kind"] == "attachment"
    assert body["caption"] == "look"
    assert body["mimeType"] == "image/jpeg"  # inferred from .jpg


@pytest.mark.asyncio
async def test_standalone_send_text_then_attachments(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_safe_path(monkeypatch)
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG fake")
    monkeypatch.setenv("PHOTON_SIDECAR_TOKEN", "tok")

    posted: list[tuple[str, dict[str, Any]]] = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"ok": True, "messageId": "m-9"}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url: str, json: dict[str, Any], headers=None):
            posted.append((url, json))
            return _Resp()

    monkeypatch.setattr(photon_adapter.httpx, "AsyncClient", _FakeClient)

    cfg = PlatformConfig(enabled=True, token="", extra={})
    result = await photon_adapter._standalone_send(
        cfg,
        "any;-;+1",
        "hello",
        media_files=[(str(img), False)],
    )

    assert result.get("success") is True
    # First call is the text /send, second is /send-attachment.
    assert posted[0][0].endswith("/send")
    assert posted[0][1]["text"] == "hello"
    assert posted[1][0].endswith("/send-attachment")
    assert posted[1][1]["path"] == str(img)
    assert posted[1][1]["kind"] == "attachment"
    assert posted[1][1]["mimeType"] == "image/png"


def _images(tmp_path, *names: str) -> list[str]:
    files = []
    for name in names:
        p = tmp_path / name
        p.write_bytes(b"\x89PNG fake")
        files.append(str(p))
    return files


@pytest.mark.asyncio
async def test_several_local_images_go_out_as_one_group(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from urllib.parse import quote

    _patch_safe_path(monkeypatch)
    adapter = _make_adapter(monkeypatch)
    calls = _capture_sidecar(adapter)
    files = _images(tmp_path, "a.png", "b c.png", "d.jpg")

    # The gateway hands local images over as quoted file:// URLs with no alt text.
    result = await adapter.send_multiple_images("chat", [(f"file://{quote(f)}", "") for f in files])

    assert result.success is True
    assert calls == [("/send-attachment", {"spaceId": "chat", "paths": files})]


@pytest.mark.asyncio
async def test_refused_group_falls_back_to_one_by_one(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_safe_path(monkeypatch)
    adapter = _make_adapter(monkeypatch)
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _fake_call(path: str, body: dict[str, Any]) -> dict[str, Any]:
        calls.append((path, body))
        if "paths" in body:  # an older sidecar without group support
            raise photon_adapter.PhotonSidecarError(
                path=path, status_code=400, error="spaceId and path are required")
        return {"ok": True, "messageId": "msg-1"}

    adapter._sidecar_call = _fake_call  # type: ignore[assignment]
    files = _images(tmp_path, "a.png", "b.png")

    result = await adapter.send_multiple_images("chat", [(f"file://{f}", "") for f in files])

    assert result.success is True
    assert [body.get("path") for _, body in calls[1:]] == files


@pytest.mark.asyncio
async def test_single_or_captioned_images_go_one_by_one(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_safe_path(monkeypatch)
    adapter = _make_adapter(monkeypatch)
    calls = _capture_sidecar(adapter)
    first, second = _images(tmp_path, "a.png", "b.png")

    await adapter.send_multiple_images("chat", [(f"file://{first}", "")])
    await adapter.send_multiple_images("chat", [(f"file://{first}", ""), (f"file://{second}", "a caption")])

    assert all("paths" not in body for _, body in calls)
    assert [body["path"] for _, body in calls] == [first, first, second]
    assert calls[2][1]["caption"] == "a caption"
