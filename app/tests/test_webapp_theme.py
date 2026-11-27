"""Default colour theme served by the backend (server.App + --default-theme).

Pins: GET /api/ui/config is public (the sign-in screen needs it before a session exists) and returns the server's
default theme; only 'light' and 'dark' exist (no 'system'); the default is 'light' unless --default-theme or
$SMARTPARSER_DEFAULT_THEME says otherwise; an unknown theme is refused at start-up."""
import pytest

from smartparser.webapp import server as server_mod
from smartparser.webapp.server import App

from .test_webapp_api import ctx_for
from .test_webapp_auth import H, make_auth


def test_ui_config_is_public_and_defaults_to_light(tmp_path):
    app = App(ctx_for(tmp_path), make_auth())
    s, b, _ = H(app, "GET", "/api/ui/config")
    assert s == 200 and b == {"default_theme": "light", "themes": ["light", "dark"]}


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_ui_config_returns_configured_default(tmp_path, theme):
    s, b, _ = H(App(ctx_for(tmp_path), make_auth(), default_theme=theme), "GET", "/api/ui/config")
    assert s == 200 and b["default_theme"] == theme


def test_ui_config_without_auth(tmp_path):
    s, b, _ = H(App(ctx_for(tmp_path), None, default_theme="dark"), "GET", "/api/ui/config")
    assert s == 200 and b["default_theme"] == "dark"


def test_system_theme_is_refused(tmp_path):
    with pytest.raises(ValueError):
        App(ctx_for(tmp_path), None, default_theme="system")


def test_other_ui_routes_not_found(tmp_path):
    app = App(ctx_for(tmp_path), make_auth())
    assert H(app, "GET", "/api/ui/other")[0] == 404
    assert H(app, "POST", "/api/ui/config")[0] == 404


@pytest.mark.parametrize("argv,env,expected", [
    ([], None, "light"),
    ([], "dark", "dark"),
    (["--default-theme", "dark"], None, "dark"),
    (["--default-theme", "light"], "dark", "light"),
])
def test_cli_default_theme(tmp_path, monkeypatch, argv, env, expected):
    seen = {}

    class Stop(Exception):
        pass

    def fake_serve(ctx, port, auth, default_theme):
        seen["theme"] = default_theme
        raise Stop

    if env is None:
        monkeypatch.delenv("SMARTPARSER_DEFAULT_THEME", raising=False)
    else:
        monkeypatch.setenv("SMARTPARSER_DEFAULT_THEME", env)
    monkeypatch.setattr(server_mod, "serve", fake_serve)
    monkeypatch.setattr("sys.argv", ["server", "--root", str(tmp_path / "ws"), "--insecure-no-auth", *argv])
    with pytest.raises(Stop):
        server_mod.main()
    assert seen["theme"] == expected


@pytest.mark.parametrize("argv,env", [(["--default-theme", "system"], None), ([], "system")])
def test_cli_rejects_system_theme(tmp_path, monkeypatch, argv, env):
    if env is None:
        monkeypatch.delenv("SMARTPARSER_DEFAULT_THEME", raising=False)
    else:
        monkeypatch.setenv("SMARTPARSER_DEFAULT_THEME", env)
    monkeypatch.setattr("sys.argv", ["server", "--root", str(tmp_path / "ws"), "--insecure-no-auth", *argv])
    with pytest.raises(SystemExit) as e:
        server_mod.main()
    assert e.value.code == 2
