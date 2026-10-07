from decimal import Decimal
import streamlit as st
from ui import state
from ui.charts import class_bars, ep_chart
from ui.components import badges, headline_tiles, page_header, require_result, run_banner

user = state.user()
page_header(f"Hello, {user['display_name'].split()[0]}", 'Your portfolio flood loss at a glance.')
report = require_result()
run_banner(report)
headline_tiles(report)

left, right = st.columns([3, 2], gap='large')
with left:
    with st.container(border=True):
        st.subheader('Loss vs. flood rarity')
        st.caption('Each point is one hazard tier. Rarer floods (right) cause larger losses. Hover for exact values.')
        st.altair_chart(ep_chart(report, compare_ai=report['ai_contribution']['enabled']), width='stretch')
        badges('PROXY', 'ASSUMPTION', 'SYNTHETIC')
with right:
    with st.container(border=True):
        st.subheader('Loss by construction (1-in-100)')
        cfg = state.config()
        tier = state.tier_for_rp(cfg, 100.0) if 100.0 in cfg.return_periods.values() else 'common'
        st.altair_chart(class_bars(report['runs']['baseline']['breakdowns'][tier]['construction']), width='stretch')
        st.caption('Bar labels show each class\'s share of the loss.')

run = report['runs']['baseline']
cfg = state.config()
rarest = max(cfg.return_periods, key=cfg.return_periods.get)
c1, c2 = st.columns(2, gap='large')
with c1.container(border=True, height='stretch'):
    st.subheader('Where the loss concentrates')
    areas = [a for a in run['breakdowns'][tier]['hotspot_area'] if a['id'] != 'no named hotspot within radius'][:5]
    outside = next((a for a in run['breakdowns'][tier]['hotspot_area'] if a['id'] == 'no named hotspot within radius'), None)
    for a in areas:
        st.markdown(f"**{a['id']}** — {state.kes(a['loss_kes'])} ({a['loss_share_pct']:.1f}% of loss) · {a['property_count']} properties")
    if outside: st.caption(f"{outside['loss_share_pct']:.0f}% of the loss is more than {cfg.hotspot_tag_radius_m/1000:g} km from any named hotspot.")
    if st.button('Open the accumulation map', icon=':material/map:'): st.switch_page('views/map.py')
with c2.container(border=True, height='stretch'):
    st.subheader(f'Largest property losses ({state.rp_label(cfg.return_periods[rarest])})')
    for p in run['breakdowns'][rarest]['top_properties'][:5]:
        st.markdown(f"**{p['loc_id']}** · {state.class_label(p['housing_class'])} — {state.kes(p['loss_kes'])} "
                    f"({p['damage_ratio']:.0%} damage at {p['assumed_depth_m']:.2f} m)")
    if st.button('Explore properties', icon=':material/home_work:'): st.switch_page('views/property.py')

ai = report['ai_contribution']
with st.container(border=True):
    st.subheader('AI effect on this run')
    if ai['enabled']:
        delta = Decimal(ai['aal_delta_kes'])
        st.markdown(f"{ai['applied_evidence_count']} approved drainage report(s) changed the hazard at **{ai['changed_properties']}** properties. "
                    f"Average annual loss {'rose' if delta > 0 else 'changed'} by **{state.kes(delta)}**.")
        badges('AI')
    else:
        st.write('The baseline map misses drainage-driven flooding (it flags 12 of 24 named flood areas). '
                 'Add reviewed flood reports to see how losses change.')
    if st.button('Go to AI flood evidence', icon=':material/auto_awesome:'): st.switch_page('views/evidence.py')
