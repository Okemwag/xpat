"""Xpat — Nairobi flood risk. Run: make app (starts the auth/API server and Streamlit)."""
import os
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
# Read .env (KEY=VALUE lines) without overriding variables already set in the environment.
if (ROOT/'.env').exists():
    for line in (ROOT/'.env').read_text().splitlines():
        key, sep, value = line.strip().partition('=')
        if sep and key and not key.startswith('#') and value.strip():
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))

from ui import state  # noqa: E402  (after .env so runtime settings apply)
st.set_page_config(page_title='Xpat · Nairobi flood risk', page_icon=str(ROOT/'logo.png'), layout='wide', initial_sidebar_state='expanded')
st.logo(str(ROOT/'logo.png'), size='large')

principal, reason = state.resolve()
P = lambda path, title, icon, **kw: st.Page(path, title=title, icon=icon, **kw)

if principal is None:
    public = [P('views/landing.py', 'Welcome', ':material/home:', default=True), P('views/solutions.py', 'Solutions', ':material/category:')]
    if (ROOT/'app'/'views'/'pricing.py').exists(): public.append(P('views/pricing.py', 'Pricing', ':material/sell:'))
    public += [P('views/signin.py', 'Sign in', ':material/login:'), P('views/method.py', 'How the model works', ':material/menu_book:')]
    if reason == 'expired': st.toast('Your session expired. Please sign in again.', icon=':material/schedule:')
    st.navigation(public, position='top').run()
    st.stop()

if principal.extra.get('mfa_setup_required'):
    st.navigation([P('views/mfa_setup.py', 'Set up two-step verification', ':material/security:', default=True)], position='hidden').run()
    st.stop()

can = principal.can
workspace = [P('views/overview.py', 'Overview', ':material/dashboard:', default=True)]
if can('runs.create'): workspace.append(P('views/portfolio.py', 'Portfolio', ':material/upload_file:'))
if can('runs.read'): workspace.append(P('views/submissions.py', 'Submissions', ':material/work:'))
workspace.append(P('views/notifications.py', 'Notifications', ':material/notifications:'))
results = [P('views/results.py', 'Loss curve', ':material/show_chart:'), P('views/map.py', 'Accumulation map', ':material/map:'),
           P('views/property.py', 'Property explorer', ':material/home_work:')]
model = [P('views/assumptions.py', 'Assumptions & governance', ':material/tune:')]
if can('evidence.add') or can('evidence.approve'): model.append(P('views/evidence.py', 'AI flood evidence', ':material/auto_awesome:'))
model += [P('views/honesty.py', 'Data & honesty', ':material/verified:'), P('views/method.py', 'How the model works', ':material/menu_book:')]
account = ([P('views/history.py', 'Reports & history', ':material/history:')] if can('runs.read') else []) + [P('views/account.py', 'Profile & security', ':material/person:')]
sections = {'Workspace': workspace, **({'Results': results} if can('runs.read') else {}), 'Model': model, 'Account': account}
admin = []
if can('users.manage'): admin += [P('views/admin.py', 'Users & invitations', ':material/group:'), P('views/admin_teams.py', 'Teams', ':material/groups:')]
if can('security.manage'): admin.append(P('views/admin_security.py', 'Security & sign-in', ':material/shield_lock:'))
if can('settings.manage'): admin.append(P('views/admin_settings.py', 'Organisation settings', ':material/settings:'))
if can('access_review.read') or can('usage.read'): admin.append(P('views/admin_review.py', 'Access review & usage', ':material/fact_check:'))
if can('audit.read'): admin.append(P('views/admin_audit.py', 'Audit log', ':material/receipt_long:'))
if admin: sections['Administration'] = admin
if principal.is_platform_admin: sections['Platform'] = [P('views/platform_orgs.py', 'Organisations', ':material/domain:')]
if not principal.org_id and principal.is_platform_admin:
    sections = {'Platform': [P('views/platform_orgs.py', 'Organisations', ':material/domain:', default=True)],
                'Account': [P('views/account.py', 'Profile & security', ':material/person:')]}
nav = st.navigation(sections)

with st.sidebar:
    org = state.org()
    with st.container(border=True):
        st.markdown(f"**{principal.display_name}**  \n{org.get('name', 'Xpat platform')}")
        st.caption(', '.join(r.replace('_', ' ') for r in principal.roles) or ('platform admin' if principal.is_platform_admin else ''))
        row = st.container(horizontal=True)
        if st.session_state.get('org_count', 0) > 1: row.link_button('Switch', state.auth_link('/auth/choose-org'), icon=':material/swap_horiz:')
        row.link_button('Sign out', state.auth_link('/auth/logout'), icon=':material/logout:')
    if principal.extra.get('support_access'): st.warning('Support access: you are viewing this organisation as Xpat support. Everything is audited.', icon=':material/support_agent:')
    if state.read_only(): st.error('This organisation is suspended: read-only.', icon=':material/block:')
    try:
        from floodcat.platform.data import list_notifications
        with state.platform().tx() as conn: unread = len(list_notifications(conn, principal, unread_only=True))
        if unread: st.page_link('views/notifications.py', label=f'{unread} unread notification(s)', icon=':material/notifications_active:')
    except Exception:
        pass
    if state.result(): st.caption(f"Current run: {st.session_state.get('run_label', '—')}")
    st.caption('AI: ' + ({'off': 'off for your organisation', 'extraction': 'document and description reading', 'full': 'all features'}[state.ai_mode()]
                         if state.ai_available() else 'not configured on this server'))
    st.caption('Results are indicative: proxy hazard, assumed return periods and uncalibrated damage curves — not a price.')
nav.run()
