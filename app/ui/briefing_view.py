"""AI briefing panel (draft, figure check, facts used)."""
import streamlit as st
from . import state

def briefing_panel():
    current = state.current_briefing()
    top = st.container(horizontal=True, vertical_alignment='center')
    if state.ai_enabled('extraction'):
        if top.button('Draft briefing' if not current else 'Redraft', icon=':material/auto_awesome:', type='primary' if not current else 'secondary'):
            with st.spinner('Drafting from the model output…'): state.draft_briefing()
            current = state.current_briefing()
    else:
        top.caption('AI unavailable on this server or for your organisation.')
    if not current: return
    b = current['briefing']
    if b['unsupported_figures']: top.badge(f"{len(b['unsupported_figures'])} unsupported figure(s)", color='orange', icon=':material/report:')
    else: top.badge('All figures match the model', color='green', icon=':material/fact_check:')
    st.markdown(f"**{b['headline']}**")
    for section in b['sections']:
        with st.expander(section['heading']):
            for paragraph in section['paragraphs']: st.write(paragraph)
    if b['checks']:
        with st.expander('Before relying on this result', expanded=True):
            for c in b['checks']: st.markdown(f'- {c}')
    if b['unsupported_figures']: st.warning('Not in the model output: ' + ', '.join(b['unsupported_figures']))
    from floodcat.ai.briefing import to_markdown
    with st.container(horizontal=True):
        st.download_button('Download', to_markdown(b), 'xpat_briefing.md', 'text/markdown', icon=':material/download:')
        with st.popover(f"{len(current['facts'])} facts used", icon=':material/list:'):
            for f in current['facts']: st.markdown(f"- {f['text']} · *{f['provenance']}*")
    st.caption(f"AI-written by {b['model']}; the figures come from the model.")
