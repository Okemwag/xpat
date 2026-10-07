import pandas as pd
import streamlit as st
from floodcat.core.constants import TIERS
from ui import state
from ui.charts import vulnerability_chart
from ui.components import badges

cfg = state.config()
st.title('How the model works')
st.caption('A catastrophe model in four stages, with every assumption stated. Labels: ')
badges('REAL', 'PROXY', 'SYNTHETIC', 'ASSUMPTION', 'AI')

st.header('1 · Hazard')
badges('PROXY')
st.write('Five raster maps give each 30 m cell of Nairobi a 0–1 flood susceptibility score, built from real terrain '
         '(basin elevation 45%, local depressions 20%, flatness 15%) and distance to OpenStreetMap rivers (20%). '
         'It is **not** measured flood depth and it cannot see drainage failures.')
st.info('**The tier names are about how extreme a cell is, not how often it floods.** “Extreme” keeps only the top 5% of cells — '
        'the narrowest footprint — so it stands for the most *frequent* event. “Common” keeps the top 40% — the widest footprint — '
        'so it stands for the *rarest* event.', icon=':material/lightbulb:')
st.dataframe(pd.DataFrame({'Tier': list(TIERS), 'Assumed return period': [state.rp_label(cfg.return_periods[t]) for t in TIERS],
                           'Annual chance': [f'{1/cfg.return_periods[t]:.1%}' for t in TIERS]}), hide_index=True)
st.caption('Return periods: ASSUMPTION, from the dataset metadata reference mapping; not fitted to Nairobi rainfall.')

st.header('2 · Vulnerability')
badges('REAL', 'ASSUMPTION')
st.write(f'Score → depth: **depth = score × {cfg.max_depth_m:g} m** (ASSUMPTION; pluvial flooding in Nairobi is typically 0.3–1.5 m). '
         f'Depth → damage: {cfg.vulnerability_source}.')
st.altair_chart(vulnerability_chart(cfg), width='stretch')
st.dataframe(pd.DataFrame([{'Class': state.class_label(c), 'Reads JRC curve at': f"depth ÷ {a['jrc_depth_scale']:g}",
                            'Damage cap': f"{a['damage_cap']:.0%}"} for c, a in cfg.class_adjustments.items()]), hide_index=True)
st.caption('Dashed line: the assumed maximum depth (a score of 1). Fragile classes reach a given damage at shallower depth; caps of 80–95% '
           'reflect that land and foundations survive. JRC Africa residential rests on South African and Mozambican data only.')

st.header('3 · Exposure')
badges('SYNTHETIC')
st.write('Each property needs an ID, latitude/longitude, housing class and insured value (KES). Uploaded files and AI-described '
         'portfolios pass the same validation. Only synthetic or test data is accepted.')

st.header('4 · Financial engine')
badges('ASSUMPTION')
st.write('For every property and tier: hazard score → depth → damage ratio → **loss = damage ratio × insured value**. '
         'Losses are summed per tier into the loss curve. Average annual loss integrates that curve over annual chance, assuming '
         f'no loss below a {state.rp_label(cfg.aal_zero_loss_return_period)} event and holding the rarest loss beyond '
         f'{state.rp_label(max(cfg.return_periods.values()))}. Losses are gross: no deductibles, limits or reinsurance.')

st.header('5 · AI')
badges('AI')
st.markdown('- **Free-text portfolios:** Gemini turns a description into structured records; places are located with OpenStreetMap; '
            'missing sizes are filled from stated class medians; you review every row before it is modelled.\n'
            '- **Drainage evidence:** Gemini extracts places, dates and flood mechanisms from reports, with verbatim quotes that are '
            'checked against the text. A named reviewer approves each item. Approved drainage evidence raises hazard within '
            f'{cfg.evidence_radius_m:g} m by up to {cfg.uplift_weight:.0%} of the remaining headroom, more for rarer tiers. '
            'The app shows the before/after loss curve and the named-hotspot hit rate before and after.')
