"""Start Xpat locally, and stop only the processes started here.

Default: one server on http://127.0.0.1:8501 serving the interface, the sign-in pages and the API
(app/asgi_app.py), so the browser never leaves that address.

`--two-servers`: the earlier layout, with the sign-in pages and API on port 8000 and the interface on port 8501.
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
APP_PORT = 8501
API_PORT = 8000
PORTS = (("API", API_PORT), ("Streamlit", APP_PORT))


def check_ports(ports=None) -> None:
    """Fail before launching any server if one of its ports is occupied."""
    for name, port in ports or PORTS:
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


def streamlit_command(script):
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        script,
        "--server.headless",
        "true",
        "--server.address",
        HOST,
        "--server.port",
        str(APP_PORT),
    ]


def plan(two_servers):
    """(ports to check, [(name, command)], environment for the children)."""
    env = dict(os.environ)
    if two_servers:
        env.setdefault("FLOODCAT_AUTH_PORT", str(API_PORT))
        commands = [
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
                    str(API_PORT),
                ],
            ),
            ("Streamlit", streamlit_command("app/streamlit_app.py")),
        ]
        return PORTS, commands, env
    env["FLOODCAT_AUTH_PORT"] = str(
        APP_PORT
    )  # sign-in pages live on the interface's own address
    return (("Xpat", APP_PORT),), [("Xpat", streamlit_command("app/asgi_app.py"))], env


def run(two_servers=False) -> int:
    ports, commands, env = plan(two_servers)
    try:
        check_ports(ports)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

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
            "set it to http://127.0.0.1:8501 in .env.\n",
            flush=True,
        )
    try:
        for _, command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT, env=env))
        while True:
            for (name, _), child in zip(commands, children):
                code = child.poll()
                if code is not None:
                    print(
                        f"{name} server exited with code {code}"
                        + (
                            "; stopping the other server." if len(children) > 1 else "."
                        ),
                        file=sys.stderr,
                    )
                    return code or 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 130
    finally:
        stop(children)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start Xpat locally.")
    parser.add_argument(
        "--two-servers",
        action="store_true",
        help="Sign-in pages and API on port 8000, interface on 8501 (the earlier layout)",
    )
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    sys.exit(run(two_servers=args.two_servers))
