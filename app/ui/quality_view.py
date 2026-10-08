"""Before a schedule is run: data-quality flags with fixes the user accepts (exposure/quality.py, ai/quality.py) and
storeys filled from Open Buildings heights (exposure/buildings.py). Both return new rows; nothing changes without a tick."""
import hashlib
import json
import pandas as pd
import streamlit as st
from floodcat.core.errors import ModelError
from . import state
from .components import badges

CODE_LABEL = {'duplicate_id': 'Duplicate ID', 'swapped_coordinates': 'Swapped coordinates', 'outside_coverage': 'Outside the hazard maps',
              'duplicate_record': 'Same building twice?', 'tiv_about_10x': 'Value ≈ 10× area × cost', 'tiv_units': 'Value in the wrong units?',
              'cost_outlier': 'Unusual cost per m²', 'zero_value': 'Zero value'}

def _digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()[:16]

def _quality(rows, key):
    from floodcat.exposure.quality import apply_fixes, review, summarise
    flags = review(rows, state.runtime().class_defaults, state.config())
    if not flags: return rows
    groups = summarise(flags)
    fixable = sum(1 for f in flags if f['fix'])
    with st.expander(f"Schedule check · {len(flags)} point(s) to look at, {fixable} with a proposed fix", icon=':material/rule:'):
        badges('ASSUMPTION', 'AI')
        st.caption('Fixed checks find likely data errors and propose mechanical fixes. Nothing changes until you tick a fix; fixed rows go through '
                   'the same validation as any upload and keep a note of what changed.')
        held = st.session_state.get(f'{key}_qexplain')
        explanations = held[1]['explanations'] if held and held[0] == _digest(groups) else {}
        for g in groups:
            text = f"**{CODE_LABEL.get(g['code'], g['code'])}** — {g['count']} row(s). e.g. {g['examples'][0]}"
            e = explanations.get(g['code'])
            if e: text += f"  \n:blue[AI: {e['why_it_matters']} Ask: {e['question']}]" + (f" :orange[(not in the flags: {', '.join(e['unsupported_figures'])})]" if e['unsupported_figures'] else '')
            (st.error if g['severity'] == 'error' else st.warning)(text, icon=':material/flag:')
        if state.ai_enabled('extraction') and st.button('Explain these with AI', key=f'{key}_qai', icon=':material/auto_awesome:'):
            from floodcat.ai.quality import explain
            if state.ai_quota():
                try:
                    out = explain(groups, state.runtime().llm())
                    state.audit_ai('ai.quality_explained', 'upload', _digest(rows), {'model': out['model'], 'groups': len(groups)})
                    st.session_state[f'{key}_qexplain'] = (_digest(groups), out); st.rerun()
                except ModelError as exc:
                    st.error(str(exc), icon=':material/error:')
        if not fixable: return rows
        frame = pd.DataFrame([{'Accept': False, 'Row': f['row']+1, 'ID': f['loc_id'], 'Problem': CODE_LABEL.get(f['code'], f['code']), 'Detail': f['message'],
                               'Proposed fix': ('drop this row' if f['fix']['action'] == 'drop' else 'swap lat and lon' if f['fix']['action'] == 'swap'
                                                else f"set {f['fix']['field']} to {f['fix']['value']}"), '_i': i}
                              for i, f in enumerate(flags) if f['fix']])
        select_all = st.checkbox('Tick every proposed fix', key=f'{key}_qall')
        if select_all: frame['Accept'] = True
        edited = st.data_editor(frame, hide_index=True, width='stretch', key=f'{key}_qedit_{select_all}', disabled=['Row', 'ID', 'Problem', 'Detail', 'Proposed fix'],
                                column_config={'_i': None, 'Detail': st.column_config.TextColumn(width='large')})
        accepted = [int(r['_i']) for r in edited.to_dict('records') if r['Accept']]
        if accepted: st.success(f'{len(accepted)} fix(es) will be applied to the rows you run.', icon=':material/check:')
        return apply_fixes(rows, flags, accepted)

def _storeys(rows, key):
    if not any(str(r.get('floors_above_ground') or '').strip() == '' for r in rows): return rows
    with st.expander('Fill missing storey counts from building heights (Open Buildings, AI)', icon=':material/apartment:'):
        badges('AI', 'ASSUMPTION')
        st.caption('Upload a building-height GeoTIFF exported with scripts/gee_open_buildings_height.js (Open Buildings 2.5D Temporal; heights come from '
                   f"Google's machine-learning model, no published accuracy). Storeys = height ÷ {state.config().building_attributes['storey_height_m']:g} m "
                   '(ASSUMPTION). Only blank storey counts are proposed; housing class is never changed. With storeys known, only the ground storey '
                   'and basements are treated as flood-exposed.')
        file = st.file_uploader('Building-height GeoTIFF', type=['tif', 'tiff'], key=f'{key}_heights')
        if file is None: return rows
        data = file.getvalue(); digest = hashlib.sha256(data).hexdigest()
        if not state.screen_upload(data, digest): return rows
        from floodcat.exposure.buildings import HeightRaster, apply_floors, propose_floors
        try:
            proposals = propose_floors(rows, HeightRaster.read(data), state.config())
        except ModelError as exc:
            st.error(str(exc), icon=':material/error:'); return rows
        usable = [p for p in proposals if p['status'] == 'proposed']
        st.caption(f"{len(usable)} storey count(s) proposed · {sum(p['status'] == 'no_building' for p in proposals)} point(s) with no building detected "
                   f"(check their coordinates) · {sum(p['status'] == 'no_data' for p in proposals)} outside the height map")
        if not proposals: return rows
        frame = pd.DataFrame([{'Accept': False, 'ID': p['loc_id'], 'Height (m)': p['height_m'], 'Storeys': p['floors'], 'Why': p['reason'], '_row': p['row']}
                              for p in proposals])
        edited = st.data_editor(frame, hide_index=True, width='stretch', key=f'{key}_hedit', disabled=['ID', 'Height (m)', 'Storeys', 'Why'],
                                column_config={'_row': None, 'Why': st.column_config.TextColumn(width='large')})
        accepted = [int(r['_row']) for r in edited.to_dict('records') if r['Accept']]  # apply_floors ignores rows with no proposal
        return apply_floors(rows, proposals, accepted)

def improve_rows(rows, key):
    """Show the checks and return the rows with the user's accepted changes (or the rows unchanged)."""
    try:
        rows = _quality(rows, key)
    except ModelError as exc:
        st.caption(f'Schedule check skipped: {exc}')
    return _storeys(rows, key)
