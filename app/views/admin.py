import pandas as pd
import streamlit as st
from floodcat.platform import identity, orgs
from floodcat.platform.rbac import ASSIGNABLE, ROLES
from ui import state
from ui.components import page_header, when

p = state.principal()
page_header('Users & invitations', 'Invite people, set their roles, and remove access when they leave. Every change is audited.')
with state.platform().tx() as conn:
    members = identity.list_members(conn, p)
    invites = identity.list_invitations(conn, p)
    teams = orgs.list_teams(conn, p.org_id)
    org = orgs.get_org(conn, p.org_id)
active = [m for m in members if m['status'] == 'active']
a, b, c = st.columns(3)
a.metric('Active users', len(active)); b.metric('Pending invitations', len([i for i in invites if not i['expired']])); c.metric('Seats', org['seats'])
role_label = lambda r: f"{r.replace('_', ' ').title()} — {ROLES[r]}"
grantable = [r for r in ASSIGNABLE if r != 'owner' or 'owner' in p.roles]

with st.expander('Invite someone', icon=':material/person_add:', expanded=not invites and len(members) < 2):
    with st.form('invite', clear_on_submit=True):
        email = st.text_input('Work e-mail')
        roles = st.multiselect('Roles', grantable, default=['underwriter'], format_func=role_label)
        team_ids = st.multiselect('Teams', [t['id'] for t in teams], format_func={t['id']: t['name'] for t in teams}.get)
        domains = org['settings']['allowed_domains']
        if domains: st.caption(f"Only addresses at {', '.join(domains)} can be invited.")
        if st.form_submit_button('Send invitation', type='primary'):
            if state.guarded(identity.invite, email, roles, team_ids) is not state.FAILED: st.success(f'Invitation sent to {email}.')

if invites:
    st.subheader('Pending invitations')
    for inv in invites:
        with st.container(border=True, horizontal=True, vertical_alignment='center'):
            st.markdown(f"**{inv['email']}** · {', '.join(inv['roles'])} · {'expired' if inv['expired'] else 'expires ' + when(inv['expires_at'])}")
            if st.button('Resend', key=f"resend_{inv['id']}"):
                if state.guarded(identity.invite, inv['email'], inv['roles'], inv['team_ids']) is not state.FAILED: st.rerun()
            if st.button('Revoke', key=f"revoke_{inv['id']}"):
                if state.guarded(identity.revoke_invitation, inv['id']) is not state.FAILED: st.rerun()

st.subheader('Members')
st.dataframe(pd.DataFrame([{'Name': m['display_name'], 'E-mail': m['email'], 'Roles': ', '.join(m['roles']), 'Status': m['status'],
                            'Two-step': 'on' if m['mfa_enabled_at'] else 'off', 'Last sign-in': when(m['last_login_at'])} for m in members]),
             hide_index=True, width='stretch')
others = [m for m in members if m['id'] != p.user_id]
if others:
    st.subheader('Change a member')
    choice = st.selectbox('Member', [m['id'] for m in others], format_func={m['id']: f"{m['display_name']} ({m['email']}) — {m['status']}" for m in others}.get)
    m = next(x for x in others if x['id'] == choice)
    roles_tab, leave_tab, mfa_tab = st.tabs(['Roles', 'Deactivate / reactivate', 'Reset two-step'])
    with roles_tab:
        with st.form('roles'):
            new_roles = st.multiselect('Roles', grantable, default=[r for r in m['roles'] if r in grantable], format_func=role_label)
            reason = st.text_input('Reason (recorded in the audit log)')
            if st.form_submit_button('Save roles'):
                if state.guarded(identity.set_roles, m['id'], new_roles, reason) is not state.FAILED:
                    st.success('Roles updated. Their sessions were signed out so the change applies at once.')
    with leave_tab:
        if m['status'] == 'active':
            st.write('Removes access immediately: sessions and API tokens are revoked. Their analyses and submissions can be handed to someone else.')
            heirs = [x for x in active if x['id'] != m['id']]
            heir = st.selectbox('Hand their work to', [None]+[x['id'] for x in heirs],
                                format_func=lambda i: 'Nobody (keep under their name)' if i is None else next(x['display_name'] for x in heirs if x['id'] == i))
            if st.button('Deactivate', type='primary'):
                if state.guarded(identity.deactivate, m['id'], heir) is not state.FAILED: st.rerun()
        elif st.button('Reactivate'):
            if state.guarded(identity.reactivate, m['id']) is not state.FAILED: st.rerun()
    with mfa_tab:
        st.write('For a lost phone. They must set up two-step verification again at next sign-in. Requires your password and a reason.')
        reason = st.text_input('Reason / ticket number', key='mfa_reason')
        if st.button('Reset two-step verification'):
            if state.guarded(identity.admin_reset_mfa, m['id'], reason) is not state.FAILED: st.success('Reset. They have been signed out.')
