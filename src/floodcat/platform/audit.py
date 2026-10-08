"""Append-only, hash-chained audit log (AUD-01…06)."""
import hashlib
import json
from datetime import timezone
from sqlalchemy import func, select
from .db import audit_events, now, uid

SENSITIVE_KEYS = {'password', 'token', 'secret', 'code', 'text', 'document', 'email_body', 'client_secret', 'totp'}

def _clean(details):
    """Never log secrets or document text (AUD-05)."""
    out = {}
    for k, v in (details or {}).items():
        if any(s in k.lower() for s in SENSITIVE_KEYS) and k not in ('file_sha256', 'prompt_version'): continue
        out[k] = _clean(v) if isinstance(v, dict) else v
    return out

def _iso(at):
    if isinstance(at, str): return at
    return (at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)).isoformat()

def _digest(prev_hash, record):
    body = json.dumps({k: record[k] for k in ('id', 'at', 'org_id', 'actor_id', 'action', 'target_type', 'target_id', 'outcome', 'details')},
                      sort_keys=True, default=str)
    return hashlib.sha256(((prev_hash or '')+body).encode()).hexdigest()

def record(conn, action, *, actor=None, org_id=None, target_type=None, target_id=None, outcome='success', details=None, request=None):
    """Write one event inside the caller's transaction. `actor` is a Principal or None (anonymous / system)."""
    if conn.dialect.name == 'postgresql':  # serialise writers so the hash chain cannot fork
        conn.exec_driver_sql('SELECT pg_advisory_xact_lock(727274)')
    last = conn.execute(select(audit_events.c.hash).order_by(audit_events.c.seq.desc()).limit(1)).scalar()
    event = {'id': uid(), 'at': now(), 'org_id': org_id if org_id is not None else getattr(actor, 'org_id', None),
             'actor_id': getattr(actor, 'user_id', None), 'actor_roles': list(getattr(actor, 'roles', ()) or ()),
             'action': action, 'target_type': target_type, 'target_id': None if target_id is None else str(target_id),
             'outcome': outcome, 'details': _clean(details), 'ip': (request or {}).get('ip'),
             'user_agent': ((request or {}).get('user_agent') or '')[:300] or None, 'request_id': (request or {}).get('request_id')}
    event['prev_hash'] = last
    event['hash'] = _digest(last, {**event, 'at': _iso(event['at'])})
    conn.execute(audit_events.insert().values(**event))
    return event

def verify_chain(conn):
    """Recompute the chain; return (ok, first_bad_seq)."""
    prev = None
    for row in conn.execute(select(audit_events).order_by(audit_events.c.seq)).mappings():
        if row['prev_hash'] != prev or _digest(prev, {**row, 'at': _iso(row['at'])}) != row['hash']:
            return False, row['seq']
        prev = row['hash']
    return True, None

def query(conn, org_id, *, actor_id=None, action=None, since=None, until=None, target_id=None, limit=500):
    q = select(audit_events).order_by(audit_events.c.seq.desc()).limit(limit)
    if org_id is not None: q = q.where(audit_events.c.org_id == org_id)
    if actor_id: q = q.where(audit_events.c.actor_id == actor_id)
    if action: q = q.where(audit_events.c.action.like(f'{action}%'))
    if since: q = q.where(audit_events.c.at >= since)
    if until: q = q.where(audit_events.c.at <= until)
    if target_id: q = q.where(audit_events.c.target_id == str(target_id))
    return [dict(r) for r in conn.execute(q).mappings()]

def count(conn, org_id=None):
    q = select(func.count()).select_from(audit_events)
    if org_id: q = q.where(audit_events.c.org_id == org_id)
    return conn.execute(q).scalar()
