import pandas as pd
import streamlit as st
from floodcat.core.constants import TIERS
from floodcat.hazard.hotspots import hotspot_check
from floodcat.reporting.provenance import provenance
from ui import state
from ui.charts import hotspot_check_map
from ui.components import LABELS, badges, explain, page_header

page_header('Data & honesty', 'What is real, what is a proxy, what is synthetic, what we assumed — and what the model cannot see.')
cfg = state.config(); rt = state.runtime()

st.subheader('Where every number comes from')
st.dataframe(pd.DataFrame([{'Component': p['component'].replace('_', ' '), 'Label': p['label'], 'What it means': LABELS[p['label']][1], 'Detail': p['note']}
                           for p in provenance(cfg)]), hide_index=True, width='stretch')

st.subheader('Data sources')
st.markdown("""
| Data | Label | Notes |
|---|---|---|
| Five pluvial proxy rasters (`nairobi_pluvial_proxy_*.tif`) | PROXY | Copernicus GLO-30 terrain + OpenStreetMap rivers; 0–1 susceptibility, not depth; uncalibrated |
| 600-property exposure file | SYNTHETIC | Generated for the hackathon starter kit; TIV ≈ 10× floor area × cost/m² (cause unconfirmed) |
| 24 geocoded flood hotspots | REAL (approximate) | Names from the county's March 2026 list of 37; coordinates from OSM Nominatim neighbourhood centres |
| Depth-damage curve | REAL | Huizinga, de Moel & Szewczyk (2017), *Global flood depth-damage functions*, JRC105688, Table 3-1 |
| Return periods, max depth, class scales/caps, AAL rules | ASSUMPTION | All in `configs/default.json`; editable on the Assumptions page |
| Flood reports and extracted evidence | REAL source, AI extraction | Every item keeps its source, verbatim quote and reviewer |
""")

st.subheader('How well does the baseline map find known flood areas?')
check = hotspot_check(rt.hotspots, rt.hazard)
a, b = st.columns([1, 2])
a.metric('Named hotspots flagged', f"{check['flagged_any_tier']} of {check['hotspot_count']}")
a.caption('Flagged = score above zero in any tier at the hotspot\'s approximate centre.')
b.dataframe(pd.DataFrame([{'Tier': t, 'Return period': state.rp_label(cfg.return_periods[t]), 'Hotspots flagged': n}
                          for t, n in check['flagged_by_tier'].items()]), hide_index=True, width='stretch')
st.pydeck_chart(hotspot_check_map(check['points']), height=420)
explain('The 24 government-named flood areas we could geocode. Filled blue circles with ✓ were flagged by the proxy map (score above zero); '
        'hollow circles with ✗ were missed.',
        'Most misses sit in the west and centre (Kibera, Westlands, Lavington, Kileleshwa…), where flooding comes from overwhelmed drains rather '
        'than low ground near rivers — exactly what a terrain-and-river proxy cannot see.',
        ['REAL', 'PROXY'], source='county hotspot names (real) · OSM coordinates (approximate) · proxy rasters ·')
missed = [p['name'] for p in check['points'] if not p['flagged_any_tier']]
st.warning('Missed by the proxy: ' + ', '.join(missed) + '. These areas flood mainly because of drainage, which a terrain-and-river '
           'proxy cannot represent. The AI evidence stage targets exactly this gap.', icon=':material/visibility_off:')

st.subheader('How accurate is the AI portfolio reader?')
evaluation = state.ingestion_eval()
if evaluation is None:
    st.info('No evaluation has been run yet. Run `scripts/evaluate_ingestion.py` with a Gemini key.')
else:
    s = evaluation['summary']
    def fmt(part): return '—' if part['rate'] is None else f"{part['correct']}/{part['total']}"
    a, b, c, d = st.columns(4)
    a.metric('Test cases fully correct', f"{s['cases_fully_correct']}/{s['cases']}")
    b.metric('Housing class right', fmt(s['housing_class']), help='Including correctly flagging a class the text did not state')
    c.metric('Value per building within 2%', fmt(s['tiv_kes_each']))
    d.metric('Spurious extra groups', s['extra_groups'])
    st.caption(f"{s['cases']} held-out, team-written synthetic descriptions (including a prompt-injection attempt, Swahili terms and group totals) · "
               f"run {evaluation['generated']} · models {', '.join(evaluation['models'])} · prompt {evaluation['prompt_version']}. "
               'A small check, not a statistical accuracy estimate; every AI record is still reviewed by a person before it is modelled.')
    badges('AI')

st.subheader('Limitations')
for item in ['The 600 properties are invented. They are not a real insurer\'s holdings.',
             'Hazard values are relative susceptibility, not measured depths or annual probabilities.',
             'The damage curve is a published regional curve adapted by assumption; it is not validated against Kenyan claims.',
             'The years attached to the five tiers are assumptions, so the loss curve compares assumed scenarios rather than forecasting annual loss.',
             'Losses are gross of policy terms: no deductibles, limits or reinsurance.',
             'A zero score means the proxy did not flag a place, not that it cannot flood.',
             'Hotspot coordinates are approximate neighbourhood centres, not flooded buildings.',
             'The named-hotspot check uses only known flood areas, so it cannot measure false alarms.',
             'AI outputs are reviewed by people but can still be wrong; every AI-derived value is labelled.']:
    st.markdown(f'- {item}')

report = state.result()
if report:
    st.subheader('This run')
    st.json({'analysis_id': report['analysis_id'], 'created_at': report['created_at'], 'config_version': report['config']['version'],
             'config_fingerprint': report['config_fingerprint'], 'input_fingerprint': report['input_fingerprint'],
             'hazard_provider': report['hazard_provider'], 'declarations': report.get('declarations', [])}, expanded=False)
