import streamlit as st
from floodcat.platform import orgs, sso
from floodcat.platform.identity import auth_url
from ui import state
from ui.components import kpis, page_header, section, when

p = state.principal()
page_header('Security & sign-in', 'How your people sign in and how long sessions last. Changes need your password and are audited.')
with state.platform().tx() as conn:
    org = orgs.get_org(conn, p.org_id); s = org['settings']; sso_cfg = sso.get_config(conn, p.org_id); grants = orgs.list_support_grants(conn, p.org_id)

kpis([('Two-step required for', {'off': 'Nobody', 'admins': 'Owners and admins', 'all': 'Everyone'}[s['mfa_policy']]),
      ('Idle sign-out', f"{s['session_idle_minutes']} min"), ('Longest session', f"{s['session_max_hours']} h"),
      ('Single sign-on', ('required' if sso_cfg.get('enforced') else 'on') if sso_cfg and sso_cfg.get('enabled') else 'off'),
      ('Support access', sum(g['active'] for g in grants), 'Active grants to Xpat support')])
with st.form('policy'):
    section('Sign-in policy')
    mfa = st.radio('Two-step verification required for', ['off', 'admins', 'all'], index=['off', 'admins', 'all'].index(s['mfa_policy']), horizontal=True,
                   format_func={'off': 'Nobody (not recommended)', 'admins': 'Owners and admins', 'all': 'Everyone'}.get)
    a, b = st.columns(2)
    idle = a.number_input('Sign out after inactivity (minutes)', 5, 480, int(s['session_idle_minutes']))
    life = b.number_input('Maximum session length (hours)', 1, 72, int(s['session_max_hours']))
    domains = st.text_input('Allowed e-mail domains (comma-separated)', ', '.join(s['allowed_domains']), help='Only these addresses can be invited or sign in with SSO.')
    sod = st.toggle('Separation of duties: approvals need a second person', value=bool(s['enforce_separation_of_duties']),
                    help='The person who adds evidence or proposes an assumption change cannot approve it.')
    if st.form_submit_button('Save policy', type='primary'):
        changes = {'mfa_policy': mfa, 'session_idle_minutes': int(idle), 'session_max_hours': int(life),
                   'allowed_domains': [d.strip() for d in domains.split(',') if d.strip()], 'enforce_separation_of_duties': sod}
        if state.guarded(orgs.update_settings, changes) is not state.FAILED: st.success('Policy saved.')

section('Single sign-on (OpenID Connect)')
st.caption(f'Register Xpat in your identity provider (Microsoft Entra ID, Google Workspace, Okta…) with redirect URI '
           f'`{auth_url()}/auth/sso/callback`, then enter its details here. Your provider then handles passwords, MFA and leavers.')
with st.form('sso'):
    url = st.text_input('Discovery URL', (sso_cfg or {}).get('discovery_url', ''), placeholder='https://login.microsoftonline.com/<tenant>/v2.0/.well-known/openid-configuration')
    client_id = st.text_input('Client ID', (sso_cfg or {}).get('client_id', ''))
    secret = st.text_input('Client secret', type='password', help='Stored encrypted. Leave blank to keep the current secret.')
    default_role = st.selectbox('Role for new SSO users', list(sso.SAFE_DEFAULT_ROLES), index=list(sso.SAFE_DEFAULT_ROLES).index((sso_cfg or {}).get('default_role', 'viewer')))
    mapping_text = st.text_area('Group → roles mapping (optional, one per line: group = role, role)',
                                '\n'.join(f"{g} = {', '.join(r)}" for g, r in ((sso_cfg or {}).get('role_mapping') or {}).items()))
    a, b = st.columns(2)
    enabled = a.toggle('Enabled', value=(sso_cfg or {}).get('enabled', True))
    enforced = b.toggle('Require SSO (password sign-in only for owners, as a break-glass)', value=(sso_cfg or {}).get('enforced', False))
    if st.form_submit_button('Save single sign-on'):
        mapping = {}
        for line in mapping_text.splitlines():
            group, _, roles = line.partition('=')
            if group.strip() and roles.strip(): mapping[group.strip()] = [r.strip() for r in roles.split(',') if r.strip()]
        if state.guarded(sso.configure, url, client_id, secret, default_role, mapping, enabled, enforced) is not state.FAILED: st.success('Single sign-on saved.')

section('Xpat support access')
st.caption('Let Xpat support see your organisation for a limited time, e.g. to investigate a ticket. They can read, not change. Fully audited.')
if p.can('support.grant'):
    with st.form('support'):
        staff = st.text_input('Support engineer\'s e-mail')
        hours = st.number_input('Hours', 1, 72, 4)
        reason = st.text_input('Reason / ticket number')
        if st.form_submit_button('Grant access'):
            if state.guarded(orgs.grant_support, staff, int(hours), reason) is not state.FAILED: st.rerun()
for g in grants:
    with st.container(border=True, horizontal=True, vertical_alignment='center'):
        st.markdown(f"{'**Active**' if g['active'] else 'Ended'} · {g['reason']} · until {when(g['expires_at'])}")
        if g['active'] and st.button('Revoke', key=f"sg_{g['id']}"):
            if state.guarded(orgs.revoke_support, g['id']) is not state.FAILED: st.rerun()
