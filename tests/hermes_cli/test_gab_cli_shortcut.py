from argparse import Namespace


def test_cmd_gab_launches_chat_with_gab_arya(monkeypatch):
    from hermes_cli import main as main_mod

    captured = {}

    def fake_cmd_chat(args):
        captured["model"] = args.model
        captured["provider"] = args.provider
        captured["query"] = args.query
        captured["quiet"] = args.quiet
        return 0

    monkeypatch.setattr(main_mod, "cmd_chat", fake_cmd_chat)

    result = main_mod.cmd_gab(Namespace(query="hi", quiet=True))

    assert result == 0
    assert captured == {
        "model": "arya",
        "provider": "custom:gab",
        "query": "hi",
        "quiet": True,
    }


def test_cmd_model_gab_shortcut_is_session_chat_not_default_picker(monkeypatch):
    from hermes_cli import main as main_mod

    called = {}

    def fake_cmd_gab(args):
        called["shortcut"] = args.shortcut
        return 0

    def fail_picker(*_args, **_kwargs):
        raise AssertionError("model picker should not open for `hermes model gab`")

    monkeypatch.setattr(main_mod, "cmd_gab", fake_cmd_gab)
    monkeypatch.setattr(main_mod, "select_provider_and_model", fail_picker)

    result = main_mod.cmd_model(Namespace(shortcut="gab"))

    assert result == 0
    assert called == {"shortcut": "gab"}
