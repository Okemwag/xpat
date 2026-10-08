"""Broker submission documents (PDF/DOCX/text) → reviewed exposure rows, shown inside the Portfolio upload."""
import hashlib
import pandas as pd
import streamlit as st
from floodcat.core.constants import CLASSES, TIERS
from floodcat.core.errors import ModelError
from . import state
from .components import badges

SEVERITY = {'error': (':material/error:', 'red'), 'warning': (':material/warning:', 'orange'), 'info': (':material/info:', 'blue')}

def _show_checks(checks):
    for sev in ('error', 'warning', 'info'):
        for c in [c for c in checks if c['severity'] == sev]:
            icon, _ = SEVERITY[sev]
            box = {'error': st.error, 'warning': st.warning, 'info': st.info}[sev]
            box(c['message'] + (f"\n\n> {c['quote'][:300]}" if c['quote'] else ''), icon=icon)

def _field_table(fields):
    labels = {'housing_class': 'Construction class', 'construction': 'Construction (as written)', 'tiv_kes': 'Insured value (KES)',
              'floors_above_ground': 'Storeys above ground', 'basement_levels': 'Basement levels', 'gross_floor_area_m2': 'Gross floor area (m²)',
              'coordinates': 'Coordinates (lat, lon)', 'floor_area_components_total': 'Sum of listed floor areas (m²)',
              'flood_deductible': 'Flood deductible', 'flood_limit_kes': 'Flood limit (KES)'}
    def fmt(key, value):
        if value is None: return '—'
        if key == 'flood_deductible':
            return f"{value['percent']:.0%} of {value.get('basis') or '?'}" + (f", minimum KES {value['minimum_kes']:,.0f}" if value.get('minimum_kes') else '')
        if key == 'housing_class': return state.class_label(value)
        if isinstance(value, float) and key.endswith(('_kes', '_m2', 'total')): return f'{value:,.0f}'
        return str(value)
    rows = [{'Field': labels.get(k, k), 'Value': fmt(k, f['value']),
             'Checked against document': {True: '✓ quote found', False: '⚠ not found — check', None: 'computed' if k.endswith('total') else '—'}[f['verified']],
             'Source quote': f['quote'][:160]} for k, f in fields.items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')

def submission_flow(data, filename, review_and_run):
    """Read a document, ask consent, extract with Gemini, show checks, then hand rows to the shared review step."""
    badges('AI', 'ASSUMPTION')
    digest = hashlib.sha256(data).hexdigest()
    cached = st.session_state.get('doc', {})
    if cached.get('digest') != digest or cached.get('filename') != filename:
        st.session_state.pop('submission', None)
        from floodcat.ai.documents import read_document
        try:
            st.session_state['doc'] = {'digest': digest, **read_document(data, filename)}
        except ModelError as exc:
            st.session_state.pop('doc', None); st.error(str(exc), icon=':material/error:'); return
    doc = st.session_state['doc']
    removed = doc.get('redacted', {})
    st.markdown(f"**Document:** {doc['filename']} · read as {doc['kind'].upper()}" + (f" · {doc['pages']} pages" if doc['pages'] else '')
                + f" · {doc['chars']:,} characters" + (f" · the name says {doc['filename'].rsplit('.', 1)[-1].upper()} but the file is a {doc['kind'].upper()} — read correctly, no action needed"
                   if doc['name_mismatch'] else ''))
    st.caption(f"Removed before any AI sees it: {removed.get('emails', 0)} e-mail address(es) and {removed.get('phones', 0)} phone number(s). "
               'The original file is not stored; only the extracted property values and their source quotes are kept with the run.')
    with st.expander('Text that will be sent to the AI'):
        st.text(doc['text'][:6000] + ('\n…' if len(doc['text']) > 6000 else ''))
    if not state.ai_enabled('extraction'):
        st.warning('Documents cannot be read here: AI is not configured on this server, or your organisation has turned it off. '
                   'Upload a CSV or Excel schedule instead.', icon=':material/key_off:')
        return
    where = 'the local AI model' if state.ai_local(client_data=True) else 'Google Gemini'
    consent = st.checkbox(f'Send the text above to {where} ({state.ai_name(client_data=True)}) to extract the property details', key=f'consent_{digest[:8]}',
                          help='Contact details are removed first. Names of people and companies may remain.'
                               + (" The model runs on this organisation's own server; the text does not leave it." if state.ai_local(client_data=True) else ''))
    if st.button('Extract properties with AI', type='primary', icon=':material/auto_awesome:', disabled=not consent, key='doc_extract'):
        from floodcat.ai.submission import extract_submission
        rt = state.runtime()
        if not state.ai_quota(): return
        try:
            with st.spinner(f'{state.ai_name(client_data=True)} is reading the document; checking it against the map and the model…'):
                st.session_state['submission'] = extract_submission(doc, (client := state.llm(client_data=True)), rt.gazetteer(llm=client), rt.hazard, rt.hotspots, state.config(), rt.class_defaults)
            from floodcat.platform import data
            extraction_id = state.guarded(data.save_extraction, doc, st.session_state['submission'], consent)
            if extraction_id is not state.FAILED: st.session_state['pending_extraction'] = {'id': extraction_id, 'decisions': {}}
        except ModelError as exc:
            st.error(str(exc), icon=':material/error:')
    sub = st.session_state.get('submission')
    if not sub: return
    from floodcat.ai.submission import to_exposure_row
    st.caption(f"Model {sub['model']} · prompt {sub['prompt_version']} · {len(sub['properties'])} propert{'y' if len(sub['properties']) == 1 else 'ies'} found")
    rows, apply_terms = [], False
    for i, prop in enumerate(sub['properties']):
        with st.container(border=True):
            counts = {s: sum(c['severity'] == s for c in prop['checks']) for s in ('error', 'warning', 'info')}
            st.subheader(prop['name'])
            st.caption(f"{counts['error']} to fix · {counts['warning']} to review · {counts['info']} notes")
            _field_table(prop['fields'])
            st.markdown('**Checks**')
            _show_checks(prop['checks'])
            if prop['landmarks']:
                with st.expander('Landmark claims checked against OpenStreetMap'):
                    st.dataframe(pd.DataFrame([{'Landmark': l['name'], 'Document says': f"{l['claimed'] if l['claimed'] is not None else '?'} km {l.get('direction') or ''}",
                                                'Map says': f"{l['actual_km']} km {l['actual_direction']}" if 'actual_km' in l else '—', 'Result': l['status']}
                                               for l in prop['landmarks']]), hide_index=True, width='stretch')
            if prop['flood_claims']:
                with st.expander("The document's flood-risk claims vs the model"):
                    primary = prop['hazard'][0] if prop['hazard'] else None
                    if primary and primary['scores'] is not None:
                        st.markdown('**Model view at the chosen location:** ' + ', '.join(f"{t} {primary['scores'][t]:.2f}" for t in TIERS)
                                    + (f" · nearest named hotspot {primary['nearest_hotspot']['nearest_hotspot']} "
                                       f"({primary['nearest_hotspot']['hotspot_distance_m']/1000:.1f} km)" if primary.get('nearest_hotspot') else ''))
                    for c in prop['flood_claims']:
                        st.markdown(f"- “{c['claim']}”" + ('' if c['verified'] else ' :orange[(quote not found)]'))
                    st.caption('These are the broker\'s statements. The hazard map is blind to drainage-driven flooding, so a low score does not confirm them.')
            st.markdown('**Before running**')
            options = prop['hazard'] or []
            labels = [f"{o['source']}: {o['lat']:.5f}, {o['lon']:.5f}" + ('' if o['scores'] is None else f" (common-tier score {o['scores']['common']:.2f})") for o in options]
            choice = st.radio('Location to model', list(range(len(options))) + ['manual'], key=f'loc_{i}',
                              format_func=lambda k: labels[k] if k != 'manual' else 'Enter coordinates')
            location = options[choice] if choice != 'manual' else None
            if choice == 'manual':
                a, b = st.columns(2)
                location = {'lat': a.number_input('Latitude', -1.45, -1.10, -1.29, 0.0001, format='%.5f', key=f'lat_{i}'),
                            'lon': b.number_input('Longitude', 36.60, 36.9997, 36.82, 0.0001, format='%.5f', key=f'lon_{i}')}
            basis = None
            if prop['row']['deductible']:
                current = prop['row']['deductible'].get('basis') or 'loss'
                basis = st.radio('Flood deductible percentage is of', ['loss', 'value'], index=0 if current == 'loss' else 1, horizontal=True, key=f'ded_{i}',
                                 format_func={'loss': 'each loss (minimum applies)', 'value': 'the insured value'}.get)
            row = to_exposure_row(prop, location, sub['filename'], sub['model'], deductible_basis=basis, loc_id=f'DOC-{i+1:02d}-' + prop['name'].upper()[:20].replace(' ', '-'))
            if not row['housing_class']:
                row['housing_class'] = st.selectbox('Construction class', CLASSES, format_func=state.class_label, key=f'cls_{i}')
            if not row['tiv_kes']:
                value = st.number_input('Insured value (KES)', min_value=0.0, step=1e6, key=f'tiv_{i}')
                row['tiv_kes'] = f'{value:.2f}' if value else ''
            if row.get('floors_above_ground'):
                from floodcat.financial.loss import exposed_fraction
                from floodcat.exposure.validation import parse_row
                try:
                    share = exposed_fraction(parse_row({**row, 'synthetic': 'False'})[0], state.config())
                    st.caption(f"Flood-exposed share of value: {share:.0%} — basements plus the lowest "
                               f"{state.config().storey_exposure['flooded_storeys_above_ground']} storey(s) of {row['floors_above_ground']} (ASSUMPTION).")
                except ModelError:
                    pass
            if row.get('deductible_kes') or row.get('limit_kes') or row.get('deductible_pct_of_loss'):
                apply_terms = True
            rows.append(row)
            if st.session_state.get('pending_extraction'):
                st.session_state['pending_extraction']['decisions'][prop['name']] = {
                    'location': (location or {}).get('source', 'manual'), 'lat': (location or {}).get('lat'), 'lon': (location or {}).get('lon'),
                    'deductible_basis': basis, 'housing_class': row['housing_class']}
    terms = False
    if apply_terms:
        terms = st.checkbox("Apply the document's flood deductible and limit (adds an insured loss next to the gross loss)", value=True, key='doc_terms')
    review = {'label': None, 'properties': sub['properties'], 'filename': sub['filename'], 'model': sub['model']}
    if terms:
        overrides = dict(st.session_state.get('config_overrides') or {})
        overrides['policy_terms'] = {'enabled': True, 'deductible_pct_of_tiv': 0.0, 'limit_pct_of_tiv': 1.0}
        st.session_state['config_overrides'] = overrides
    elif st.session_state.get('config_overrides', {}).get('policy_terms', {}).get('enabled') and apply_terms:
        overrides = dict(st.session_state['config_overrides']); overrides.pop('policy_terms'); st.session_state['config_overrides'] = overrides
    label = f"Submission: {sub['properties'][0]['name']}" if len(sub['properties']) == 1 else f"Submission: {sub['filename']}"
    review['label'] = label
    st.session_state['submission_review'] = review
    review_and_run(rows, label, f"submission document {sub['filename']}", 'doc')
