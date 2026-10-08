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
    def busy():
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
    monkeypatch.setattr(run_app, "check_ports", lambda: None)
    monkeypatch.setattr(
        run_app.subprocess, "Popen", lambda *_args, **_kwargs: next(children)
    )
    assert run_app.run() == 1
    assert ui.terminated
