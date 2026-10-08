"""Organisation platform: tenancy, identity flows, RBAC matrix, audit log. SQLite in-memory; e-mail goes to the outbox."""
import re
from datetime import timedelta
import pytest
from sqlalchemy import select, update
from floodcat.core.errors import ModelError
from floodcat.platform import audit, data, identity, orgs, security
from floodcat.platform.db import audit_events, one_time_tokens, sessions, users
from floodcat.platform.email import recent
from floodcat.platform.rbac import PERMISSIONS, Principal
from floodcat.platform.service import Platform

PW = 'a long and unusual passphrase 42'
REQ = {'ip': '10.0.0.1', 'user_agent': 'pytest'}

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv('FLOODCAT_BREACH_CHECK', '0')
    monkeypatch.delenv('RESEND_API_KEY', raising=False)

@pytest.fixture
def p(tmp_path, monkeypatch):
    """SQLite by default; a real PostgreSQL when TEST_DATABASE_URL is set (CI runs both)."""
    import os
    monkeypatch.setenv('FLOODCAT_STORE_DIR', str(tmp_path))
    url = os.getenv('TEST_DATABASE_URL')
    if not url: return Platform(f'sqlite:///{tmp_path}/platform.db')
    from floodcat.platform.db import create_schema, metadata
    plat = Platform(url, create=False)
    with plat.engine.begin() as c: c.exec_driver_sql('DROP TRIGGER IF EXISTS audit_no_change ON audit_events')
    metadata.drop_all(plat.engine); create_schema(plat.engine)
    return plat

def link(conn, to, kind):
    msg = next(m for m in recent(conn, to) if m['kind'] == kind)
    return re.search(r'/auth/[a-z-]+/(\S+)', msg['text']).group(1)

def make_org(p, name='Acme Re', owner='owner@acme.re'):
    with p.tx() as c:
        admin_id = identity.bootstrap_platform_admin(c, f'staff-{name[:4].lower()}@xpat.io', 'Staff', PW) if not c.execute(
            select(users.c.id).where(users.c.is_platform_admin.is_(True))).scalar() else c.execute(select(users.c.id).where(users.c.is_platform_admin.is_(True))).scalar()
        staff = identity.principal_for(c, admin_id, None)
        org_id, _ = identity.create_organisation(c, staff, name, owner)
        raw = link(c, owner, 'invitation')
        user_id, _ = identity.accept_invitation(c, raw, display_name='Olive Owner', password=PW)
        raw_s, sid = identity.start_session(c, user_id, org_id)
        principal, _ = identity.resolve_session(c, raw_s)
    return org_id, principal, raw_s

def member(p, owner, email, roles):
    with p.tx() as c:
        identity.invite(c, owner, email, roles)
        user_id, org_id = identity.accept_invitation(c, link(c, email, 'invitation'), display_name=email.split('@')[0], password=PW)
        raw, _ = identity.start_session(c, user_id, org_id)
        principal, _ = identity.resolve_session(c, raw)
    return principal, raw

# Invitations, sign-in, sessions --------------------------------------------------------------------
def test_invitation_flow_creates_member_with_roles(p):
    org_id, owner, _ = make_org(p)
    assert owner.roles == ('owner',) and owner.can('users.manage')
    uw, _ = member(p, owner, 'uw@acme.re', ['underwriter'])
    assert uw.roles == ('underwriter',) and uw.org_id == org_id and not uw.can('users.manage')

def test_invitation_link_single_use_and_expiring(p):
    org_id, owner, _ = make_org(p)
    with p.tx() as c:
        identity.invite(c, owner, 'x@acme.re', ['viewer']); raw = link(c, 'x@acme.re', 'invitation')
        identity.accept_invitation(c, raw, display_name='X', password=PW)
        with pytest.raises(ModelError): identity.accept_invitation(c, raw, display_name='X', password=PW)
        identity.invite(c, owner, 'y@acme.re', ['viewer']); raw2 = link(c, 'y@acme.re', 'invitation')
        c.execute(update(identity.invitations).values(expires_at=identity.now()-timedelta(minutes=1)))
        with pytest.raises(ModelError): identity.invitation_for(c, raw2)

def test_domain_allowlist_and_seats(p):
    org_id, owner, _ = make_org(p)
    with p.tx() as c:
        identity.reauthenticate(c, owner, password=PW)
        orgs.update_settings(c, owner, {'allowed_domains': ['acme.re']})
        with pytest.raises(ModelError) as e: identity.invite(c, owner, 'a@gmail.com', ['viewer'])
        assert e.value.code == 'domain_not_allowed'
        c.execute(update(identity.organisations).values(seats=1))
        with pytest.raises(ModelError) as e: identity.invite(c, owner, 'b@acme.re', ['viewer'])
        assert e.value.code == 'seat_limit'

def test_only_owner_invites_owner(p):
    org_id, owner, _ = make_org(p)
    admin, _ = member(p, owner, 'admin@acme.re', ['admin'])
    with p.tx() as c, pytest.raises(ModelError):
        identity.invite(c, admin, 'z@acme.re', ['owner'])

def test_login_generic_errors_and_lockout(p):
    make_org(p)
    with p.tx() as c:
        for _ in range(5):
            with pytest.raises(ModelError) as e: identity.authenticate(c, 'owner@acme.re', 'wrong password', REQ)
            assert e.value.code == 'bad_credentials'
        with pytest.raises(ModelError) as e: identity.authenticate(c, 'owner@acme.re', PW, REQ)
        assert e.value.code == 'locked'
        with pytest.raises(ModelError) as e: identity.authenticate(c, 'nobody@acme.re', PW, REQ)
        assert e.value.code == 'bad_credentials'      # same message for unknown accounts

def test_session_idle_timeout_and_revocation(p):
    org_id, owner, raw = make_org(p)
    with p.tx() as c:
        c.execute(update(sessions).values(last_seen_at=identity.now()-timedelta(minutes=31)))
        assert identity.resolve_session(c, raw) == (None, 'expired')
        raw2, _ = identity.start_session(c, owner.user_id, org_id)
        identity.logout(c, raw2)
        assert identity.resolve_session(c, raw2)[0] is None

def test_admin_mfa_policy_flags_setup(p):
    org_id, owner, raw = make_org(p)
    with p.tx() as c:
        principal, _ = identity.resolve_session(c, raw)
        assert principal.extra['mfa_setup_required']          # policy 'admins' and owner has no MFA yet
        secret, _ = identity.begin_mfa(c, principal)
        codes = identity.confirm_mfa(c, principal, security.totp(secret))
        assert len(codes) == 10
        principal, _ = identity.resolve_session(c, raw)
        assert not principal.extra['mfa_setup_required']
        assert identity.verify_second_factor(c, owner.user_id, codes[0]) and not identity.verify_second_factor(c, owner.user_id, codes[0])

# Password flows ------------------------------------------------------------------------------------
def test_forgot_password_reset_revokes_sessions(p):
    org_id, owner, raw = make_org(p)
    with p.tx() as c:
        identity.forgot_password(c, 'owner@acme.re', REQ)
        identity.forgot_password(c, 'nobody@acme.re', REQ)          # no error, no e-mail
        assert not [m for m in recent(c, 'nobody@acme.re')]
        token = link(c, 'owner@acme.re', 'password_reset')
        identity.reset_password(c, token, 'another long passphrase 77', request=REQ)
        assert identity.resolve_session(c, raw)[0] is None          # sessions revoked
        with pytest.raises(ModelError): identity.reset_password(c, token, 'yet another long passphrase')   # single use
        assert identity.authenticate(c, 'owner@acme.re', 'another long passphrase 77', REQ)['id'] == owner.user_id

def test_reset_requires_mfa_when_enabled_and_tokens_expire(p):
    org_id, owner, raw = make_org(p)
    with p.tx() as c:
        principal, _ = identity.resolve_session(c, raw)
        secret, _ = identity.begin_mfa(c, principal); identity.confirm_mfa(c, principal, security.totp(secret))
        identity.forgot_password(c, 'owner@acme.re', REQ); token = link(c, 'owner@acme.re', 'password_reset')
        with pytest.raises(ModelError) as e: identity.reset_password(c, token, 'another long passphrase 77')
        assert e.value.code == 'mfa_required'
        c.execute(update(one_time_tokens).values(expires_at=identity.now()-timedelta(seconds=1)))
        with pytest.raises(ModelError): identity.reset_password(c, token, 'another long passphrase 77', code=security.totp(secret))

def test_reset_rate_limited(p):
    make_org(p)
    with p.tx() as c:
        for _ in range(5): identity.forgot_password(c, 'owner@acme.re', REQ)
        assert len([m for m in recent(c, 'owner@acme.re') if m['kind'] == 'password_reset']) == 3

def test_change_password_keeps_current_session_only(p):
    org_id, owner, raw = make_org(p)
    with p.tx() as c:
        other, _ = identity.start_session(c, owner.user_id, org_id)
        with pytest.raises(ModelError): identity.change_password(c, owner, 'wrong', 'another long passphrase 77')
        identity.change_password(c, owner, PW, 'another long passphrase 77')
        assert identity.resolve_session(c, raw)[0] is not None and identity.resolve_session(c, other)[0] is None

@pytest.mark.parametrize('pw', ['short', 'password1234', 'aaaaaaaaaaaaaa', 'owner-owner-owner'])
def test_password_policy(pw):
    with pytest.raises(ModelError): security.check_password(pw, 'owner@acme.re')

def test_legacy_pbkdf2_hash_is_upgraded(p):
    org_id, owner, _ = make_org(p)
    import hashlib
    legacy = 'pbkdf2$' + '00'*16 + '$' + hashlib.pbkdf2_hmac('sha256', PW.encode(), bytes(16), 310_000).hex()
    with p.tx() as c:
        c.execute(update(users).where(users.c.id == owner.user_id).values(password_hash=legacy))
        identity.authenticate(c, 'owner@acme.re', PW, REQ)
        assert c.execute(select(users.c.password_hash).where(users.c.id == owner.user_id)).scalar().startswith('$argon2id$')

def test_email_change_needs_reauth_and_verification(p):
    org_id, owner, raw = make_org(p)
    with p.tx() as c:
        c.execute(update(sessions).values(reauth_at=identity.now()-timedelta(hours=1)))
        with pytest.raises(ModelError) as e: identity.request_email_change(c, owner, 'new@acme.re')
        assert e.value.code == 'reauth_required'
        identity.reauthenticate(c, owner, password=PW)
        identity.request_email_change(c, owner, 'new@acme.re')
        assert any(m['kind'] == 'email_change_notice' for m in recent(c, 'owner@acme.re'))
        identity.confirm_email_change(c, link(c, 'new@acme.re', 'email_change'))
        assert c.execute(select(users.c.email).where(users.c.id == owner.user_id)).scalar() == 'new@acme.re'

# Roles, leavers, tokens ---------------------------------------------------------------------------
def test_role_change_revokes_sessions_and_protects_last_owner(p):
    org_id, owner, raw = make_org(p)
    uw, uw_raw = member(p, owner, 'uw@acme.re', ['underwriter'])
    with p.tx() as c:
        identity.set_roles(c, owner, uw.user_id, ['analyst'], reason='moved team')
        assert identity.resolve_session(c, uw_raw)[0] is None
        with pytest.raises(ModelError): identity.set_roles(c, owner, owner.user_id, ['viewer'])

def test_leaver_loses_access_and_hands_over_runs(p, starter_rows):
    org_id, owner, _ = make_org(p)
    uw, uw_raw = member(p, owner, 'uw@acme.re', ['underwriter'])
    head, _ = member(p, owner, 'head@acme.re', ['head_uw'])
    from floodcat.services.analysis import analyse
    report = analyse(starter_rows[:5])
    with p.tx() as c:
        token = identity.create_api_token(c, uw, 'script', ['runs.read'])
        data.save_run(c, uw, report, starter_rows[:5], 'test')
        identity.deactivate(c, owner, uw.user_id, reassign_to=head.user_id)
        assert identity.resolve_session(c, uw_raw)[0] is None and identity.resolve_api_token(c, token) is None
        assert data.list_runs(c, head, mine_only=True)[0]['id'] == report['analysis_id']

def test_api_token_scopes_limit_permissions(p):
    org_id, owner, _ = make_org(p)
    uw, _ = member(p, owner, 'uw@acme.re', ['underwriter'])
    with p.tx() as c:
        raw = identity.create_api_token(c, uw, 'read only', ['runs.read'])
        principal = identity.resolve_api_token(c, raw)
        assert identity.token_allows(principal, 'runs.read') and not identity.token_allows(principal, 'runs.create')
        with pytest.raises(ModelError): identity.create_api_token(c, uw, 'too much', ['evidence.add', 'runs.create', 'ai.extract', 'users.manage'][3:] or ['x'])

# Tenant isolation (ORG-05) --------------------------------------------------------------------------------
def test_tenant_isolation(p, starter_rows):
    org_a, owner_a, _ = make_org(p, 'Acme Re', 'owner@acme.re')
    org_b, owner_b, _ = make_org(p, 'Beta Re', 'owner@beta.re')
    uw_a, _ = member(p, owner_a, 'uw@acme.re', ['underwriter'])
    uw_b, _ = member(p, owner_b, 'uw@beta.re', ['underwriter'])
    from floodcat.services.analysis import analyse
    report = analyse(starter_rows[:3])
    with p.tx() as c:
        data.save_run(c, uw_a, report, starter_rows[:3], 'secret', visibility='org')
        assert data.list_runs(c, uw_b) == []
        with pytest.raises(ModelError): data.get_run(c, uw_b, report['analysis_id'])
        with pytest.raises(ModelError): data.delete_run(c, uw_b, report['analysis_id'])
        with pytest.raises(ModelError): identity.deactivate(c, owner_b, uw_a.user_id)
        assert all(m['email'].endswith('beta.re') for m in identity.list_members(c, owner_b))
        assert audit.query(c, org_b, action='run.') == [e for e in audit.query(c, org_b, action='run.') if e['org_id'] == org_b]

def test_run_visibility(p, starter_rows):
    org_id, owner, _ = make_org(p)
    with p.tx() as c: team = orgs.create_team(c, owner, 'Facultative')
    a, _ = member(p, owner, 'a@acme.re', ['underwriter'])
    b, _ = member(p, owner, 'b@acme.re', ['underwriter'])
    with p.tx() as c:
        orgs.set_team_members(c, owner, team, [a.user_id])
        a = identity.principal_for(c, a.user_id, org_id)
        from floodcat.services.analysis import analyse
        for vis in ('private', 'team', 'org'):
            report = analyse(starter_rows[:2])
            data.save_run(c, a, report, starter_rows[:2], vis, visibility=vis, team_id=team if vis == 'team' else None)
        assert sorted(r['label'] for r in data.list_runs(c, a)) == ['org', 'private', 'team']
        assert sorted(r['label'] for r in data.list_runs(c, b)) == ['org']

# Separation of duties, governance, workflow ---------------------------------------------------------------
def test_evidence_maker_checker(p):
    org_id, owner, _ = make_org(p)
    rev1, _ = member(p, owner, 'r1@acme.re', ['reviewer'])
    rev2, _ = member(p, owner, 'r2@acme.re', ['reviewer'])
    from floodcat.ai.evidence import Evidence
    item = Evidence('ev-1', 's', 'q', '', 'Kibera', -1.31, 36.79, 'manual', 'drainage', 0.9, True)
    with p.tx() as c:
        data.add_evidence(c, rev1, item)
        with pytest.raises(ModelError) as e: data.approve_evidence(c, rev1, 'ev-1')
        assert e.value.code == 'separation_of_duties'
        assert data.approve_evidence(c, rev2, 'ev-1').approved
        assert data.list_evidence(c, org_id)[0][0].reviewer == 'r2'

def test_assumption_proposal_needs_another_approver(p):
    org_id, owner, _ = make_org(p)
    analyst, _ = member(p, owner, 'an@acme.re', ['analyst'])
    head, _ = member(p, owner, 'head@acme.re', ['head_uw'])
    with p.tx() as c:
        cfg = data.house_config(c, org_id); cfg['max_depth_m'] = 2.0
        with pytest.raises(ModelError): data.propose(c, analyst, 'Deeper', cfg, '')
        set_id = data.propose(c, analyst, 'Deeper', cfg, 'Survey evidence from 2026 floods')
        with pytest.raises(ModelError): data.decide(c, analyst, set_id, True)
        data.decide(c, head, set_id, True, 'ok', make_default=True)
        assert data.house_config(c, org_id)['max_depth_m'] == 2.0
        cfg['max_depth_m'] = 'deep'
        with pytest.raises(ModelError): data.propose(c, analyst, 'Bad', cfg, 'x')

def test_submission_referral_above_authority(p, starter_rows):
    org_id, owner, _ = make_org(p)
    uw, _ = member(p, owner, 'uw@acme.re', ['underwriter'])
    head, _ = member(p, owner, 'head@acme.re', ['head_uw'])
    from floodcat.services.analysis import analyse
    with p.tx() as c:
        identity.reauthenticate(c, owner, password=PW)
        orgs.update_settings(c, owner, {'authority_limit_tiv_kes': 1_000_000})
        sub = data.create_submission(c, uw, 'Landmark Plaza', 'Landmark Realty', 'Eastside')
        report = analyse(starter_rows[:5])
        data.save_run(c, uw, report, starter_rows[:5], 'run', submission_id=sub)
        data.move_submission(c, uw, sub, 'under_review')
        with pytest.raises(ModelError) as e: data.move_submission(c, uw, sub, 'quoted')
        assert e.value.code == 'referral_required'
        data.move_submission(c, uw, sub, 'referred', 'TIV above my limit')
        assert any(n['kind'] == 'referral' for n in data.list_notifications(c, head))
        data.move_submission(c, head, sub, 'quoted')
        with pytest.raises(ModelError): data.move_submission(c, uw, sub, 'received')

def test_support_access_is_time_limited(p, starter_rows):
    org_id, owner, raw = make_org(p)
    with p.tx() as c:
        staff_id = c.execute(select(users.c.id).where(users.c.is_platform_admin.is_(True))).scalar()
        staff_raw, _ = identity.start_session(c, staff_id, org_id)
        assert identity.resolve_session(c, staff_raw)[0] is None
        identity.reauthenticate(c, owner, password=PW)
        grant = orgs.grant_support(c, owner, c.execute(select(users.c.email).where(users.c.id == staff_id)).scalar(), 2, 'Ticket 42')
        staff_raw, _ = identity.start_session(c, staff_id, org_id)
        staff, _ = identity.resolve_session(c, staff_raw)
        assert staff.support_access and staff.can('runs.read') and not staff.can('runs.create')
        orgs.revoke_support(c, owner, grant)
        assert identity.resolve_session(c, staff_raw)[0] is None

# Permission matrix (RBAC-08) ------------------------------------------------------------------------------
MATRIX = {
    'users.manage': {'owner', 'admin'}, 'security.manage': {'owner', 'admin'}, 'audit.read': {'owner', 'admin', 'auditor'},
    'runs.create': {'head_uw', 'underwriter', 'analyst'}, 'ai.extract': {'head_uw', 'underwriter', 'analyst'},
    'runs.read': {'owner', 'head_uw', 'underwriter', 'analyst', 'reviewer', 'viewer', 'auditor'},
    'runs.export': {'head_uw', 'underwriter', 'analyst', 'viewer'}, 'assumptions.sandbox': {'head_uw', 'analyst'},
    'assumptions.approve': {'head_uw'}, 'evidence.add': {'head_uw', 'underwriter', 'analyst', 'reviewer'},
    'evidence.approve': {'head_uw', 'reviewer'}, 'org.billing': {'owner'}, 'org.close': {'owner'},
}

@pytest.mark.parametrize('permission', sorted(MATRIX))
@pytest.mark.parametrize('role', sorted(PERMISSIONS))
def test_permission_matrix(role, permission):
    principal = Principal('u', 'e', 'n', 'o', roles=(role,))
    assert principal.can(permission) == (role in MATRIX[permission])

# Audit log (AUD) ------------------------------------------------------------------------------------------
def test_audit_append_only_hash_chain_and_no_secrets(p):
    org_id, owner, raw = make_org(p)
    with p.tx() as c:
        identity.forgot_password(c, 'owner@acme.re', REQ)
        ok, bad = audit.verify_chain(c)
        assert ok and bad is None
        actions = {e['action'] for e in audit.query(c, None)}
        assert {'org.created', 'user.invited', 'user.invitation_accepted', 'auth.login', 'auth.reset_requested'} <= actions
        dump = str(audit.query(c, None))
        assert PW not in dump and 'token' not in dump.lower().replace('api_token', '')
    with pytest.raises(Exception), p.tx() as c:
        c.execute(update(audit_events).values(action='tampered'))
    with pytest.raises(Exception), p.tx() as c:
        c.execute(audit_events.delete())

def test_tampering_detected(tmp_path):  # SQLite only: needs to drop the trigger to simulate tampering
    from sqlalchemy import text
    plat = Platform(f'sqlite:///{tmp_path}/t.db')
    with plat.tx() as c:
        for i in range(3): audit.record(c, f'test.{i}')
        c.exec_driver_sql('DROP TRIGGER audit_no_update')
        c.execute(text("UPDATE audit_events SET action='test.x' WHERE seq=2"))
        assert audit.verify_chain(c) == (False, 2)

# Scanning, quotas, alerts --------------------------------------------------------------------------------
def test_clamav_scan_protocol(monkeypatch):
    import socket, threading, struct
    from floodcat.platform.scanning import scan
    server = socket.socket(); server.bind(('127.0.0.1', 0)); server.listen(2)
    replies = iter([b'stream: OK\0', b'stream: Eicar-Test-Signature FOUND\0'])
    def serve():
        for _ in range(2):
            conn, _ = server.accept()
            assert conn.recv(10) == b'zINSTREAM\0'
            while True:
                size = struct.unpack('>I', conn.recv(4))[0]
                if size == 0: break
                remaining = size
                while remaining: remaining -= len(conn.recv(remaining))
            conn.sendall(next(replies)); conn.close()
    threading.Thread(target=serve, daemon=True).start()
    monkeypatch.setenv('FLOODCAT_CLAMAV', f'127.0.0.1:{server.getsockname()[1]}')
    assert scan(b'x'*100_000) == 'clean'
    with pytest.raises(ModelError) as e: scan(b'X5O!P%@AP')
    assert e.value.code == 'malware_detected'

def test_scanner_required_in_production(monkeypatch):
    from floodcat.platform.scanning import scan
    monkeypatch.delenv('FLOODCAT_CLAMAV', raising=False)
    assert scan(b'data') == 'skipped'
    monkeypatch.setenv('FLOODCAT_ENV', 'production')
    with pytest.raises(ModelError): scan(b'data')

def test_ai_quota(p, monkeypatch):
    org_id, owner, _ = make_org(p)
    uw, _ = member(p, owner, 'uw@acme.re', ['underwriter'])
    monkeypatch.setenv('FLOODCAT_QUOTA_AI_USER_PER_HOUR', '2')
    with p.tx() as c:
        orgs.check_ai_quota(c, uw); orgs.check_ai_quota(c, uw)
        with pytest.raises(ModelError) as e: orgs.check_ai_quota(c, uw)
        assert e.value.code == 'rate_limited'

def test_alerts_on_failed_signins_and_escalation(p):
    from floodcat.platform import alerts
    org_id, owner, _ = make_org(p)
    uw, _ = member(p, owner, 'uw@acme.re', ['underwriter'])
    with p.tx() as c:
        for i in range(10):
            try: identity.authenticate(c, 'uw@acme.re', 'wrong', {'ip': f'1.1.1.{i}'})
            except ModelError: pass
            c.execute(identity.login_attempts.delete())          # avoid the lockout so attempts keep counting
        identity.set_roles(c, owner, uw.user_id, ['admin'], reason='test')
        raised = alerts.evaluate(c)
        assert {k for _, k in raised} >= {'failed_signins', 'escalation'}
        assert alerts.evaluate(c) == []                           # not repeated within the window
        assert any(n['kind'] == 'security_alert' for n in data.list_notifications(c, owner))
