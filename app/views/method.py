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

st.header('A catastrophe model in four stages')
st.markdown("""
| Stage | Question | In Xpat |
|---|---|---|
| **Hazard** | Where does flooding happen, and how severe is it? | Five proxy rasters give each place a 0–1 severity score per tier |
| **Vulnerability** | How much damage at that severity? | Score → assumed depth → adapted JRC depth-damage curve per construction class |
| **Exposure** | What is there and what is it worth? | Validated property records (CSV, AI-described or sample) |
| **Financial engine** | What does it cost, and how often? | Damage × value per property → five scenario losses → 10,000 simulated years → loss curve and AAL |
""")
st.header('What a return period is — and is not')
st.markdown("""
- A **1-in-100-year loss** is a loss with about a **1% chance of being reached or exceeded in any one year**.
- It is **not** a loss that happens once every 100 years, and it can happen twice in a decade by chance.
- Over a 30-year building life, a 1-in-100 event has about a 26% chance of happening at least once (1 − 0.99³⁰).
- The **average annual loss** is the long-run yearly average — what you would set aside every year if the model were right.
""")
st.header('Why simulate 10,000 years?')
st.markdown(f"""
The hazard data gives five scenarios, not a year-by-year history. To read losses at any rarity, Xpat simulates 10,000 years. Each year draws
how rare its worst flood is and one plausible version of the damage curves, then reads the loss between the five scenario points. Sorting
the years gives the loss curve; re-sampling them gives the grey band. Floods more frequent than
1-in-{cfg.aal_zero_loss_return_period:g} are assumed to cause no loss, and nothing rarer than 1-in-{max(cfg.return_periods.values()):g} is modelled
— beyond that the curve only reflects damage uncertainty. All of this is ASSUMPTION, not fitted to Nairobi flood records.
""")
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
badges('REAL', 'SYNTHETIC')
st.write('Each property needs an ID, latitude/longitude, housing class and insured value (KES). Uploaded files and AI-described '
         'portfolios pass the same validation. Schedules (CSV, Excel) are read directly; broker documents (PDF, Word) are read by AI '
         'with every value quoted and checked. Real data is labelled REAL, synthetic data SYNTHETIC.')

st.header('4 · Financial engine')
badges('ASSUMPTION')
st.write('For every property and tier: hazard score → depth → damage ratio → **loss = damage ratio × insured value**. '
         'Losses are summed per tier into the loss curve. Average annual loss integrates that curve over annual chance, assuming '
         f'no loss below a {state.rp_label(cfg.aal_zero_loss_return_period)} event and holding the rarest loss beyond '
         f'{state.rp_label(max(cfg.return_periods.values()))}.')
st.markdown('**Insured vs reinsured.** Results are **gross** (ground-up). With policy terms on, Xpat also gives the **insured** loss after each '
            'property\'s deductible and limit — including facultative terms read from a submission. **Reinsured** loss (net of treaties, '
            'layers or quota shares) is not modelled: the brief puts reinsurance structuring out of scope.')

st.header('5 · AI')
badges('AI')
st.markdown('- **Free-text portfolios:** Gemini turns a description into structured records; places are located with OpenStreetMap; '
            'missing sizes are filled from stated class medians; you review every row before it is modelled.\n'
            '- **Drainage evidence:** Gemini extracts places, dates and flood mechanisms from reports, with verbatim quotes that are '
            'checked against the text. A named reviewer approves each item. Approved drainage evidence raises hazard within '
            f'{cfg.evidence_radius_m:g} m by up to {cfg.uplift_weight:.0%} of the remaining headroom, more for rarer tiers. '
            'The app shows the before/after loss curve and the named-hotspot hit rate before and after.')
