"""Ask the results: a question box answered only from the run's fact pack (ai/ask.py)."""
import streamlit as st
from floodcat.core.errors import ModelError
from . import state
from .components import LABELS

CHART_PAGES = {'loss_curve': ('views/results.py', 'Loss curve'), 'map': ('views/map.py', 'Accumulation map'),
               'property_explorer': ('views/property.py', 'Property explorer'), 'assumptions': ('views/assumptions.py', 'Assumptions'),
               'data_and_honesty': ('views/honesty.py', 'Data & honesty'), 'method': ('views/method.py', 'How the model works')}
SUGGESTIONS = ['What drives the 1-in-100 loss?', 'Why is the common tier the rarest event?', 'How far can I trust these numbers?',
               'Which construction class loses most?']

def ask_panel(report, key='ask'):
    st.caption('Answers use only this run’s results and the model’s stated method. Every figure is checked; the facts used are listed.')
    if not state.ai_enabled('extraction'):
        st.caption('AI is unavailable on this server or for your organisation.'); return
    pick = st.pills('Try', SUGGESTIONS, key=f'{key}_pick')
    with st.form(f'{key}_form', border=False):
        question = st.text_input('Your question', value=pick or '', max_chars=500, placeholder='e.g. Where does most of the loss come from?')
        asked = st.form_submit_button('Ask', icon=':material/auto_awesome:', type='primary')
    if asked and question.strip():
        from floodcat.ai.ask import ask, method_facts
        if state.ai_quota():
            try:
                with st.spinner('Answering from the model results…'):
                    answer = ask(question, state.briefing_facts(report) + method_facts(state.config()), state.runtime().llm())
                state.audit_ai('ai.question_answered', 'run', report['analysis_id'],
                               {'model': answer['model'], 'prompt_version': answer['prompt_version'], 'answerable': answer['answerable'],
                                'facts_used': len(answer['facts_used']), 'unsupported_figures': answer['unsupported_figures']})
                st.session_state[f'{key}_answer'] = (report['analysis_id'], answer)
            except ModelError as exc:
                st.error(str(exc), icon=':material/error:')
    held = st.session_state.get(f'{key}_answer')
    if not held or held[0] != report['analysis_id']: return
    answer = held[1]
    with st.container(border=True):
        st.markdown(f"**Q:** {answer['question']}")
        if not answer['answerable']: st.info(answer['answer'] or 'The model results do not cover this question.', icon=':material/help:')
        else: st.write(answer['answer'])
        row = st.container(horizontal=True, gap='small', vertical_alignment='center')
        for label in answer['provenance']:
            if label in LABELS: row.badge(label, color=LABELS[label][0], help=LABELS[label][1])
        if answer['unsupported_figures']: row.badge(f"not in the results: {', '.join(answer['unsupported_figures'])}", color='orange', icon=':material/report:')
        elif answer['answerable']: row.badge('figures match the results', color='green', icon=':material/fact_check:')
        if answer['facts_used']:
            with row.popover(f"{len(answer['facts_used'])} fact(s) used", icon=':material/list:'):
                for f in answer['facts_used']: st.markdown(f"- {f['text']} · *{f['provenance']}*")
        if answer['chart'] in CHART_PAGES:
            page, title = CHART_PAGES[answer['chart']]
            try: st.page_link(page, label=f'See it on: {title}', icon=':material/arrow_forward:')
            except Exception: st.caption(f'See it on: {title}')
        st.caption(f"AI-written by {answer['model']} from the model output; it cannot change any number.")
