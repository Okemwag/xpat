"""Start the local API and Streamlit app, and stop only the processes started here."""

import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORTS = (("API", 8000), ("Streamlit", 8501))


def check_ports() -> None:
    """Fail before launching either server if one of their ports is occupied."""
    for name, port in PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((HOST, port))
            except OSError as exc:
                raise RuntimeError(
                    f"{name} port {port} is unavailable. Stop the existing server "
                    f"and retry (find it with `netstat -ano | findstr :{port}` on Windows or `lsof -nP -iTCP:{port} -sTCP:LISTEN` elsewhere)."
                ) from exc


def stop(children: list[subprocess.Popen]) -> None:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def run() -> int:
    try:
        check_ports()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    commands = (
        (
            "API",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "floodcat.api.app:create_app",
                "--factory",
                "--host",
                HOST,
                "--port",
                "8000",
            ],
        ),
        (
            "Streamlit",
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "app/streamlit_app.py",
                "--server.headless",
                "true",
                "--server.address",
                HOST,
                "--server.port",
                "8501",
            ],
        ),
    )
    children: list[subprocess.Popen] = []
    sys.path.insert(0, str(ROOT / "src"))
    from floodcat.platform.identity import app_url

    print(
        f"\nOpen Xpat at {app_url()}  (use exactly this address: the sign-in cookie belongs to it)\n",
        flush=True,
    )
    if "localhost" in app_url():
        print(
            "Note: FLOODCAT_APP_URL uses 'localhost'. If the browser says the site cannot be reached, "
            "set FLOODCAT_APP_URL and FLOODCAT_AUTH_URL to http://127.0.0.1:8501 and http://127.0.0.1:8000 in .env.\n",
            flush=True,
        )
    try:
        for _, command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT))
        while True:
            for (name, _), child in zip(commands, children):
                code = child.poll()
                if code is not None:
                    print(
                        f"{name} server exited with code {code}; stopping the other server.",
                        file=sys.stderr,
                    )
                    return code or 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 130
    finally:
        stop(children)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    sys.exit(run())
