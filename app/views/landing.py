import streamlit as st
from ui import state

@st.cache_data(show_spinner=False)
def sample_headline():
    report = state.runtime().run(state.runtime().sample_rows())
    curve = {p['return_period_years']: p for p in report['runs']['baseline']['ep_curve']}
    return {'tiv': report['modelled_tiv_kes'], 'count': report['modelled_count'], 'rp100': curve[100.0]['loss_kes'],
            'pct100': curve[100.0]['loss_pct_of_tiv'], 'aal': report['runs']['baseline']['aal']['aal_kes']}

left, right = st.columns([3, 2], gap='large', vertical_alignment='center')
with left:
    st.markdown('# What could a Nairobi flood cost your portfolio?')
    st.markdown('#### Xpat turns flood information into an explainable loss estimate — by property, by place, and by how rare the flood is.')
    st.write('Upload a portfolio, or describe it in plain English, and see the loss you should budget for at the '
             '1-in-100 and 1-in-250 year level, where that loss is concentrated, and exactly which assumptions drive it.')
    row = st.container(horizontal=True)
    if row.button('Create an account', type='primary', icon=':material/person_add:'):
        st.session_state['auth_tab'] = 'register'; st.switch_page('views/auth.py')
    if row.button('Sign in', icon=':material/login:'):
        st.session_state['auth_tab'] = 'signin'; st.switch_page('views/auth.py')
    if state.guest_allowed() and row.button('Explore as guest', icon=':material/visibility:', help='Judges: no account needed. Sessions are temporary.'):
        state.sign_in_guest(); st.rerun()
with right:
    with st.container(border=True):
        st.caption('LIVE · SAMPLE PORTFOLIO (SYNTHETIC)')
        try:
            h = sample_headline()
            st.metric('Insured value', state.kes(h['tiv']), help=f"{h['count']} synthetic Nairobi properties")
            a, b = st.columns(2)
            a.metric('1-in-100 loss', state.kes(h['rp100']), help=f"{state.pct(h['pct100'])} of insured value")
            b.metric('Average annual loss', state.kes(h['aal']))
            st.caption('Computed just now by the same model you will use. Illustrative only.')
        except Exception as exc:  # landing must never crash
            st.warning(f'Live preview unavailable: {exc}')

st.divider()
st.subheader('How it works')
steps = st.columns(4)
for col, (icon, title, text) in zip(steps, [
    (':material/water:', '1 · Hazard', 'Five flood-severity maps of Nairobi (a terrain and river proxy) are read at every property.'),
    (':material/home:', '2 · Vulnerability', 'A published JRC depth-damage curve, adapted per construction type, turns severity into damage.'),
    (':material/apartment:', '3 · Exposure', 'Your properties, their construction and insured value — validated before anything is modelled.'),
    (':material/payments:', '4 · Loss', 'Damage × value per property, summed per flood rarity into a loss curve and average annual loss.')]):
    with col.container(border=True, height='stretch'):
        st.markdown(f'#### {icon} {title}'); st.write(text)

st.subheader('Where AI changes the answer')
a, b = st.columns(2)
with a.container(border=True, height='stretch'):
    st.markdown('#### :material/edit_note: Describe a portfolio in words')
    st.write('“20 iron-sheet houses in Mathare worth 300k each” becomes validated property records and a loss estimate. '
             'Every value shows whether it came from your words, a map lookup, or a stated assumption.')
with b.container(border=True, height='stretch'):
    st.markdown('#### :material/flood: Find the floods the map misses')
    st.write('The baseline map flags only 12 of 24 named flood areas — it cannot see blocked drains. AI reads flood reports, '
             'a reviewer approves each finding, and the model shows exactly which losses change.')

st.subheader('Built for')
cols = st.columns(3)
for col, (title, text) in zip(cols, [
    ('Underwriters & analysts', 'A defensible loss at the return period you budget for, in minutes.'),
    ('Portfolio managers', 'How much insured value sits where flooding is worst.'),
    ('Judges, counties & brokers', 'Every number labelled as real, proxy, synthetic, assumption or AI.')]):
    col.markdown(f'**{title}**  \n{text}')

with st.container(border=True):
    st.markdown('**Honest by design.** This is an uncalibrated prototype. The portfolio is synthetic, the hazard is a proxy and '
                'the return periods are assumptions. The app says so next to every number.')
    if st.button('Read how the model works', icon=':material/menu_book:'): st.switch_page('views/method.py')
