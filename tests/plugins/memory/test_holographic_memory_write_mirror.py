"""on_memory_write mirrors replace/remove, not only add.

The built-in memory tool passes the entry's previous text as
``metadata["previous_content"]`` on replace and remove. Before this, only add
was mirrored, so a corrected or deleted USER.md / MEMORY.md entry lived on in
the fact store and kept coming back through prefetch.
"""

from plugins.memory.holographic import HolographicMemoryProvider


def _provider(tmp_path):
    provider = HolographicMemoryProvider(config={"db_path": str(tmp_path / "memory_store.db"), "hrr_dim": 64})
    provider.initialize(session_id="test-session")
    return provider


def _contents(provider):
    return sorted(fact["content"] for fact in provider._store.list_facts(limit=100))


def test_replace_updates_the_mirrored_fact(tmp_path):
    provider = _provider(tmp_path)
    provider.on_memory_write("add", "user", "Prefers fast mode by default")
    provider.on_memory_write("replace", "user", "Prefers high effort, fast only for live chat",
                             metadata={"previous_content": "Prefers fast mode by default"})
    assert _contents(provider) == ["Prefers high effort, fast only for live chat"]


def test_remove_deletes_the_mirrored_fact(tmp_path):
    provider = _provider(tmp_path)
    provider.on_memory_write("add", "memory", "Old note")
    provider.on_memory_write("add", "memory", "Keep me")
    provider.on_memory_write("remove", "memory", "", metadata={"previous_content": "Old note"})
    assert _contents(provider) == ["Keep me"]


def test_replace_without_previous_content_changes_nothing(tmp_path):
    provider = _provider(tmp_path)
    provider.on_memory_write("add", "user", "A fact")
    provider.on_memory_write("replace", "user", "Another fact")
    provider.on_memory_write("remove", "user", "", metadata={})
    assert _contents(provider) == ["A fact"]
