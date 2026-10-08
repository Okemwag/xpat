"""Organisation-scoped business data. Every function takes a Principal and enforces tenant isolation and permissions.

ORG-03…05, RBAC-04, RBAC-06, RBAC-07, DATA-02, DATA-04, GOV-01…06, WF-01…06.
"""
import json
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import select
from ..core.errors import ModelError
from . import audit, security
from .db import (assumption_sets, comments, evidence, extractions, memberships, notifications, organisations, runs, submissions, now, uid)
from .identity import _aware, settings_for
from .rbac import can_see_run, require

# Notifications (WF-06) ----------------------------------------------------------------------------------
def notify(conn, org_id, user_id, kind, message, link=None):
    conn.execute(notifications.insert().values(id=uid(), org_id=org_id, user_id=user_id, kind=kind, message=str(message)[:1000], link=link,
                                                created_at=now()))

def notify_role(conn, org_id, role, kind, message, link=None, exclude=None):
    rows = conn.execute(select(memberships.c.user_id, memberships.c.roles).where(memberships.c.org_id == org_id, memberships.c.status == 'active'))
    for user_id, roles in rows:
        if role in roles and user_id != exclude: notify(conn, org_id, user_id, kind, message, link)

def list_notifications(conn, principal, unread_only=False, limit=50):
    q = select(notifications).where(notifications.c.user_id == principal.user_id, notifications.c.org_id == principal.org_id)
    if unread_only: q = q.where(notifications.c.read_at.is_(None))
    return [dict(r) for r in conn.execute(q.order_by(notifications.c.created_at.desc()).limit(limit)).mappings()]

def mark_read(conn, principal, notification_id=None):
    q = notifications.update().where(notifications.c.user_id == principal.user_id, notifications.c.read_at.is_(None))
    if notification_id: q = q.where(notifications.c.id == notification_id)
    conn.execute(q.values(read_at=now()))

# Runs (ORG-03, RBAC-06) ---------------------------------------------------------------------------------
def _summary(report):
    base = report['runs']['baseline']
    curve = {p['return_period_years']: p['loss_kes'] for p in base['ep_curve']}
    return {'modelled_count': report['modelled_count'], 'modelled_tiv_kes': report['modelled_tiv_kes'], 'aal_kes': base['aal']['aal_kes'],
            'loss_rarest_kes': curve[max(curve)], 'ai_enabled': report['ai_contribution']['enabled'],
            'origin': report.get('exposure_origin', {}).get('labels', ['SYNTHETIC']), 'config_version': report['config']['version'],
            'partial': report['partial']}

def save_run(conn, principal, report, rows, label, settings=None, visibility=None, team_id=None, submission_id=None,
             assumption_set_id=None, request=None):
    require(principal, 'runs.create')
    if principal.extra.get('read_only'): raise ModelError('read_only', 'This organisation is suspended (read-only)')
    visibility = visibility or settings_for(conn, principal.org_id)['default_visibility']
    if visibility not in ('private', 'team', 'org'): raise ModelError('invalid', 'Unknown visibility')
    team_id = team_id or (principal.team_ids[0] if principal.team_ids else None)
    if team_id and team_id not in principal.team_ids: raise ModelError('forbidden', 'You can only share with your own teams')
    if visibility == 'team' and not team_id: visibility = 'private'
    if submission_id: _submission(conn, principal, submission_id)
    run_id = report['analysis_id']
    clean_settings = {k: v for k, v in (settings or {}).items() if k != 'evidence'}
    conn.execute(runs.insert().values(id=run_id, org_id=principal.org_id, owner_id=principal.user_id, team_id=team_id, visibility=visibility,
                                      label=str(label)[:200], created_at=now(), submission_id=submission_id, summary=_summary(report),
                                      payload=json.loads(json.dumps(report, default=str)), inputs_enc=security.encrypt(json.dumps(rows, default=str)),
                                      settings=json.loads(json.dumps(clean_settings, default=str)), assumption_set_id=assumption_set_id))
    if submission_id: _attach_run(conn, submission_id, report)
    from .orgs import record_usage
    record_usage(conn, principal.org_id, principal.user_id, 'properties_modelled', report['modelled_count'])
    audit.record(conn, 'run.created', actor=principal, target_type='run', target_id=run_id,
                 details={'properties': report['modelled_count'], 'visibility': visibility, 'origin': _summary(report)['origin'],
                          'config_fingerprint': report['config_fingerprint'], 'input_fingerprint': report['input_fingerprint']}, request=request)
    return run_id

def _run_row(conn, principal, run_id):
    row = conn.execute(select(runs).where(runs.c.id == str(run_id), runs.c.org_id == principal.org_id, runs.c.deleted_at.is_(None))).mappings().first()
    if not row or not can_see_run(principal, row):
        audit.record(conn, 'run.access_denied', actor=principal, target_type='run', target_id=run_id, outcome='denied')
        raise ModelError('not_found', 'Analysis not found')
    return row

def list_runs(conn, principal, mine_only=False, submission_id=None, limit=200):
    require(principal, 'runs.read')
    q = select(runs.c.id, runs.c.org_id, runs.c.owner_id, runs.c.team_id, runs.c.visibility, runs.c.label, runs.c.created_at, runs.c.summary,
               runs.c.submission_id).where(runs.c.org_id == principal.org_id, runs.c.deleted_at.is_(None))
    if mine_only: q = q.where(runs.c.owner_id == principal.user_id)
    if submission_id: q = q.where(runs.c.submission_id == submission_id)
    rows = conn.execute(q.order_by(runs.c.created_at.desc()).limit(limit)).mappings()
    return [dict(r) for r in rows if can_see_run(principal, r)]

def get_run(conn, principal, run_id, with_inputs=False, request=None):
    row = _run_row(conn, principal, run_id)
    out = dict(row); out.pop('inputs_enc')
    if with_inputs:
        require(principal, 'runs.create')
        out['inputs'] = json.loads(security.decrypt(row['inputs_enc'])) if row['inputs_enc'] else []
    audit.record(conn, 'run.opened', actor=principal, target_type='run', target_id=run_id, request=request)
    return out

def record_export(conn, principal, run_id, fmt, request=None):
    require(principal, 'runs.export'); _run_row(conn, principal, run_id)
    audit.record(conn, 'run.exported', actor=principal, target_type='run', target_id=run_id, details={'format': fmt}, request=request)

def set_visibility(conn, principal, run_id, visibility, team_id=None, request=None):
    row = _run_row(conn, principal, run_id)
    if row['owner_id'] != principal.user_id: raise ModelError('forbidden', 'Only the owner can change who sees this analysis')
    if visibility not in ('private', 'team', 'org'): raise ModelError('invalid', 'Unknown visibility')
    if team_id and team_id not in principal.team_ids: raise ModelError('forbidden', 'You can only share with your own teams')
    conn.execute(runs.update().where(runs.c.id == row['id']).values(visibility=visibility, team_id=team_id or row['team_id']))
    audit.record(conn, 'run.shared', actor=principal, target_type='run', target_id=run_id, details={'visibility': visibility}, request=request)

def delete_run(conn, principal, run_id, request=None):
    row = _run_row(conn, principal, run_id)
    if row['owner_id'] != principal.user_id and not principal.can('runs.delete_any'):
        raise ModelError('forbidden', 'Only the owner or the head of underwriting can delete this analysis')
    conn.execute(runs.update().where(runs.c.id == row['id']).values(deleted_at=now(), inputs_enc=None, payload={}))
    audit.record(conn, 'run.deleted', actor=principal, target_type='run', target_id=run_id, request=request)

def reassign_owner(conn, org_id, from_user, to_user):
    n = conn.execute(runs.update().where(runs.c.org_id == org_id, runs.c.owner_id == from_user).values(owner_id=to_user)).rowcount
    n += conn.execute(submissions.update().where(submissions.c.org_id == org_id, submissions.c.assignee_id == from_user)
                      .values(assignee_id=to_user)).rowcount
    return n

# Extraction records (DATA-02) ---------------------------------------------------------------------------
def save_extraction(conn, principal, document, result, consent, decisions=None, run_id=None, request=None):
    require(principal, 'ai.extract')
    extraction_id = uid()
    conn.execute(extractions.insert().values(id=extraction_id, org_id=principal.org_id, user_id=principal.user_id, created_at=now(),
                                             file_sha256=document['digest'], file_kind=document['kind'], pages=document.get('pages'),
                                             model=result.get('model'), prompt_version=result.get('prompt_version'),
                                             redaction=document.get('redacted', {}), consent=bool(consent),
                                             result=json.loads(json.dumps(result, default=str)), decisions=decisions or {}, run_id=run_id))
    from .orgs import record_usage
    record_usage(conn, principal.org_id, principal.user_id, 'documents_read', 1)
    audit.record(conn, 'ai.document_extracted', actor=principal, target_type='extraction', target_id=extraction_id,
                 details={'file_sha256': document['digest'], 'kind': document['kind'], 'pages': document.get('pages'), 'model': result.get('model'),
                          'prompt_version': result.get('prompt_version'), 'redaction': document.get('redacted', {}), 'consent': bool(consent),
                          'properties': len(result.get('properties', []))}, request=request)
    return extraction_id

def link_extraction(conn, principal, extraction_id, run_id, decisions):
    conn.execute(extractions.update().where(extractions.c.id == extraction_id, extractions.c.org_id == principal.org_id)
                 .values(run_id=run_id, decisions=json.loads(json.dumps(decisions, default=str))))

# Evidence (ORG-07, RBAC-04) -----------------------------------------------------------------------------
def add_evidence(conn, principal, item, request=None):
    require(principal, 'evidence.add')
    if conn.execute(select(evidence.c.pk).where(evidence.c.org_id == principal.org_id, evidence.c.evidence_id == item.evidence_id)).scalar():
        raise ModelError('duplicate_evidence', 'This passage is already in the evidence library')
    conn.execute(evidence.insert().values(pk=uid(), org_id=principal.org_id, evidence_id=item.evidence_id, created_by=principal.user_id,
                                          payload=item.to_dict(), created_at=now(), updated_at=now()))
    notify_role(conn, principal.org_id, 'reviewer', 'evidence_pending', f'New flood evidence to review: {item.location_name}', exclude=principal.user_id)
    audit.record(conn, 'evidence.added', actor=principal, target_type='evidence', target_id=item.evidence_id,
                 details={'location': item.location_name, 'mechanism': item.mechanism}, request=request)

def list_evidence(conn, org_id):
    from ..ai.evidence import Evidence
    rows = conn.execute(select(evidence).where(evidence.c.org_id == org_id).order_by(evidence.c.created_at)).mappings()
    return [(Evidence(**r['payload']), {'created_by': r['created_by']}) for r in rows]

def _evidence_row(conn, principal, evidence_id):
    row = conn.execute(select(evidence).where(evidence.c.org_id == principal.org_id, evidence.c.evidence_id == evidence_id)).mappings().first()
    if not row: raise ModelError('not_found', 'Evidence not found')
    return row

def approve_evidence(conn, principal, evidence_id, request=None):
    require(principal, 'evidence.approve')
    row = _evidence_row(conn, principal, evidence_id)
    if row['created_by'] == principal.user_id and settings_for(conn, principal.org_id)['enforce_separation_of_duties']:
        audit.record(conn, 'evidence.approve_denied', actor=principal, target_type='evidence', target_id=evidence_id, outcome='denied',
                     details={'reason': 'separation_of_duties'}, request=request)
        raise ModelError('separation_of_duties', 'Someone other than the person who added this evidence must approve it')
    from ..ai.evidence import Evidence
    updated = Evidence(**{**row['payload'], 'approved': True, 'reviewer': principal.display_name})
    conn.execute(evidence.update().where(evidence.c.pk == row['pk']).values(payload=updated.to_dict(), updated_at=now()))
    audit.record(conn, 'evidence.approved', actor=principal, target_type='evidence', target_id=evidence_id, request=request)
    return updated

def withdraw_evidence(conn, principal, evidence_id, request=None):
    require(principal, 'evidence.approve')
    row = _evidence_row(conn, principal, evidence_id)
    conn.execute(evidence.update().where(evidence.c.pk == row['pk']).values(payload={**row['payload'], 'approved': False, 'reviewer': None},
                                                                            updated_at=now()))
    audit.record(conn, 'evidence.withdrawn', actor=principal, target_type='evidence', target_id=evidence_id, request=request)

def delete_evidence(conn, principal, evidence_id, request=None):
    row = _evidence_row(conn, principal, evidence_id)
    if row['created_by'] != principal.user_id and not principal.can('evidence.approve'):
        raise ModelError('forbidden', 'Only the person who added it or a reviewer can delete evidence')
    conn.execute(evidence.delete().where(evidence.c.pk == row['pk']))
    audit.record(conn, 'evidence.deleted', actor=principal, target_type='evidence', target_id=evidence_id, request=request)

# Assumption sets / house view (GOV-01…03) ----------------------------------------------------------------
def _validate_config(config):
    from ..core.config import ModelConfig
    try:
        return ModelConfig(**config).to_dict()
    except TypeError:
        raise ModelError('invalid_config', 'Assumption set has unknown or missing fields') from None

def _next_version(conn, org_id):
    current = conn.execute(select(assumption_sets.c.version).where(assumption_sets.c.org_id == org_id)
                           .order_by(assumption_sets.c.version.desc()).limit(1)).scalar()
    return (current or 0)+1

def save_sandbox(conn, principal, name, config, request=None):
    require(principal, 'assumptions.sandbox')
    cfg = _validate_config(config)
    set_id = uid()
    conn.execute(assumption_sets.insert().values(id=set_id, org_id=principal.org_id, version=_next_version(conn, principal.org_id),
                                                 name=str(name)[:200] or 'Sandbox', status='draft', config=cfg, owner_id=principal.user_id,
                                                 personal=True, proposed_by=principal.user_id))
    audit.record(conn, 'assumptions.sandbox_saved', actor=principal, target_type='assumption_set', target_id=set_id, request=request)
    return set_id

def propose(conn, principal, name, config, reason, request=None):
    require(principal, 'assumptions.propose')
    if not str(reason or '').strip(): raise ModelError('reason_required', 'Explain why the house assumptions should change')
    cfg = _validate_config(config)
    base = house_config(conn, principal.org_id)
    diff = {k: {'from': base.get(k), 'to': v} for k, v in cfg.items() if base.get(k) != v}
    set_id = uid()
    conn.execute(assumption_sets.insert().values(id=set_id, org_id=principal.org_id, version=_next_version(conn, principal.org_id),
                                                 name=str(name)[:200] or 'Proposal', status='proposed', config=cfg, reason=reason,
                                                 proposed_by=principal.user_id, proposed_at=now(), owner_id=principal.user_id))
    notify_role(conn, principal.org_id, 'head_uw', 'assumptions_proposed', f'Assumption change proposed: {name}', exclude=principal.user_id)
    audit.record(conn, 'assumptions.proposed', actor=principal, target_type='assumption_set', target_id=set_id,
                 details={'reason': reason, 'diff': json.loads(json.dumps(diff, default=str))}, request=request)
    return set_id

def decide(conn, principal, set_id, approve, note='', make_default=False, request=None):
    require(principal, 'assumptions.approve')
    row = conn.execute(select(assumption_sets).where(assumption_sets.c.id == set_id, assumption_sets.c.org_id == principal.org_id)).mappings().first()
    if not row or row['status'] != 'proposed': raise ModelError('not_found', 'No pending proposal with that id')
    if row['proposed_by'] == principal.user_id and settings_for(conn, principal.org_id)['enforce_separation_of_duties']:
        audit.record(conn, 'assumptions.decision_denied', actor=principal, target_type='assumption_set', target_id=set_id, outcome='denied',
                     details={'reason': 'separation_of_duties'}, request=request)
        raise ModelError('separation_of_duties', 'Someone other than the proposer must approve this change')
    conn.execute(assumption_sets.update().where(assumption_sets.c.id == set_id).values(
        status='approved' if approve else 'rejected', decided_by=principal.user_id, decided_at=now(), decision_note=note))
    notify(conn, principal.org_id, row['proposed_by'], 'assumptions_decided', f"Your proposal '{row['name']}' was {'approved' if approve else 'rejected'}")
    audit.record(conn, 'assumptions.approved' if approve else 'assumptions.rejected', actor=principal, target_type='assumption_set',
                 target_id=set_id, details={'note': note}, request=request)
    if approve and make_default: set_default(conn, principal, set_id, request)

def set_default(conn, principal, set_id, request=None):
    require(principal, 'assumptions.approve')
    row = conn.execute(select(assumption_sets).where(assumption_sets.c.id == set_id, assumption_sets.c.org_id == principal.org_id)).mappings().first()
    if not row or row['status'] != 'approved': raise ModelError('not_approved', 'Only an approved assumption set can become the house view')
    conn.execute(assumption_sets.update().where(assumption_sets.c.org_id == principal.org_id).values(is_default=False))
    conn.execute(assumption_sets.update().where(assumption_sets.c.id == set_id).values(is_default=True))
    settings = settings_for(conn, principal.org_id)
    conn.execute(organisations.update().where(organisations.c.id == principal.org_id).values(settings={**settings, 'default_assumption_set_id': set_id}))
    audit.record(conn, 'assumptions.house_view_changed', actor=principal, target_type='assumption_set', target_id=set_id,
                 details={'version': row['version']}, request=request)

def list_sets(conn, principal):
    q = select(assumption_sets).where(assumption_sets.c.org_id == principal.org_id).order_by(assumption_sets.c.version.desc())
    return [dict(r) for r in conn.execute(q).mappings() if not r['personal'] or r['owner_id'] == principal.user_id]

def house_config(conn, org_id):
    """The organisation's approved default assumptions, else the shipped configs/default.json."""
    row = conn.execute(select(assumption_sets.c.config).where(assumption_sets.c.org_id == org_id, assumption_sets.c.is_default.is_(True))).scalar()
    if row: return dict(row)
    from ..core.config import load_config
    return load_config().to_dict()

def house_set(conn, org_id):
    return conn.execute(select(assumption_sets.c.id, assumption_sets.c.version, assumption_sets.c.name)
                        .where(assumption_sets.c.org_id == org_id, assumption_sets.c.is_default.is_(True))).mappings().first()

# Submissions workflow (WF-01…05, RBAC-07) ------------------------------------------------------------------
STATUSES = ('received', 'under_review', 'referred', 'quoted', 'bound', 'declined')
TRANSITIONS = {'received': {'under_review', 'declined'}, 'under_review': {'referred', 'quoted', 'declined'},
               'referred': {'quoted', 'declined', 'under_review'}, 'quoted': {'bound', 'declined', 'under_review'}, 'bound': set(), 'declined': {'under_review'}}

def create_submission(conn, principal, name, cedant='', broker='', inception='', team_id=None, request=None):
    require(principal, 'submissions.manage')
    if not str(name or '').strip(): raise ModelError('invalid', 'Submission name required')
    sub_id = uid()
    conn.execute(submissions.insert().values(id=sub_id, org_id=principal.org_id, name=str(name)[:200], cedant=str(cedant)[:200],
                                             broker=str(broker)[:200], inception=str(inception)[:20], status='received', assignee_id=principal.user_id,
                                             team_id=team_id or (principal.team_ids[0] if principal.team_ids else None), created_by=principal.user_id,
                                             created_at=now(), updated_at=now()))
    audit.record(conn, 'submission.created', actor=principal, target_type='submission', target_id=sub_id, details={'name': name}, request=request)
    return sub_id

def _submission(conn, principal, sub_id):
    row = conn.execute(select(submissions).where(submissions.c.id == sub_id, submissions.c.org_id == principal.org_id)).mappings().first()
    if not row: raise ModelError('not_found', 'Submission not found')
    return row

def _attach_run(conn, sub_id, report):
    base = report['runs']['baseline']
    rarest = max(p['return_period_years'] for p in base['ep_curve'])
    loss = next(p['loss_kes'] for p in base['ep_curve'] if p['return_period_years'] == rarest)
    conn.execute(submissions.update().where(submissions.c.id == sub_id).values(tiv_kes=report['modelled_tiv_kes'], loss_250_kes=loss, updated_at=now()))

def list_submissions(conn, principal, assigned_only=False):
    require(principal, 'runs.read')
    q = select(submissions).where(submissions.c.org_id == principal.org_id)
    if assigned_only: q = q.where(submissions.c.assignee_id == principal.user_id)
    return [dict(r) for r in conn.execute(q.order_by(submissions.c.updated_at.desc())).mappings()]

def get_submission(conn, principal, sub_id):
    require(principal, 'runs.read')
    return dict(_submission(conn, principal, sub_id))

def exceeds_authority(conn, principal, sub):
    s = settings_for(conn, principal.org_id)
    reasons = []
    if s['authority_limit_tiv_kes'] and sub['tiv_kes'] and Decimal(sub['tiv_kes']) > Decimal(str(s['authority_limit_tiv_kes'])):
        reasons.append(f"insured value above the authority limit of KES {float(s['authority_limit_tiv_kes']):,.0f}")
    if s['authority_limit_loss_kes'] and sub['loss_250_kes'] and Decimal(sub['loss_250_kes']) > Decimal(str(s['authority_limit_loss_kes'])):
        reasons.append(f"modelled rarest-scenario loss above the limit of KES {float(s['authority_limit_loss_kes']):,.0f}")
    return reasons

def move_submission(conn, principal, sub_id, status, note='', request=None):
    require(principal, 'submissions.manage')
    sub = _submission(conn, principal, sub_id)
    if status not in STATUSES or status not in TRANSITIONS[sub['status']]:
        raise ModelError('invalid_transition', f"A submission cannot move from {sub['status']} to {status}")
    reasons = exceeds_authority(conn, principal, sub)
    if status in ('quoted', 'bound') and reasons and not principal.can('referrals.approve'):
        raise ModelError('referral_required', 'Refer this to the head of underwriting first: ' + '; '.join(reasons))
    if status == 'quoted' and sub['status'] == 'referred' and not principal.can('referrals.approve'):
        raise ModelError('referral_required', 'Only the head of underwriting can clear a referral')
    if status == 'referred' and not str(note).strip(): raise ModelError('reason_required', 'Say why this is being referred')
    conn.execute(submissions.update().where(submissions.c.id == sub_id).values(status=status, updated_at=now(),
                                                                               referral_reason=note if status == 'referred' else sub['referral_reason']))
    if status == 'referred': notify_role(conn, principal.org_id, 'head_uw', 'referral', f"Referral: {sub['name']} — {note}", exclude=principal.user_id)
    elif sub['assignee_id'] and sub['assignee_id'] != principal.user_id:
        notify(conn, principal.org_id, sub['assignee_id'], 'submission_status', f"{sub['name']} moved to {status.replace('_', ' ')}")
    audit.record(conn, 'submission.status_changed', actor=principal, target_type='submission', target_id=sub_id,
                 details={'from': sub['status'], 'to': status, 'note': note}, request=request)

def assign_submission(conn, principal, sub_id, user_id, request=None):
    require(principal, 'submissions.manage')
    sub = _submission(conn, principal, sub_id)
    if not conn.execute(select(memberships.c.id).where(memberships.c.org_id == principal.org_id, memberships.c.user_id == user_id,
                                                       memberships.c.status == 'active')).scalar():
        raise ModelError('not_found', 'User not found')
    conn.execute(submissions.update().where(submissions.c.id == sub_id).values(assignee_id=user_id, updated_at=now()))
    notify(conn, principal.org_id, user_id, 'assigned', f"You were assigned: {sub['name']}")
    audit.record(conn, 'submission.assigned', actor=principal, target_type='submission', target_id=sub_id, details={'to': user_id}, request=request)

# Comments (WF-04) ---------------------------------------------------------------------------------------
def add_comment(conn, principal, target_type, target_id, body, request=None):
    require(principal, 'comments.write')
    body = str(body or '').strip()
    if not body: raise ModelError('invalid', 'Write a comment')
    if target_type == 'submission': _submission(conn, principal, target_id)
    elif target_type == 'run': _run_row(conn, principal, target_id)
    else: raise ModelError('invalid', 'Unknown comment target')
    comment_id = uid()
    conn.execute(comments.insert().values(id=comment_id, org_id=principal.org_id, target_type=target_type, target_id=str(target_id),
                                          author_id=principal.user_id, body=body[:5000], created_at=now()))
    audit.record(conn, 'comment.added', actor=principal, target_type=target_type, target_id=target_id, request=request)
    return comment_id

def list_comments(conn, principal, target_type, target_id):
    q = select(comments).where(comments.c.org_id == principal.org_id, comments.c.target_type == target_type, comments.c.target_id == str(target_id))
    return [dict(r) for r in conn.execute(q.order_by(comments.c.created_at)).mappings()]

# Retention (DATA-04, DATA-06) -----------------------------------------------------------------------------
def run_retention(conn):
    """Delete expired business data per organisation settings; purge closed organisations after their export window."""
    deleted = {}
    for org in conn.execute(select(organisations)).mappings():
        s = settings_for(conn, org['id'])
        cutoff = now()-timedelta(days=int(s['retention_runs_days']))
        n = conn.execute(runs.delete().where(runs.c.org_id == org['id'], runs.c.created_at < cutoff)).rowcount
        n += conn.execute(extractions.delete().where(extractions.c.org_id == org['id'], extractions.c.created_at < cutoff)).rowcount
        if org['status'] == 'closed' and org['export_until'] and _aware(org['export_until']) < now():
            for table in (runs, extractions, evidence, comments, submissions, notifications, assumption_sets):
                n += conn.execute(table.delete().where(table.c.org_id == org['id'])).rowcount
            conn.execute(memberships.update().where(memberships.c.org_id == org['id']).values(status='deactivated', deactivated_at=now()))
        if n:
            deleted[org['id']] = n
            audit.record(conn, 'retention.deleted', org_id=org['id'], target_type='organisation', target_id=org['id'], details={'records': n})
    return deleted
