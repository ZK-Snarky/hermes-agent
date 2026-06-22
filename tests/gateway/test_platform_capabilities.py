"""Generic PlatformEntry capability hooks: clean_inbox + outbound_sanitize_fn.

These extension points replace hardcoded per-platform branches in the gateway.
The tests use a synthetic platform (not Photon) to prove the mechanism is
generic and upstreamable, then assert the gateway honors the declared
capabilities.
"""

import pytest

from gateway.platform_registry import PlatformEntry, platform_registry
from gateway.run import (
    _gateway_platform_entry,
    _prepare_gateway_status_message,
    _sanitize_gateway_final_response,
)


@pytest.fixture
def synthetic_platform():
    """Register a throwaway platform with both capabilities declared."""
    def sanitize(text: str) -> str:
        if "SECRET-NOTE" in text:
            return "ok"
        return text.upper()

    entry = PlatformEntry(
        name="synthtest",
        label="Synthetic Test",
        adapter_factory=lambda cfg: None,
        check_fn=lambda: True,
        clean_inbox=True,
        outbound_sanitize_fn=sanitize,
    )
    platform_registry.register(entry)
    try:
        yield entry
    finally:
        platform_registry.unregister("synthtest")


def test_clean_inbox_suppresses_status(synthetic_platform):
    assert _prepare_gateway_status_message("synthtest", "lifecycle", "retrying...") is None


def test_outbound_sanitize_fn_is_applied(synthetic_platform):
    assert _sanitize_gateway_final_response("synthtest", "hello") == "HELLO"
    assert _sanitize_gateway_final_response("synthtest", "this has SECRET-NOTE inside") == "ok"


def test_outbound_sanitize_fn_failure_falls_back_to_redaction():
    def boom(text: str) -> str:
        raise RuntimeError("hook broke")

    entry = PlatformEntry(
        name="brokenhook",
        label="Broken Hook",
        adapter_factory=lambda cfg: None,
        check_fn=lambda: True,
        outbound_sanitize_fn=boom,
    )
    platform_registry.register(entry)
    try:
        out = _sanitize_gateway_final_response(
            "brokenhook", "leak sk-ABCDEFGHIJKLMNOP1234567890 here"
        )
        # Hook raised, so core falls back to baseline secret redaction.
        assert "[REDACTED]" in out
        assert "sk-ABCDEFGHIJKLMNOP1234567890" not in out
    finally:
        platform_registry.unregister("brokenhook")


def test_unregistered_platform_has_no_entry_and_is_unchanged():
    # No registry entry => no capability => status passes through unchanged.
    assert _gateway_platform_entry("ghostplatform") is None
    assert (
        _prepare_gateway_status_message("ghostplatform", "lifecycle", "retrying...")
        == "retrying..."
    )
    assert _sanitize_gateway_final_response("ghostplatform", "hello") == "hello"


def test_default_platform_entry_has_capabilities_off():
    entry = PlatformEntry(
        name="defaults",
        label="Defaults",
        adapter_factory=lambda cfg: None,
        check_fn=lambda: True,
    )
    assert entry.clean_inbox is False
    assert entry.outbound_sanitize_fn is None
