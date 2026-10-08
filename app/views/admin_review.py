import pandas as pd
import streamlit as st
from floodcat.platform import orgs
from ui import state
from ui.components import page_header, when

p = state.principal()
page_header('Access review & usage', 'Who has access, who has not signed in for 90 days, and which admins lack two-step verification.')
if p.can('access_review.read'):
    with state.platform().tx() as conn: rows = orgs.access_review(conn, p)
    a, b, c = st.columns(3)
    a.metric('Active members', sum(r['status'] == 'active' for r in rows))
    b.metric('Dormant (90+ days)', sum(r['dormant'] for r in rows))
    c.metric('Admins without two-step', sum(r['admin_without_mfa'] for r in rows))
    frame = pd.DataFrame([{'Name': r['display_name'], 'E-mail': r['email'], 'Roles': ', '.join(r['roles']), 'Status': r['status'],
                           'Last sign-in': when(r['last_login_at']), 'Two-step': 'on' if r['mfa_enabled_at'] else 'off',
                           'Review': '; '.join(x for x, y in (('dormant — remove?', r['dormant']), ('admin without two-step', r['admin_without_mfa'])) if y) or 'ok'}
                          for r in rows])
    st.dataframe(frame, hide_index=True, width='stretch')
    st.download_button('Download review (CSV)', frame.to_csv(index=False), 'xpat-access-review.csv', 'text/csv')
    st.caption('Run this review every quarter and keep the download as evidence for auditors. Generating it is recorded in the audit log.')
if p.can('usage.read'):
    st.subheader('Usage (last 30 days)')
    with state.platform().tx() as conn: usage = orgs.usage_summary(conn, p)
    a, b, c = st.columns(3)
    a.metric('Properties modelled', f"{usage.get('properties_modelled', 0):,}"); b.metric('Documents read by AI', usage.get('documents_read', 0))
    c.metric('AI calls', usage.get('ai_calls', 0))
