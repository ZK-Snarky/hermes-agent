"""``platforms.telegram.extra.dm_threads``: ``shared`` keys a Telegram DM as one session whatever
``message_thread_id`` its messages carry; ``per_thread`` (default) keeps one session per thread."""

import logging

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.event import MessageEvent
from gateway.session import SessionSource, SessionStore
from tests.gateway.test_base_topic_sessions import DummyTelegramAdapter


def _store(tmp_path, monkeypatch, extra):
    config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="t", extra=extra)})
    return SessionStore(sessions_dir=tmp_path, config=config)


def _dm(thread_id):
    return SessionSource(platform=Platform.TELEGRAM, chat_id="111", chat_type="dm", user_id="111",
                         thread_id=thread_id)


def _session_ids(store):
    return {store.get_or_create_session(_dm(tid)).session_id for tid in ("501", "777", None)}


@pytest.mark.parametrize("extra, expected", [
    ({}, 3),
    ({"dm_threads": "per_thread"}, 3),
    ({"dm_threads": "shared"}, 1),
    # Operator-declared topics stay their own workspaces under shared.
    ({"dm_threads": "shared", "dm_topics": [{"chat_id": 111, "topics": [{"name": "W", "thread_id": 501}]}]}, 2),
])
def test_dm_thread_ids_share_one_session_only_when_opted_in(tmp_path, monkeypatch, extra, expected):
    assert len(_session_ids(_store(tmp_path, monkeypatch, extra))) == expected


def test_topic_mode_lanes_stay_isolated_under_shared(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch, {"dm_threads": "shared"})
    store._scoped_persistence().routing.enable_topic_mode(chat_id="111", user_id="111")
    assert len(_session_ids(store)) == 3


def test_unknown_mode_warns_and_keeps_per_thread(tmp_path, monkeypatch, caplog):
    store = _store(tmp_path, monkeypatch, {"dm_threads": "shard"})
    with caplog.at_level(logging.WARNING, logger="gateway.session_dm_threads"):
        assert len(_session_ids(store)) == 3
    assert "per_thread, shared" in caplog.text


def test_adapter_batch_key_matches_the_store_key(tmp_path, monkeypatch):
    """The adapter's batching/busy key and the store's routing key must agree, or a shared DM
    still runs one busy guard per thread."""
    store = _store(tmp_path, monkeypatch, {"dm_threads": "shared"})
    adapter = DummyTelegramAdapter()
    adapter.config.extra["dm_threads"] = "shared"
    adapter.set_session_store(store)
    keys = {adapter._event_session_key(MessageEvent(text="hi", source=_dm(tid))) for tid in ("501", "777")}
    assert keys == {store._generate_session_key(_dm("501"))} == {"agent:main:telegram:dm:111"}


def test_background_delegation_result_returns_to_the_thread_it_was_asked_in(tmp_path, monkeypatch):
    """The shared session was created in thread 501, so its stored origin names 501. A background
    delegation asked for from thread 777 must report back to 777, as a reply would."""
    from gateway.run import GatewayRunner
    from gateway.session_context import clear_session_vars, set_session_vars
    from tests.waiting import wait_until
    from tools import async_delegation as ad
    from tools.process_registry import process_registry

    extra = {"dm_threads": "shared"}
    runner = GatewayRunner(GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="t", extra=extra)}))
    adapter = DummyTelegramAdapter()
    adapter.config.extra.update(extra)
    runner.adapters[Platform.TELEGRAM] = adapter
    key = runner.session_store.get_or_create_session(_dm("501")).session_key

    ad._reset_for_tests()
    tokens = set_session_vars(platform="telegram", chat_id="111", chat_type="dm", thread_id="777",
                              user_id="111", session_key=key)
    try:
        handle = ad.dispatch_async_delegation(
            goal="research", context=None, toolsets=None, role="leaf", model="m", session_key=key,
            runner=lambda: {"status": "completed", "summary": "done"})
    finally:
        clear_session_vars(tokens)

    def completion():
        while not process_registry.completion_queue.empty():
            evt = process_registry.completion_queue.get_nowait()
            if evt.get("delegation_id") == handle["delegation_id"]:
                return evt
        return None

    evt = wait_until(completion, timeout=10, what="the delegation's completion event")
    source = runner._build_process_event_source(evt)
    assert (source.platform, source.chat_id, source.thread_id) == (Platform.TELEGRAM, "111", "777")
