import pandas as pd
import streamlit as st
from floodcat.platform import identity, security
from floodcat.platform.rbac import ROLES
from ui import state
from ui.components import link, page_header, when

p = state.principal()
page_header('Profile & security')
profile, security_tab, sessions_tab, tokens_tab = st.tabs([':material/person: Profile', ':material/lock: Password & two-step',
                                                           ':material/devices: Sessions', ':material/key: API tokens'])
with profile:
    st.markdown(f"**{p.email}** · {state.org().get('name', '')}")
    for r in p.roles: st.caption(f'{r.replace("_", " ").title()} — {ROLES[r]}')
    with st.form('name'):
        name = st.text_input('Your name', value=p.display_name, max_chars=120)
        if st.form_submit_button('Save'):
            if state.guarded(identity.update_profile, name) is not state.FAILED: st.success('Saved.')
    if p.can('ai.extract'):
        from floodcat.ai.llm import LABEL, configured, describe
        from floodcat.platform import orgs
        st.subheader('AI model')
        s = state.org().get('settings', {})
        allowed = [x for x in s.get('ai_providers', []) if x in configured()]
        current = (s.get('ai_preferences') or {}).get(p.user_id)
        WHY = {'gemini': 'Faster and stronger at reading long documents. Text (contact details removed) is sent to Google.',
               'ollama': 'Runs on this server: text never leaves it. Slower on ordinary hardware and less reliable at reasoning; every answer is still checked.'}
        if not allowed:
            st.caption('No AI model your organisation allows is configured on this server.')
        else:
            options = [None] + allowed
            pick = st.radio('Use for my AI requests', options, index=options.index(current) if current in options else 0, key='ai_pref',
                            format_func=lambda x: 'Organisation default' if x is None else f'{LABEL[x]} — {describe(x)}')
            if pick: st.caption(WHY[pick])
            if s.get('ai_local_for_client_data'):
                st.info('Your organisation keeps client data on this server: documents, schedules, descriptions and results on real exposure always '
                        'use the local model, whatever you choose here. Your choice applies to public material such as news and public notes.',
                        icon=':material/shield:')
            unconfigured = [x for x in s.get('ai_providers', []) if x not in configured()]
            if unconfigured: st.caption('Allowed but not set up on this server: ' + ', '.join(LABEL[x] for x in unconfigured) + '.')
            if pick != current and st.button('Save AI model', key='ai_pref_save'):
                if state.guarded(orgs.set_ai_preference, pick) is not state.FAILED:
                    state.resolve(); st.success('Saved. New AI requests use it.')
    st.subheader('Change e-mail')
    st.caption('We send a confirmation link to the new address and a notice to the old one. Requires your password.')
    with st.form('email'):
        new_email = st.text_input('New work e-mail')
        if st.form_submit_button('Send confirmation link'):
            if state.guarded(identity.request_email_change, new_email) is not state.FAILED: st.info('A confirmation link is on its way to the new address.')

with security_tab:
    if p.extra.get('method') == 'sso':
        st.info('You sign in through your organisation\'s identity provider. Change your password there.', icon=':material/business:')
    elif p.extra.get('method') != 'guest':
        st.subheader('Change password')
        with st.form('pw'):
            old = st.text_input('Current password', type='password')
            new = st.text_input('New password', type='password', help=f'At least {security.MIN_PASSWORD} characters; checked against known breaches.')
            confirm = st.text_input('Confirm new password', type='password')
            if st.form_submit_button('Update password'):
                if new != confirm: st.error('The new passwords do not match.')
                else:
                    try:
                        with state.platform().tx() as conn: identity.change_password(conn, p, old, new, state.request_info())
                        st.success('Password updated. Your other sessions were signed out.')
                    except Exception as exc: st.error(str(exc))
    st.subheader('Two-step verification')
    if p.extra.get('mfa_enabled'):
        st.success('On — sign-ins need a code from your authenticator app.', icon=':material/verified_user:')
        a, b = st.columns(2)
        if a.button('New recovery codes'):
            codes = state.guarded(identity.regenerate_recovery_codes)
            if codes is not state.FAILED: st.code('\n'.join(codes)); st.caption('Old recovery codes no longer work. Save these now.')
        if b.button('Turn off'):
            if state.guarded(identity.disable_mfa) is not state.FAILED: st.rerun()
    else:
        st.warning('Off. Turn it on to protect your account.', icon=':material/gpp_maybe:')
        if st.button('Set up two-step verification', type='primary'):
            with state.platform().tx() as conn: st.session_state['mfa_secret'], st.session_state['mfa_uri'] = identity.begin_mfa(conn, p)
        if st.session_state.get('mfa_uri'):
            st.html(security.qr_svg(st.session_state['mfa_uri']))
            st.caption(f"Key: `{st.session_state['mfa_secret']}`")
            code = st.text_input('6-digit code from the app', key='acct_mfa_code')
            if st.button('Confirm'):
                try:
                    with state.platform().tx() as conn: codes = identity.confirm_mfa(conn, p, code, state.request_info())
                    st.session_state.pop('mfa_uri'); st.session_state.pop('mfa_secret')
                    st.success('Two-step verification is on. Save these recovery codes:'); st.code('\n'.join(codes))
                except Exception as exc: st.error(str(exc))

with sessions_tab:
    with state.platform().tx() as conn: rows = identity.list_sessions(conn, p)
    st.caption('Where you are signed in. Signing out a session takes effect immediately.')
    for s in rows:
        with st.container(border=True, horizontal=True, vertical_alignment='center'):
            st.markdown(f"**{'This browser' if s['current'] else (s['user_agent'] or 'Unknown device')[:60]}** · {s['method']}  \n"
                        f"From {s['ip'] or '?'} · signed in {when(s['created_at'])} · last active {when(s['last_seen_at'])}")
            if not s['current'] and st.button('Sign out', key=f"rev_{s['id']}"):
                with state.platform().tx() as conn: identity.revoke_session(conn, p, s['id'], state.request_info())
                st.rerun()
    if len(rows) > 1 and st.button('Sign out all other sessions'):
        with state.platform().tx() as conn: identity.revoke_all_sessions(conn, p.user_id, except_session=p.session_id, reason='user_request', actor=p)
        st.rerun()

with tokens_tab:
    st.caption('Tokens let scripts call the Xpat API as you, limited to the scopes you choose. A token is shown once; store it like a password.')
    with st.form('token'):
        name = st.text_input('Name', value='My integration')
        scopes = st.multiselect('Scopes', [s for s in identity.API_SCOPES if p.can(s)], default=[s for s in ('runs.read',) if p.can(s)])
        days = st.select_slider('Expires after (days)', [7, 30, 90, 180, 365], value=90)
        if st.form_submit_button('Create token'):
            raw = state.guarded(identity.create_api_token, name, scopes, days)
            if raw is not state.FAILED: st.success('Copy this token now — it will not be shown again.'); st.code(raw)
    with state.platform().tx() as conn: tokens = identity.list_api_tokens(conn, p)
    for t in tokens:
        with st.container(border=True, horizontal=True, vertical_alignment='center'):
            status = 'revoked' if t['revoked_at'] else 'active'
            st.markdown(f"**{t['name']}** `{t['prefix']}…` · {', '.join(t['scopes'])} · {status}  \n"
                        f"Created {when(t['created_at'])} · expires {when(t['expires_at'])} · last used {when(t['last_used_at'])}")
            if not t['revoked_at'] and st.button('Revoke', key=f"tok_{t['id']}"):
                if state.guarded(identity.revoke_api_token, t['id']) is not state.FAILED: st.rerun()
