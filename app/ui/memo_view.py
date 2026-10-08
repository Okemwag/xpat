"""Referral and quote memo drafting on the Underwriting decision page (ai/memo.py)."""
import streamlit as st
from floodcat.core.errors import ModelError
from . import state

KIND_LABEL = {'referral': 'Referral to head of underwriting', 'quote': 'Quote letter to the broker'}

def memo_panel(rec, report, key):
    if not state.ai_enabled('extraction'):
        st.caption('AI is unavailable on this server or for your organisation.'); return
    with st.form('memo_form', border=False):
        kind = st.segmented_control('Draft', list(KIND_LABEL), default='referral', format_func=KIND_LABEL.get) or 'referral'
        note = st.text_area('Your context (optional)', max_chars=1000, placeholder='e.g. Broker says the buildings were re-surveyed in 2025.',
                            help='Treated as background only: figures must still come from the rules and the model. Contact details are removed.')
        go = st.form_submit_button('Draft', icon=':material/edit_note:', type='primary')
    if go:
        from floodcat.ai.memo import draft
        if state.ai_quota():
            try:
                with st.spinner('Drafting from the recommendation and model facts…'):
                    memo = draft(rec, state.runtime().llm(), kind, report, note)
                state.audit_ai('ai.memo_drafted', 'run', report['analysis_id'],
                               {'model': memo['model'], 'prompt_version': memo['prompt_version'], 'kind': kind, 'outcome': rec['outcome'],
                                'unsupported_figures': memo['unsupported_figures']})
                st.session_state['uw_memo'] = (key, memo)
            except ModelError as exc:
                st.error(str(exc), icon=':material/error:')
    held = st.session_state.get('uw_memo')
    if not held or held[0] != key: return
    from floodcat.ai.memo import to_docx, to_markdown
    memo = held[1]
    if memo['unsupported_figures']:
        st.warning('Not in the rule or model facts: ' + ', '.join(memo['unsupported_figures']) + ' — correct these before sending.', icon=':material/report:')
    text = st.text_area('Edit before sending', to_markdown(memo), height=320, key=f'memo_text_{memo["kind"]}')
    with st.container(horizontal=True):
        st.download_button('Download (Markdown)', text, f"xpat_{memo['kind']}.md", 'text/markdown', icon=':material/download:')
        st.download_button('Download (Word, as drafted)', to_docx(memo), f"xpat_{memo['kind']}.docx",
                           'application/vnd.openxmlformats-officedocument.wordprocessingml.document', icon=':material/description:')
    st.caption(f"AI-drafted by {memo['model']}. It cannot change the recommendation ({memo['outcome']}); you edit, send and record the decision.")
