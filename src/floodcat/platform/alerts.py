"""Security alerts from the audit log (AUD-08). Run every few minutes: `flood-cat alerts`."""
from datetime import timedelta
from sqlalchemy import func, select
from . import audit
from .data import notify_role
from .db import audit_events, memberships, now, users
from .email import send

WINDOW = timedelta(minutes=15)
RULES = {'failed_signins': 10, 'exports_per_user': 20}

def _already_alerted(conn, org_id, kind):
    return conn.execute(select(func.count()).select_from(audit_events).where(
        audit_events.c.action == 'alert.raised', audit_events.c.org_id == org_id, audit_events.c.target_id == kind,
        audit_events.c.at >= now()-WINDOW)).scalar() > 0

def _raise(conn, org_id, kind, message):
    if _already_alerted(conn, org_id, kind): return False
    notify_role(conn, org_id, 'admin', 'security_alert', message); notify_role(conn, org_id, 'owner', 'security_alert', message)
    admins = conn.execute(select(users.c.email, memberships.c.roles).join(memberships, memberships.c.user_id == users.c.id)
                          .where(memberships.c.org_id == org_id, memberships.c.status == 'active')).all()
    for email_addr, roles in admins:
        if {'owner', 'admin'} & set(roles): send(conn, email_addr, 'Xpat security alert', [message, 'Review the audit log in Xpat.'], kind='security_alert')
    audit.record(conn, 'alert.raised', org_id=org_id, target_type='alert', target_id=kind, details={'message': message})
    return True

def evaluate(conn):
    raised = []
    since = now()-WINDOW
    # Repeated failed sign-ins against members of one organisation.
    failures = conn.execute(select(memberships.c.org_id, func.count()).select_from(audit_events)
                            .join(memberships, memberships.c.user_id == audit_events.c.target_id)
                            .where(audit_events.c.action == 'auth.login_failed', audit_events.c.at >= since).group_by(memberships.c.org_id)).all()
    for org_id, n in failures:
        if n >= RULES['failed_signins'] and _raise(conn, org_id, 'failed_signins', f'{n} failed sign-in attempts on your users in the last 15 minutes.'):
            raised.append((org_id, 'failed_signins'))
    exports = conn.execute(select(audit_events.c.org_id, audit_events.c.actor_id, func.count()).where(
        audit_events.c.action.in_(('run.exported', 'org.exported')), audit_events.c.at >= since).group_by(audit_events.c.org_id, audit_events.c.actor_id)).all()
    for org_id, actor, n in exports:
        if n >= RULES['exports_per_user'] and _raise(conn, org_id, f'mass_export:{actor}', f'One user exported data {n} times in 15 minutes.'):
            raised.append((org_id, 'mass_export'))
    for e in conn.execute(select(audit_events).where(audit_events.c.action == 'user.roles_changed', audit_events.c.at >= since)).mappings():
        added = set((e['details'] or {}).get('after', [])) - set((e['details'] or {}).get('before', []))
        if {'owner', 'admin'} & added and _raise(conn, e['org_id'], f"escalation:{e['target_id']}", f"Administrator access was granted ({', '.join(sorted(added))})."):
            raised.append((e['org_id'], 'escalation'))
    ok, bad = audit.verify_chain(conn)
    if not ok:
        audit.record(conn, 'alert.audit_chain_broken', target_type='audit', target_id=str(bad), outcome='error')
        raised.append((None, 'audit_chain_broken'))
    return raised
