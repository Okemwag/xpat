import hashlib
import secrets
import pandas as pd
import streamlit as st
from floodcat.core.constants import CLASSES
from floodcat.core.errors import ModelError, ReviewRequired
from floodcat.exposure.validation import apply_declarations, validate_rows
from ui import state
from ui.components import badges, issues_panel, page_header

TEMPLATE = ('loc_id,lat,lon,housing_class,floor_area_m2,cost_per_m2_kes,tiv_kes,synthetic,source\n'
            'P-001,-1.2576,36.8962,semi_permanent,33,10000,3300000,True,my test portfolio\n'
            'P-002,-1.3113,36.7890,informal_iron_sheet,12,8000,96000,True,my test portfolio\n'
            'P-003,-1.2630,36.8106,concrete_rcc,400,60000,24000000,True,my test portfolio\n')
EXAMPLES = [
    '20 iron-sheet houses in Mathare, about 300,000 shillings each. A three-storey concrete block of flats in Kileleshwa insured for 45 million.',
    'Five semi-permanent shops along Outer Ring Road in Donholm, roughly 40 square metres each. Twelve masonry homes in Kibera worth 1.2m each.',
]

page_header('Portfolio', 'Load the properties to model. Every source goes through the same validation before any loss is calculated.', ('SYNTHETIC',))

def run_and_go(rows, label, settings):
    with st.spinner('Running hazard → vulnerability → loss…'):
        report, error = state.execute(rows, label, settings=settings)
    if error is None:
        st.session_state.pop('pending', None); st.session_state.pop('ai_draft', None)
        st.toast(f"{report['modelled_count']} properties modelled", icon=':material/check_circle:')
        st.switch_page('views/overview.py')
    if isinstance(error, ReviewRequired):
        st.session_state['review_error'] = {'issues': error.issues, 'accepted': error.accepted_count}
    else:
        st.error(f'{error}', icon=':material/error:')

def preview_map(assets):
    if assets:
        st.map(pd.DataFrame({'lat': [a.lat for a in assets], 'lon': [a.lon for a in assets]}), size=40, color='#2a78d6', height=280)

def review_and_run(rows, label_default, source_kind, key):
    """Shared review step: declarations, validation summary, preview, explicit partial run."""
    columns = set().union(*(r.keys() for r in rows))
    missing_label = not {'synthetic', 'source'} <= columns or any(r.get('synthetic') in (None, '') for r in rows)
    missing_ids = 'loc_id' not in columns or any(r.get('loc_id') in (None, '') for r in rows)
    with st.container(border=True):
        st.markdown('**Before running**')
        declare = st.checkbox('I confirm this portfolio is synthetic or test data, not real client data', value=False, key=f'{key}_declare',
                              disabled=not missing_label, help='Required when the file has no synthetic/source columns. Real portfolios are out of scope.')
        assign = st.checkbox('Give records without an ID a generated one (UPL-<row>)', value=False, key=f'{key}_ids', disabled=not missing_ids)
        label = st.text_input('Name this run', value=label_default, max_chars=80, key=f'{key}_label')
    prepared, _ = apply_declarations(rows, declare, f'{source_kind}; declared synthetic by {state.user()["display_name"]}', assign)
    try:
        assets, issues = validate_rows(prepared)
    except ModelError as exc:
        st.error(str(exc), icon=':material/error:')
        return
    a, b, c = st.columns(3)
    a.metric('Records', len(rows)); b.metric('Valid', len(assets)); c.metric('Insured value (valid)', state.kes(sum(x.tiv_kes for x in assets)))
    issues_panel(issues, expanded=True)
    preview_map(assets)
    errors = any(i['severity'] == 'error' for i in issues)
    review = st.session_state.get('review_error')
    partial = False
    if errors or review:
        if review:
            st.error('Some valid records could not be given a hazard value:', icon=':material/error:')
            issues_panel([i for i in review['issues'] if i['severity'] == 'error'])
        partial = st.checkbox(f'Run on the valid records only and report the rest as excluded', key=f'{key}_partial')
    disabled = not assets or (bool(errors or review) and not partial)
    if st.button('Run analysis', type='primary', icon=':material/play_arrow:', disabled=disabled, key=f'{key}_run'):
        st.session_state.pop('review_error', None)
        run_and_go(rows, label or label_default, {'declare_synthetic': declare, 'assign_missing_ids': assign, 'allow_partial': partial,
                                                  'source_label': f'{source_kind}; declared synthetic by {state.user()["display_name"]}'})

upload, describe, sample = st.tabs([':material/upload_file: Upload a CSV', ':material/edit_note: Describe in words (AI)', ':material/dataset: Sample portfolio'])

with upload:
    left, right = st.columns([3, 2], gap='large')
    with right:
        with st.container(border=True):
            st.markdown('**File format**')
            st.markdown('Required: `loc_id`, `lat`, `lon`, `housing_class`, `tiv_kes`, `synthetic`, `source`.  \n'
                        'Optional: `floor_area_m2`, `cost_per_m2_kes`, `hazard_score_<tier>` (checked against the maps).  \n'
                        f"Classes: {', '.join(f'`{c}`' for c in CLASSES)} (common spellings like *concrete* or *mabati* are accepted and reported).  \n"
                        'Values like `1,250,000`, `KES 2.5m` or `300k` are fine. Comma, semicolon or tab separated; up to 10,000 rows / 10 MB.')
            st.download_button('Download template', TEMPLATE, 'xpat_portfolio_template.csv', 'text/csv', icon=':material/download:')
    with left:
        file = st.file_uploader('Portfolio CSV', type=['csv', 'txt'], help='Up to 10 MB')
        if file is not None:
            data = file.getvalue()
            digest = hashlib.sha256(data).hexdigest()
            if st.session_state.get('pending', {}).get('digest') != digest:
                st.session_state.pop('review_error', None)
                try:
                    st.session_state['pending'] = {'digest': digest, 'name': file.name, 'rows': state.runtime().parse_upload(data)}
                except ModelError as exc:
                    st.session_state.pop('pending', None)
                    st.error(f'Could not read {file.name}: {exc}', icon=':material/error:')
            pending = st.session_state.get('pending')
            if pending and pending['digest'] == digest:
                st.caption(f"{pending['name']} · {len(pending['rows'])} rows · columns: {', '.join(sorted(set().union(*(r.keys() for r in pending['rows']))))}")
                review_and_run(pending['rows'], pending['name'].rsplit('.', 1)[0], f"uploaded file {pending['name']}", 'upload')

with describe:
    badges('AI', 'ASSUMPTION')
    if not state.ai_available():
        st.warning('AI is not configured on this server (set GEMINI_API_KEY). Use the CSV upload or the sample portfolio instead.', icon=':material/key_off:')
    st.write('Describe buildings as you would to a colleague. Gemini turns your words into records; OpenStreetMap locates the places; '
             'anything you did not say is filled from a stated assumption and marked. You review every row before it is modelled.')
    ex = st.pills('Examples', ['Example 1', 'Example 2'], key='example_pick')
    default_text = EXAMPLES[int(ex[-1])-1] if ex else st.session_state.get('describe_text', '')
    text = st.text_area('Portfolio description', value=default_text, height=140, max_chars=8000,
                        placeholder='e.g. 15 masonry homes in Kayole worth about 2 million each…')
    st.session_state['describe_text'] = text
    if st.button('Turn into records', type='primary', icon=':material/auto_awesome:', disabled=not state.ai_available() or not text.strip()):
        from floodcat.ai.ingestion import ingest
        try:
            with st.spinner('Gemini is reading the description; locating places…'):
                rt = state.runtime()
                draft = ingest(text, rt.llm(), rt.gazetteer(), rt.class_defaults, batch_id='AI'+secrets.token_hex(2).upper())
            st.session_state['ai_draft'] = draft; st.session_state.pop('review_error', None)
        except ModelError as exc:
            st.error(str(exc), icon=':material/error:')
    draft = st.session_state.get('ai_draft')
    if draft:
        st.subheader('What the AI understood')
        st.caption(f"Model: {draft['model']} · prompt {draft['prompt_version']} · {len(draft['rows'])} records from {len(draft['groups'])} group(s)")
        for g in draft['groups']:
            with st.container(border=True):
                st.markdown(f"**Group {g['group']}: {g['count']} × {state.class_label(g['housing_class'])} in {g['location_name'] or '?'}** — "
                            f"value each: {state.kes(g['tiv_kes_each'], compact=False) if g['tiv_kes_each'] != '—' else '—'}")
                st.markdown(f"> {g['source_quote']}" + ('' if g['quote_verified'] else '  \n:orange[quote not found in your text]'))
                st.caption(g['field_provenance'] or 'no fields extracted')
                for flag in g['flags']: st.warning(flag, icon=':material/flag:')
        if draft['unparsed']:
            with st.expander('Sentences the AI could not use'):
                for u in draft['unparsed']: st.write(f'- {u}')
        st.markdown('**Edit records** — fix anything flagged; changes here override the AI.')
        frame = pd.DataFrame(draft['rows'])
        edited = st.data_editor(frame, hide_index=True, width='stretch', num_rows='dynamic', key='ai_editor',
                                column_config={'housing_class': st.column_config.SelectboxColumn('housing_class', options=list(CLASSES)),
                                               'source': None, 'synthetic': None, 'ai_group': None,
                                               'ai_field_provenance': st.column_config.TextColumn('provenance', disabled=True)})
        rows = [{k: ('' if pd.isna(v) else str(v)) for k, v in r.items()} for r in edited.to_dict('records')]
        for r in rows:
            r.setdefault('synthetic', 'True'); r['synthetic'] = r.get('synthetic') or 'True'
            r['source'] = r.get('source') or draft['rows'][0]['source']
        review_and_run(rows, 'Described portfolio', 'AI-ingested description', 'ai')

with sample:
    badges('SYNTHETIC', 'PROXY')
    st.write('600 synthetic Nairobi properties supplied with the hackathon starter kit, across four construction classes '
             '(KES 63.64 bn insured). Their insured values are about 10× floor area × cost per m² — the cause is unconfirmed, '
             'so the supplied values are used as they are and the gap is flagged.')
    if st.button('Run the sample portfolio', type='primary', icon=':material/play_arrow:'):
        run_and_go(state.runtime().sample_rows(), 'Starter kit sample (600 synthetic)', {})
    st.download_button('Download the sample CSV', state.runtime().sample_path.read_bytes(), 'exposure_nairobi_with_hazard.csv', 'text/csv',
                       icon=':material/download:')
