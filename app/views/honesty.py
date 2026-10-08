import pandas as pd
import streamlit as st
from floodcat.hazard.hotspots import hotspot_check
from floodcat.reporting.provenance import provenance
from ui import state
from ui.charts import hotspot_check_map, columns_chart
from ui.components import LABELS, explain, kpis, page_header, section

page_header('Data & honesty', 'What is real, what is a proxy, what is synthetic, what we assumed — and what the model cannot see.')
cfg = state.config(); rt = state.runtime()
report = state.result()
check = hotspot_check(rt.hotspots, rt.hazard)
evaluation = state.ingestion_eval()
origin = report.get('exposure_origin', {}) if report else {}
kpis([('Named hotspots the map finds', f"{check['flagged_any_tier']} of {check['hotspot_count']}", 'Score above zero in any tier at the hotspot centre'),
      ('Current run’s properties', (f"{origin.get('real', 0)} real · {origin.get('synthetic', 0)} synthetic" if report else 'no run loaded'),
       'Every record carries its own label'),
      ('AI reader test cases fully right', f"{evaluation['summary']['cases_fully_correct']} of {evaluation['summary']['cases']}" if evaluation else 'not run',
       'Held-out descriptions; every AI record is still reviewed'),
      ('Assumptions stated', sum(p['label'] == 'ASSUMPTION' for p in provenance(cfg)), 'All in configs/default.json, editable on Assumptions')])

# Hotspot check -------------------------------------------------------------------------------------------
section('How well does the baseline map find known flood areas?')
left, right = st.columns([3, 2], gap='large')
with left.container(border=True, height='stretch'):
    st.pydeck_chart(hotspot_check_map(check['points']), height=420, alt='Map of the 24 named flood hotspots, flagged or missed by the proxy')
    explain('The 24 government-named flood areas we could geocode. Filled blue circles with ✓ were flagged by the proxy map (score above zero); '
            'hollow circles with ✗ were missed.',
            'Most misses sit in the west and centre (Kibera, Westlands, Lavington, Kileleshwa…), where flooding comes from overwhelmed drains rather '
            'than low ground near rivers — exactly what a terrain-and-river proxy cannot see.',
            ['REAL', 'PROXY'], source='county hotspot names (real) · OSM coordinates (approximate) · proxy rasters ·')
with right.container(border=True, height='stretch'):
    st.markdown('**Hotspots flagged in each tier**')
    chart = columns_chart([{'Tier': f"{t} ({state.rp_label(cfg.return_periods[t])})", 'Hotspots flagged': n} for t, n in check['flagged_by_tier'].items()],
                          'Tier', 'Hotspots flagged', 'Hotspots flagged', height=200, sort=None)
    if chart: st.altair_chart(chart, width='stretch', alt='Named hotspots flagged by the proxy in each tier')
    st.caption('Wider (rarer) tiers flag more places. Tier names describe how extreme a cell is, not how often it floods.')
    missed = [p['name'] for p in check['points'] if not p['flagged_any_tier']]
    st.markdown(f'**Missed ({len(missed)})**')
    st.markdown(' · '.join(missed) or 'none')
    st.warning('These areas flood mainly because of drainage, which a terrain-and-river proxy cannot represent. The AI evidence stage targets exactly this gap.',
               icon=':material/visibility_off:')

# Provenance ---------------------------------------------------------------------------------------------
left, right = st.columns(2, gap='large')
with left.container(border=True, height='stretch'):
    section('Where every number comes from')
    rows = provenance(cfg, origin if report else None)
    st.dataframe(pd.DataFrame([{'Component': p['component'].replace('_', ' '), 'Label': p['label'], 'Detail': p['note']} for p in rows]),
                 hide_index=True, width='stretch', alt='Provenance label of each model component',
                 column_config={'Detail': st.column_config.TextColumn(width='large')})
    with st.container(horizontal=True, gap='small'):
        for label, (colour, meaning) in LABELS.items(): st.badge(label, color=colour, help=meaning)
with right.container(border=True, height='stretch'):
    section('Data sources')
    st.dataframe(pd.DataFrame([
        {'Data': 'Five pluvial proxy rasters', 'Label': 'PROXY', 'Notes': 'Copernicus GLO-30 terrain + OpenStreetMap rivers; 0–1 susceptibility, not depth; uncalibrated'},
        {'Data': '600-property starter portfolio', 'Label': 'SYNTHETIC', 'Notes': 'Generated for the hackathon; TIV ≈ 10× floor area × cost/m² (cause unconfirmed)'},
        {'Data': 'Uploaded schedules and documents', 'Label': 'REAL or SYNTHETIC', 'Notes': 'As declared by the user for each record; never committed or shared'},
        {'Data': '24 geocoded flood hotspots', 'Label': 'REAL (approximate)', 'Notes': "County's March 2026 list of 37; coordinates are OSM neighbourhood centres"},
        {'Data': 'Depth-damage curve', 'Label': 'REAL', 'Notes': 'Huizinga, de Moel & Szewczyk (2017), JRC105688, Table 3-1 (Africa, residential)'},
        {'Data': 'Return periods, max depth, class scales and caps, AAL rules', 'Label': 'ASSUMPTION', 'Notes': 'configs/default.json; editable on Assumptions'},
        {'Data': 'Underwriting rules', 'Label': 'ASSUMPTION', 'Notes': 'Each organisation’s own appetite; starter values in configs/underwriting_rules.json'},
        {'Data': 'Flood reports and extracted evidence', 'Label': 'REAL source, AI extraction', 'Notes': 'Every item keeps its source, verbatim quote and reviewer'},
    ]), hide_index=True, width='stretch', alt='Data sources and their labels', column_config={'Notes': st.column_config.TextColumn(width='large')})

# AI accuracy ---------------------------------------------------------------------------------------------
with st.container(border=True):
    section('How accurate is the AI portfolio reader?')
    if evaluation is None:
        st.info('No evaluation has been run yet. Run `make eval-ingestion` with a Gemini key.')
    else:
        s = evaluation['summary']
        def fmt(part): return '—' if part['rate'] is None else f"{part['correct']}/{part['total']}"
        kpis([('Test cases fully correct', f"{s['cases_fully_correct']}/{s['cases']}"),
              ('Housing class right', fmt(s['housing_class']), 'Including correctly flagging a class the text did not state'),
              ('Value per building within 2%', fmt(s['tiv_kes_each'])), ('Spurious extra groups', s['extra_groups'])])
        st.caption(f"{s['cases']} held-out, team-written synthetic descriptions (including a prompt-injection attempt, Swahili terms and group totals) · "
                   f"run {evaluation['generated']} · models {', '.join(evaluation['models'])} · prompt {evaluation['prompt_version']}. "
                   'A small check, not a statistical accuracy estimate; every AI record is still reviewed by a person before it is modelled.')

# Limitations ---------------------------------------------------------------------------------------------
with st.container(border=True):
    section('Limitations')
    items = ['The 600 sample properties are invented. They are not a real insurer\'s holdings.',
             'Hazard values are relative susceptibility, not measured depths or annual probabilities.',
             'The damage curve is a published regional curve adapted by assumption; it is not validated against Kenyan claims.',
             'The years attached to the five tiers are assumptions, so the loss curve compares assumed scenarios rather than forecasting annual loss.',
             'Losses are gross unless policy terms are applied; then insured loss is shown after per-property deductibles and limits. '
             'Reinsurance (treaties, layers, net-of-reinsurance loss) is not modelled — out of scope by the brief.',
             'A zero score means the proxy did not flag a place, not that it cannot flood.',
             'Hotspot coordinates are approximate neighbourhood centres, not flooded buildings.',
             'The named-hotspot check uses only known flood areas, so it cannot measure false alarms.',
             'Underwriting recommendations apply your organisation’s rules to these indicative results; they are not a price, and a person decides.',
             'AI outputs are reviewed by people but can still be wrong; every AI-derived value is labelled.']
    a, b = st.columns(2, gap='large')
    half = (len(items)+1)//2
    a.markdown('\n'.join(f'- {i}' for i in items[:half])); b.markdown('\n'.join(f'- {i}' for i in items[half:]))

if report:
    with st.expander('This run’s fingerprints', icon=':material/fingerprint:'):
        st.json({'analysis_id': report['analysis_id'], 'created_at': report['created_at'], 'config_version': report['config']['version'],
                 'config_fingerprint': report['config_fingerprint'], 'input_fingerprint': report['input_fingerprint'],
                 'hazard_provider': report['hazard_provider'], 'declarations': report.get('declarations', [])}, expanded=False)
