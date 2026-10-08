from datetime import datetime, timezone
import pandas as pd
import streamlit as st
from floodcat.platform import orgs
from ui import state
from ui.charts import columns_chart
from ui.components import kpis, page_header, section, when

p = state.principal()
page_header('Access review & usage', 'Who has access, who has not signed in for 90 days, and which admins lack two-step verification.')

def since_sign_in(value):
    if value is None: return 'Never'
    value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - value).days
    return 'Last 7 days' if days <= 7 else 'Last 30 days' if days <= 30 else 'Last 90 days' if days <= 90 else 'Over 90 days'

if p.can('access_review.read'):
    with state.platform().tx() as conn: rows = orgs.access_review(conn, p)
    active = [r for r in rows if r['status'] == 'active']
    kpis([('Active members', len(active)), ('Dormant (90+ days)', sum(r['dormant'] for r in rows), 'Consider removing their access'),
          ('Admins without two-step', sum(r['admin_without_mfa'] for r in rows), 'Should be zero'),
          ('Two-step on', f"{sum(bool(r['mfa_enabled_at']) for r in active)} of {len(active)}")])
    left, right = st.columns([1, 2], gap='large')
    with left.container(border=True, height='stretch'):
        section('Last sign-in')
        order = ['Last 7 days', 'Last 30 days', 'Last 90 days', 'Over 90 days', 'Never']
        buckets = [since_sign_in(r['last_login_at']) for r in active]
        chart = columns_chart([{'When': b, 'Members': buckets.count(b)} for b in order], 'When', 'Members', 'Members', height=220, sort=order)
        st.altair_chart(chart, width='stretch', alt='Active members by time since last sign-in')
    with right.container(border=True, height='stretch'):
        section('Review list')
        frame = pd.DataFrame([{'Name': r['display_name'], 'E-mail': r['email'], 'Roles': ', '.join(r['roles']), 'Status': r['status'],
                               'Last sign-in': when(r['last_login_at']), 'Two-step': 'on' if r['mfa_enabled_at'] else 'off',
                               'Review': '; '.join(x for x, y in (('dormant — remove?', r['dormant']), ('admin without two-step', r['admin_without_mfa'])) if y) or 'ok'}
                              for r in rows])
        st.dataframe(frame, hide_index=True, width='stretch', alt='Access review of every member')
        st.download_button('Download review (CSV)', frame.to_csv(index=False), 'xpat-access-review.csv', 'text/csv', icon=':material/download:')
    st.caption('Run this review every quarter and keep the download as evidence for auditors. Generating it is recorded in the audit log.')
if p.can('usage.read'):
    with state.platform().tx() as conn: usage = orgs.usage_summary(conn, p)
    section('Usage (last 30 days)')
    kpis([('Properties modelled', f"{usage.get('properties_modelled', 0):,}"), ('Documents read by AI', usage.get('documents_read', 0)),
          ('AI calls', usage.get('ai_calls', 0))])
