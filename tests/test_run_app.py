"""The local launcher must leave existing servers alone and clean up its own children."""

import importlib.util
import socket
from pathlib import Path
import pytest


SPEC = importlib.util.spec_from_file_location(
    "run_app", Path(__file__).resolve().parents[1] / "scripts" / "run_app.py"
)
run_app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_app)


def test_check_ports_identifies_occupied_port(monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((run_app.HOST, 0))
        listener.listen()
        port = listener.getsockname()[1]
        monkeypatch.setattr(run_app, "PORTS", (("Test service", port),))
        with pytest.raises(
            RuntimeError, match=f"Test service port {port} is unavailable"
        ):
            run_app.check_ports()


def test_occupied_port_starts_no_server(monkeypatch, capsys):
    def busy(*_ports):
        raise RuntimeError("API port 8000 is unavailable")

    monkeypatch.setattr(run_app, "check_ports", busy)
    monkeypatch.setattr(
        run_app.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("server started")
        ),
    )
    assert run_app.run() == 1
    assert "port 8000" in capsys.readouterr().err


def test_server_exit_stops_sibling(monkeypatch):
    class Child:
        def __init__(self, exit_code):
            self.exit_code = exit_code
            self.terminated = False

        def poll(self):
            return -15 if self.terminated else self.exit_code

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return self.poll()

    api, ui = Child(1), Child(None)
    children = iter((api, ui))
    monkeypatch.setattr(run_app, "check_ports", lambda *_ports: None)
    monkeypatch.setattr(
        run_app.subprocess, "Popen", lambda *_args, **_kwargs: next(children)
    )
    assert run_app.run(two_servers=True) == 1
    assert ui.terminated


def test_default_is_one_server_on_one_address():
    ports, commands, env = run_app.plan(two_servers=False)
    assert ports == (("Xpat", 8501),) and len(commands) == 1
    name, command = commands[0]
    assert "app/asgi_app.py" in command and command[-1] == "8501"
    assert (
        env["FLOODCAT_AUTH_PORT"] == "8501"
    )  # sign-in links stay on the interface's address


def test_two_server_layout_keeps_sign_in_on_8000(monkeypatch):
    monkeypatch.delenv("FLOODCAT_AUTH_PORT", raising=False)
    ports, commands, env = run_app.plan(two_servers=True)
    assert [p for _, p in ports] == [8000, 8501] and len(commands) == 2
    assert env["FLOODCAT_AUTH_PORT"] == "8000"


def test_sign_in_links_follow_the_configured_port(monkeypatch):
    from floodcat.platform import identity

    identity.use_request_host(None)  # no browser host left over from another test
    monkeypatch.delenv("FLOODCAT_APP_PORT", raising=False)
    monkeypatch.delenv("FLOODCAT_AUTH_URL", raising=False)
    monkeypatch.delenv("FLOODCAT_APP_URL", raising=False)
    monkeypatch.setenv("FLOODCAT_AUTH_PORT", "8501")
    assert identity.auth_url() == identity.app_url() == "http://127.0.0.1:8501"
    monkeypatch.setenv("FLOODCAT_AUTH_PORT", "not-a-port")
    assert (
        identity.auth_url() == "http://127.0.0.1:8501"
    )  # invalid → same address as the interface
    monkeypatch.delenv("FLOODCAT_AUTH_PORT")
    assert (
        identity.auth_url() == "http://127.0.0.1:8501"
    )  # CLI messages and e-mailed links use the one address too
    monkeypatch.setenv("FLOODCAT_AUTH_PORT", "8000")
    assert identity.auth_url() == "http://127.0.0.1:8000"  # run_app.py --two-servers


def test_single_address_wrapper_hands_auth_and_api_paths_to_fastapi():
    import ast

    source = (Path(__file__).resolve().parents[1] / "app" / "asgi_app.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    # Streamlit only detects the server from a top-level `app = st.App(...)`.
    assert any(
        isinstance(n, ast.Assign)
        and n.targets[0].id == "app"
        and isinstance(n.value, ast.Call)
        and ast.unparse(n.value.func) == "st.App"
        for n in tree.body
        if isinstance(n, ast.Assign)
    )
    assert '"/auth/{rest:path}"' in source and '"/v1/{rest:path}"' in source
