from decimal import Decimal
import streamlit as st
from floodcat.core.errors import ModelError
from ui import state
from ui.briefing_view import briefing_panel
from ui.charts import donut, hbars, ylt_chart
from ui.components import badges, explain, kpis, page_header, require_result, run_banner, section

page_header('Overview')
report = require_result()
run_banner(report)
cfg = state.config()
run = report['runs']['baseline']
curve = {p['return_period_years']: p for p in run['ep_curve']}
rarest_rp = max(curve); tier_100 = state.tier_for_rp(cfg, 100.0) if 100.0 in curve else run['ep_curve'][-2]['tier']
rarest = state.tier_for_rp(cfg, rarest_rp)
flagged = sum(1 for r in run['property_losses'][rarest] if r['hazard_score'] > 0)
kpis([('Insured value', state.kes(report['modelled_tiv_kes']), f"{report['modelled_count']} properties"),
      ('1-in-100 loss', state.kes(curve[100.0]['loss_kes']) if 100.0 in curve else '—', 'Assumed 1% chance per year', state.pct(curve.get(100.0, {}).get('loss_pct_of_tiv')) + ' of value' if 100.0 in curve else None),
      (f'1-in-{rarest_rp:g} loss', state.kes(curve[rarest_rp]['loss_kes']), None, state.pct(curve[rarest_rp]['loss_pct_of_tiv']) + ' of value'),
      ('Average annual loss', state.kes(run['aal']['aal_kes']), 'Long-run yearly average'),
      ('Properties flagged', f"{flagged} / {report['modelled_count']}", 'Hazard score above zero in at least one tier')])

review = st.session_state.get('submission_review')
if review and review.get('label') == st.session_state.get('run_label'):
    warn = [c for p in review['properties'] for c in p['checks'] if c['severity'] in ('error', 'warning')]
    with st.expander(f"Submission review · {len(warn)} point(s) to check", icon=':material/fact_check:', expanded=False):
        for c in warn: st.markdown(f"- {c['message']}")

left, right = st.columns([3, 2], gap='large')
with left.container(border=True):
    section('Loss vs flood rarity')
    try:
        st.altair_chart(ylt_chart(state.ylt(report), report, compare_ai=report['ai_contribution']['enabled']), width='stretch')
        explain('Portfolio loss against how rare the year’s worst flood is (10,000 simulated years); diamonds are the five hazard scenarios.',
                '“1-in-100” ≈ 1% chance in any year of a loss at least this large.', ['PROXY', 'ASSUMPTION', *state.exposure_labels(report)])
    except ModelError as exc:
        st.warning(str(exc))
with right.container(border=True):
    section('Loss by construction', f'1-in-{cfg.return_periods[tier_100]:g}')
    items = run['breakdowns'][tier_100]['construction']
    chart = donut([{'Class': state.class_label(i['id']), 'Loss': float(Decimal(i['loss_kes'])), 'Amount': state.kes(i['loss_kes'])} for i in items],
                  'Class', 'Loss', fmt='Amount')
    if chart: st.altair_chart(chart, width='stretch')
    else: st.caption('No modelled loss.')
    explain('Share of the loss from each construction class.', 'Larger slice = more of the loss.', [*state.exposure_labels(report), 'ASSUMPTION'])

c1, c2 = st.columns(2, gap='large')
with c1.container(border=True, height='stretch'):
    section('Where it concentrates', f'Share of 1-in-{cfg.return_periods[tier_100]:g} loss by named flood area')
    areas = run['breakdowns'][tier_100].get('hotspot_area', [])
    rows = [{'Area': a['id'] if not a['id'].startswith('no named') else 'Away from named areas', 'Share (%)': round(a['loss_share_pct'], 1),
             'Loss': state.kes(a['loss_kes']), 'Properties': a['property_count'], '_label': f"{a['loss_share_pct']:.0f}%"} for a in areas[:7]]
    chart = hbars(rows, 'Area', 'Share (%)', 'Share of loss (%)', text='_label')
    if chart: st.altair_chart(chart, width='stretch')
    if st.button('Open map', icon=':material/map:'): st.switch_page('views/map.py')
with c2.container(border=True, height='stretch'):
    section('Largest losses', f'1-in-{rarest_rp:g}')
    top = run['breakdowns'][rarest]['top_properties'][:6]
    rows = [{'Property': p['loc_id'], 'Loss (KES m)': round(float(Decimal(p['loss_kes']))/1e6, 1), 'Class': state.class_label(p['housing_class']),
             'Damage': f"{p['damage_ratio']:.0%}", '_label': state.kes(p['loss_kes'])} for p in top]
    chart = hbars(rows, 'Property', 'Loss (KES m)', 'Loss (KES m)', text='_label', color='#eb6834')
    if chart: st.altair_chart(chart, width='stretch')
    if st.button('Explore properties', icon=':material/home_work:'): st.switch_page('views/property.py')

a, b = st.columns([3, 2], gap='large')
with a.container(border=True):
    section('AI underwriting briefing'); badges('AI')
    briefing_panel()
with b.container(border=True, height='stretch'):
    section('AI flood evidence')
    ai = report['ai_contribution']
    if ai['enabled']:
        kpis([('Properties changed', ai['changed_properties']), ('Change in AAL', state.kes(ai['aal_delta_kes']))], columns=2)
    else:
        st.metric('Evidence applied', 'None', help='The hazard map misses drainage flooding; reviewed reports can correct it.', border=True)
    if st.button('Flood evidence', icon=':material/auto_awesome:'): st.switch_page('views/evidence.py')
