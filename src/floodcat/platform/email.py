"""Transactional e-mail via Resend (DEC-05), with a development outbox.

Every message is written to the `email_outbox` table first. With RESEND_API_KEY set it is then sent through
the Resend API; without it (development) it stays in the outbox, where developers can read links.
"""

import html
import os
from sqlalchemy import select
from .db import now, outbox, uid

RESEND_URL = "https://api.resend.com/emails"


def configured():
    return bool(os.getenv("RESEND_API_KEY") and os.getenv("RESEND_FROM"))


def _layout(title, paragraphs, action=None):
    parts = "".join(
        f'<p style="margin:0 0 14px;line-height:1.5">{html.escape(p)}</p>'
        for p in paragraphs
    )
    button = (
        (
            f'<p style="margin:22px 0"><a href="{html.escape(action[1])}" style="background:#2a78d6;color:#fff;padding:11px 18px;'
            f'border-radius:8px;text-decoration:none;font-weight:600">{html.escape(action[0])}</a></p>'
            f'<p style="font-size:12px;color:#666">If the button does not work, paste this link into your browser:<br>{html.escape(action[1])}</p>'
        )
        if action
        else ""
    )
    return (
        f'<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;padding:24px;color:#111">'
        f'<h2 style="margin:0 0 16px">{html.escape(title)}</h2>{parts}{button}'
        f'<p style="font-size:12px;color:#666;margin-top:28px">Xpat · flood risk intelligence. If you did not expect this e-mail, you can ignore it.</p></div>'
    )


def send(conn, to, subject, paragraphs, action=None, kind=None, client=None):
    text = "\n\n".join(paragraphs) + (f"\n\n{action[0]}: {action[1]}" if action else "")
    message = {
        "id": uid(),
        "to": to,
        "subject": subject,
        "text": text,
        "html": _layout(subject, paragraphs, action),
        "kind": kind,
        "created_at": now(),
    }
    conn.execute(outbox.insert().values(**message))
    if configured():
        import httpx

        try:
            response = (client or httpx).post(
                RESEND_URL,
                timeout=10,
                headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                json={
                    "from": os.environ["RESEND_FROM"],
                    "to": [to],
                    "subject": subject,
                    "html": message["html"],
                    "text": text,
                },
            )
            response.raise_for_status()
            conn.execute(
                outbox.update()
                .where(outbox.c.id == message["id"])
                .values(sent_at=now(), provider_id=str(response.json().get("id", "")))
            )
        except Exception as exc:
            conn.execute(
                outbox.update()
                .where(outbox.c.id == message["id"])
                .values(error=f"{type(exc).__name__}: {str(exc)[:200]}")
            )
    return message["id"]


def recent(conn, to=None, limit=20):
    q = select(outbox).order_by(outbox.c.created_at.desc()).limit(limit)
    if to:
        q = q.where(outbox.c.to == to)
    return [dict(r) for r in conn.execute(q).mappings()]
