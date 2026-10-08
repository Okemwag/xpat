"""Single sign-on with OpenID Connect, configured per organisation (AUTH-01…05).

Authorization-code flow with PKCE, state and nonce. The ID token is verified against the provider's published keys
(signature, issuer, audience, expiry, nonce). Users are matched by verified e-mail within the organisation's allowed
domains and provisioned just in time with the organisation's default role, or with roles mapped from IdP groups.
"""
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode
from sqlalchemy import select
from ..core.errors import ModelError
from . import audit, security
from .db import memberships, now, organisations, sso_configs, uid, users
from .identity import _email, auth_url, require_recent_auth, settings_for, start_session
from .rbac import ROLES, require

STATE_TTL = 600
HTTP = None  # an httpx client to use instead of the module (tests inject a mock transport)
SAFE_DEFAULT_ROLES = ('viewer', 'underwriter', 'analyst', 'reviewer', 'auditor')

def configure(conn, principal, discovery_url, client_id, client_secret, default_role='viewer', role_mapping=None, enabled=True,
              enforced=False, request=None):
    require(principal, 'security.manage'); require_recent_auth(conn, principal)
    if not str(discovery_url).startswith('https://'): raise ModelError('invalid_sso', 'The discovery URL must use https')
    if default_role not in SAFE_DEFAULT_ROLES: raise ModelError('invalid_sso', 'The default role cannot be an administrator role')
    mapping = {str(k): v for k, v in (role_mapping or {}).items()}
    if any(r not in ROLES for roles in mapping.values() for r in roles): raise ModelError('invalid_sso', 'Role mapping contains an unknown role')
    if enabled and not settings_for(conn, principal.org_id)['allowed_domains']:
        raise ModelError('invalid_sso', 'Set the allowed e-mail domains first, so only your staff can sign in')
    existing = conn.execute(select(sso_configs).where(sso_configs.c.org_id == principal.org_id)).mappings().first()
    secret_enc = security.encrypt(client_secret) if client_secret else (existing['client_secret_enc'] if existing else None)
    if not secret_enc: raise ModelError('invalid_sso', 'Client secret required')
    values = dict(discovery_url=discovery_url, client_id=client_id, client_secret_enc=secret_enc, default_role=default_role,
                  role_mapping=mapping, enabled=bool(enabled), enforced=bool(enforced), updated_at=now())
    if existing: conn.execute(sso_configs.update().where(sso_configs.c.org_id == principal.org_id).values(**values))
    else: conn.execute(sso_configs.insert().values(org_id=principal.org_id, **values))
    audit.record(conn, 'sso.configured', actor=principal, target_type='organisation', target_id=principal.org_id,
                 details={'discovery_url': discovery_url, 'client_id': client_id, 'default_role': default_role, 'enabled': enabled,
                          'enforced': enforced, 'mapping_groups': sorted(mapping)}, request=request)

def get_config(conn, org_id):
    row = conn.execute(select(sso_configs).where(sso_configs.c.org_id == org_id)).mappings().first()
    return {k: v for k, v in row.items() if k != 'client_secret_enc'} if row else None

def org_for_email(conn, email_addr):
    """The organisation whose SSO covers this e-mail domain, if any."""
    domain = _email(email_addr).split('@')[1]
    for org_id, settings in conn.execute(select(organisations.c.id, organisations.c.settings).join(sso_configs, sso_configs.c.org_id == organisations.c.id)
                                         .where(sso_configs.c.enabled.is_(True), organisations.c.status.in_(('trial', 'active')))):
        if domain in [d.lower() for d in (settings or {}).get('allowed_domains', [])]: return org_id
    return None

def sso_enforced_for(conn, user_id):
    """True when every organisation of this user enforces SSO (password sign-in then only for owners, as break-glass)."""
    rows = conn.execute(select(memberships.c.org_id, memberships.c.roles, sso_configs.c.enforced)
                        .outerjoin(sso_configs, sso_configs.c.org_id == memberships.c.org_id)
                        .where(memberships.c.user_id == user_id, memberships.c.status == 'active')).all()
    return bool(rows) and all(r.enforced and 'owner' not in r.roles for r in rows)

def _discovery(config, http):
    response = http.get(config['discovery_url'], timeout=10)
    response.raise_for_status()
    meta = response.json()
    for key in ('issuer', 'authorization_endpoint', 'token_endpoint', 'jwks_uri'):
        if key not in meta: raise ModelError('invalid_sso', f'The identity provider metadata has no {key}')
    return meta

def start(conn, org_id, next_url='/', http=None):
    """Return (redirect URL to the IdP, encrypted state cookie value)."""
    import httpx
    row = conn.execute(select(sso_configs).where(sso_configs.c.org_id == org_id, sso_configs.c.enabled.is_(True))).mappings().first()
    if not row: raise ModelError('sso_not_configured', 'Single sign-on is not set up for this organisation')
    meta = _discovery(row, http or HTTP or httpx)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    params = {'response_type': 'code', 'client_id': row['client_id'], 'redirect_uri': f'{auth_url()}/auth/sso/callback',
              'scope': 'openid email profile', 'state': state, 'nonce': nonce, 'code_challenge': challenge, 'code_challenge_method': 'S256'}
    cookie = security.encrypt(json.dumps({'org_id': org_id, 'state': state, 'nonce': nonce, 'verifier': verifier, 'next': next_url,
                                          'exp': time.time()+STATE_TTL}))
    return f"{meta['authorization_endpoint']}?{urlencode(params)}", cookie

def callback(conn, code, state, cookie, http=None, request=None):
    """Exchange the code, verify the ID token and sign the user in. Returns (session token, next URL)."""
    import httpx
    from joserfc import jwt
    from joserfc.errors import JoseError
    from joserfc.jwk import KeySet
    http = http or HTTP or httpx
    try: saved = json.loads(security.decrypt(cookie or ''))
    except Exception: raise ModelError('sso_failed', 'Sign-in session expired; start again') from None
    if saved['exp'] < time.time() or not secrets.compare_digest(saved['state'], str(state or '')):
        raise ModelError('sso_failed', 'Sign-in state did not match; start again')
    row = conn.execute(select(sso_configs).where(sso_configs.c.org_id == saved['org_id'], sso_configs.c.enabled.is_(True))).mappings().first()
    if not row: raise ModelError('sso_not_configured', 'Single sign-on is not set up for this organisation')
    meta = _discovery(row, http)
    token_response = http.post(meta['token_endpoint'], timeout=10, data={
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': f'{auth_url()}/auth/sso/callback', 'client_id': row['client_id'],
        'client_secret': security.decrypt(row['client_secret_enc']), 'code_verifier': saved['verifier']})
    if token_response.status_code != 200: raise ModelError('sso_failed', 'The identity provider rejected the sign-in')
    id_token = token_response.json().get('id_token')
    if not id_token: raise ModelError('sso_failed', 'The identity provider returned no ID token')
    keys = http.get(meta['jwks_uri'], timeout=10).json()
    try:
        token = jwt.decode(id_token, KeySet.import_key_set(keys))
        jwt.JWTClaimsRegistry(iss={'essential': True, 'value': meta['issuer']}, aud={'essential': True, 'value': row['client_id']},
                              nonce={'essential': True, 'value': saved['nonce']}, exp={'essential': True}, sub={'essential': True}).validate(token.claims)
    except (JoseError, ValueError) as exc:
        audit.record(conn, 'sso.token_rejected', org_id=saved['org_id'], outcome='denied', details={'error': type(exc).__name__}, request=request)
        raise ModelError('sso_failed', 'The sign-in token could not be verified') from None
    claims = token.claims
    email_addr = claims.get('email') or claims.get('preferred_username') or ''
    if claims.get('email_verified') is False: raise ModelError('sso_failed', 'Your e-mail address is not verified with your identity provider')
    email_addr = _email(email_addr)
    domains = [d.lower() for d in settings_for(conn, saved['org_id'])['allowed_domains']]
    if email_addr.split('@')[1] not in domains:
        audit.record(conn, 'sso.domain_denied', org_id=saved['org_id'], outcome='denied', details={'email': email_addr}, request=request)
        raise ModelError('domain_not_allowed', 'Your e-mail domain is not allowed for this organisation')
    groups = claims.get('groups') or claims.get('roles') or []
    mapped = sorted({r for g in groups for r in row['role_mapping'].get(str(g), [])})
    user = conn.execute(select(users).where(users.c.email == email_addr)).mappings().first()
    if user and user['status'] != 'active': raise ModelError('account_inactive', 'Your account is not active')
    if not user:
        user_id = uid()
        conn.execute(users.insert().values(id=user_id, email=email_addr, display_name=str(claims.get('name') or email_addr)[:120],
                                           email_verified_at=now(), status='active', created_at=now(), sso_subject=claims['sub']))
    else:
        user_id = user['id']
        if user['sso_subject'] and user['sso_subject'] != claims['sub']:
            raise ModelError('sso_failed', 'This e-mail is linked to a different identity-provider account')
        conn.execute(users.update().where(users.c.id == user_id).values(sso_subject=claims['sub']))
    m = conn.execute(select(memberships).where(memberships.c.org_id == saved['org_id'], memberships.c.user_id == user_id)).mappings().first()
    if m and m['status'] != 'active': raise ModelError('account_inactive', 'Your access to this organisation has been removed')
    if not m:
        roles = mapped or [row['default_role']]
        conn.execute(memberships.insert().values(id=uid(), org_id=saved['org_id'], user_id=user_id, roles=roles, status='active', created_at=now()))
        audit.record(conn, 'sso.user_provisioned', org_id=saved['org_id'], target_type='user', target_id=user_id, details={'roles': roles}, request=request)
    elif mapped and sorted(m['roles']) != mapped and not ({'owner'} & set(m['roles'])):
        conn.execute(memberships.update().where(memberships.c.id == m['id']).values(roles=mapped))
        audit.record(conn, 'sso.roles_synced', org_id=saved['org_id'], target_type='user', target_id=user_id,
                     details={'before': m['roles'], 'after': mapped}, request=request)
    raw, _ = start_session(conn, user_id, saved['org_id'], method='sso', mfa_passed=True, request=request)
    return raw, saved.get('next') or '/'
