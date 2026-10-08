import streamlit as st
from ui import site, state

site.css()

@st.cache_data(show_spinner=False)
def sample_headline():
    report = state.runtime().run(state.runtime().sample_rows())
    curve = {p['return_period_years']: p for p in report['runs']['baseline']['ep_curve']}
    return {'tiv': report['modelled_tiv_kes'], 'count': report['modelled_count'], 'rp100': curve[100.0]['loss_kes'],
            'pct100': curve[100.0]['loss_pct_of_tiv'], 'aal': report['runs']['baseline']['aal']['aal_kes'],
            'rp250': curve[250.0]['loss_kes']}

# Hero ---------------------------------------------------------------------------------------------
left, right = st.columns([3, 2], gap='large', vertical_alignment='center')
with left:
    site.hero('Catastrophe-risk intelligence for African insurers',
              "Know what a Nairobi flood could <span class='x-accent'>cost your portfolio</span>",
              'Upload a portfolio — or describe it in plain English — and get an explainable flood loss estimate in seconds: '
              'by property, by place, and by how rare the flood is, with every assumption on the table.')
    st.space('small')
    site.cta_row(key='hero')
    st.caption('No credit card. The sample portfolio is ready to run.')
with right:
    with st.container(border=True):
        st.caption('LIVE PREVIEW · SAMPLE PORTFOLIO (SYNTHETIC)')
        try:
            h = sample_headline()
            st.metric('Insured value modelled', state.kes(h['tiv']), help=f"{h['count']} synthetic Nairobi properties")
            a, b = st.columns(2)
            a.metric('1-in-100 loss', state.kes(h['rp100']), help=f"{state.pct(h['pct100'])} of insured value")
            b.metric('1-in-250 loss', state.kes(h['rp250']))
            st.metric('Average annual loss', state.kes(h['aal']))
            st.caption('Computed just now by the same engine you will use. Illustrative only.')
        except Exception as exc:  # the landing page must never crash
            st.warning(f'Live preview unavailable: {exc}')

# Proof strip --------------------------------------------------------------------------------------
st.space('medium')
with st.container(border=True):
    site.stats([('< 1 second', 'to model 600 properties'), ('10,000', 'simulated years per loss curve'),
                ('12 of 24', 'named flood areas the standard map misses — we show it'), ('12 / 12', 'AI portfolio test cases read correctly')])

# Problem ------------------------------------------------------------------------------------------
site.section('The problem', 'Flood is Kenya’s costliest peril — and it is priced by judgement',
             'There is no locally calibrated flood model for Kenyan risks, no public measure of surface-water flood hazard in Nairobi, '
             'and global vendor models depend on claims data you cannot see.')
site.cards([
    ('🌧️', 'Blind spots in the hazard', 'Broad maps miss blocked drains and runoff — the cause of much of Nairobi’s flooding.', ()),
    ('🏘️', 'Hidden accumulation', 'You know your total insured value, not how much of it one storm could hit at once.', ()),
    ('🧾', 'Black-box numbers', 'A single risk score cannot be defended to a committee, a reinsurer or a regulator.', ()),
])

# How it works -------------------------------------------------------------------------------------
site.section('How it works', 'From a spreadsheet to a defensible loss curve in four steps')
site.cards([
    ('1', 'Load your exposure', 'Upload a CSV, describe buildings in words, or start from the sample. Every record is validated first.', ()),
    ('2', 'Score the hazard', 'Each property is read against five flood-severity maps of Nairobi — automatically, at its exact location.', ()),
    ('3', 'Estimate damage', 'A published JRC depth-damage curve, adapted per construction type, turns severity into damage.', ()),
    ('4', 'Price the risk', 'Damage × value per property, 10,000 simulated years, a loss curve, average annual loss and ranges.', ()),
], columns=4)

# Features -----------------------------------------------------------------------------------------
site.section('Platform', 'Everything an underwriting decision needs, in one place')
site.cards([
    ('📈', 'Loss curve & AAL', 'Loss at 1-in-10 to 1-in-10,000 years on a simulated year-loss table, with ranges and plain-English labels.', ()),
    ('🗺️', 'Accumulation map', 'See value, hazard and loss together; group by grid cell or named flood area.', ()),
    ('🔍', 'Property trace', 'Click any building: value → hazard → depth → damage → loss, with the arithmetic shown.', ()),
    ('🎚️', 'Live assumptions', 'Change flood depth, return periods, damage curves or policy terms and re-run instantly.', ()),
    ('✍️', 'AI portfolio reader', '“20 iron-sheet houses in Mathare at 300k each” becomes validated records you review.', ()),
    ('🛰️', 'Drainage evidence AI', 'Turn flood reports into reviewed evidence that fixes what the map misses — and measure the change.', ()),
])

# Solutions teaser ---------------------------------------------------------------------------------
site.section('Solutions', 'Built for everyone who carries or manages flood risk')
cols = st.columns(4, gap='medium')
for col, (icon, title, text) in zip(cols, [
        ('🧮', 'Underwriters', 'A defensible loss at the return period you budget for.'),
        ('📊', 'Portfolio managers', 'Where your insured value is concentrated.'),
        ('🤝', 'Reinsurers & brokers', 'Fast, consistent first-look flood quotes.'),
        ('🏛️', 'Counties & DRM bodies', 'Where flood risk and assets meet.')]):
    with col: site.card(icon, title, text)
if st.button('Explore solutions', icon=':material/arrow_forward:'): st.switch_page('views/solutions.py')

# Trust --------------------------------------------------------------------------------------------
site.section('Honest by design', 'Every number tells you where it came from')
site.cards([
    ('✅', 'Labelled provenance', 'Each result is tagged REAL, PROXY, SYNTHETIC, ASSUMPTION or AI — in the interface and in every export.', ()),
    ('📚', 'Sourced methods', 'Damage curves from the EU Joint Research Centre (Huizinga et al., 2017), cited and compared openly.', ()),
    ('🧑‍⚖️', 'People approve AI', 'AI never sets a loss. Its outputs are checked against the source and approved by a named reviewer.', ()),
])

# FAQ ----------------------------------------------------------------------------------------------
site.section('FAQ', 'Questions we hear first')
faq = [
    ('Is this a calibrated model?', 'No. Xpat is a prototype built for the Nairobi Urban Flood Challenge. The hazard is a proxy, return periods are '
     'assumptions and the sample portfolio is synthetic. It is built to make the modelling chain transparent and testable.'),
    ('What data do I need?', 'A CSV with an ID, latitude, longitude, construction type and insured value per property. A template is provided, '
     'and common spellings and Excel formats are handled. You can also describe a portfolio in words.'),
    ('Can I use real client data?', 'Not in this prototype. It accepts synthetic or test portfolios only.'),
    ('Does it include reinsurance?', 'It gives gross loss and, optionally, insured loss after simple per-property deductibles and limits. '
     'Treaties and layers are out of scope.'),
    ('How is AI used?', 'To read portfolio descriptions and flood reports. Every AI output is re-checked by deterministic code, shown to you for '
     'review, and measured against held-out tests.'),
]
for q, a in faq:
    with st.expander(q): st.write(a)

# Final CTA ----------------------------------------------------------------------------------------
site.band('See your flood exposure in minutes', 'Run the sample, upload your own test portfolio, or describe one in a sentence.')
st.space('small')
_, mid, _ = st.columns([1, 2, 1])
with mid: site.cta_row(key='footer_cta')
site.footer()
