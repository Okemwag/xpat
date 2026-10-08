"""Malware scanning of uploads through ClamAV's clamd INSTREAM protocol (SEC-04).

Set FLOODCAT_CLAMAV=host:port (or unix:/path/clamd.sock). In production (FLOODCAT_ENV=production) scanning is required:
uploads are refused if the scanner cannot be reached. In development an unconfigured scanner is skipped and reported.
"""

import os
import socket
import struct
from ..core.errors import ModelError

CHUNK = 64 * 1024


def _connect(target, timeout):
    if target.startswith("unix:"):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(target[5:])
        return s
    host, _, port = target.rpartition(":")
    return socket.create_connection((host or "localhost", int(port)), timeout=timeout)


def scan(data, timeout=30):
    """Return 'clean', 'skipped' (no scanner configured outside production); raise ModelError if infected or unavailable."""
    target = os.getenv("FLOODCAT_CLAMAV")
    if not target:
        if os.getenv("FLOODCAT_ENV") == "production":
            raise ModelError(
                "scanner_unavailable",
                "Uploads are disabled: the malware scanner is not configured",
            )
        return "skipped"
    try:
        with _connect(target, timeout) as s:
            s.sendall(b"zINSTREAM\0")
            for i in range(0, len(data), CHUNK):
                chunk = data[i : i + CHUNK]
                s.sendall(struct.pack(">I", len(chunk)) + chunk)
            s.sendall(struct.pack(">I", 0))
            reply = b""
            while not reply.endswith(b"\0"):
                part = s.recv(4096)
                if not part:
                    break
                reply += part
    except OSError:
        raise ModelError(
            "scanner_unavailable",
            "The malware scanner could not be reached; the file was not accepted",
        ) from None
    text = reply.rstrip(b"\0").decode(errors="replace")
    if text.endswith("OK"):
        return "clean"
    if "FOUND" in text:
        raise ModelError(
            "malware_detected", "The file was rejected by the malware scanner"
        )
    raise ModelError(
        "scanner_error",
        "The malware scanner returned an error; the file was not accepted",
    )
