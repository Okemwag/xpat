"""Public risk notes (AI enhancement 8): a one-page flood note for a named area, in English and Kiswahili, from the hazard maps only."""
import streamlit as st
from floodcat.core.constants import TIERS
from floodcat.core.errors import ModelError
from floodcat.hazard.hotspots import hotspot_check
from ui import state
from ui.components import badges, explain, kpis, page_header

page_header('Public risk notes', 'A plain one-page flood note for a neighbourhood, in English and Kiswahili, for county and disaster-management teams. '
            'Built from the hazard maps only: no property, insurance or client data.')
badges('PROXY', 'REAL', 'AI')
rt = state.runtime(); cfg = state.config()
check = {p['name']: p for p in hotspot_check(rt.hotspots, rt.hazard)['points']}

with st.expander('What goes into a note, and what keeps it honest', icon=':material/help:'):
    st.markdown(f"""
- **Facts** — share of the ground within {cfg.public_notes['radius_m']/1000:g} km that each scenario flags (hazard maps, PROXY), whether the county lists the
  area and whether the map flags it (REAL / PROXY), and what the map cannot see. No money, no properties.
- **Writing** — the AI writes both languages from the same facts. Every number in each language is checked against the facts.
- **Review** — a note stays a **draft** until a named Kiswahili reader confirms the translation. Notes with unchecked figures cannot be confirmed.
""")

names = sorted(check)
place = st.selectbox('Named flood area (county list)', names, index=None, placeholder='Choose an area')
if place:
    h = next(x for x in rt.hotspots if x.name == place)
    from floodcat.ai.public_note import build_facts
    facts, profile = build_facts(place, h.lat, h.lon, rt.hazard, cfg, check[place])
    kpis([(f"Ground flagged, {state.rp_label(cfg.return_periods[TIERS[0]])}", f"{profile['flagged_pct'][TIERS[0]]}%"),
          (f"Ground flagged, {state.rp_label(cfg.return_periods[TIERS[-1]])}", f"{profile['flagged_pct'][TIERS[-1]]}%"),
          ('Map flags the area centre', 'yes' if check[place]['flagged_any_tier'] else 'no', 'Score above zero in any tier')])
    explain(f"Share of {profile['points']} points within {profile['radius_m']/1000:g} km of {place} (every {profile['spacing_m']:g} m) with a score above zero.",
            'Higher means more of the surrounding ground is flood-susceptible in that scenario. It is not a depth or a forecast.', ['PROXY', 'ASSUMPTION'])
    allowed = state.ai_enabled('public_note')
    if not allowed: st.caption('AI drafting is unavailable on this server or for your organisation (needs the full AI mode).')
    if st.button('Draft the note', type='primary', icon=':material/translate:', disabled=not allowed):
        from floodcat.ai.public_note import draft
        if state.ai_quota():
            try:
                with st.spinner('Writing in English and Kiswahili from the hazard facts…'):
                    note = draft(place, h.lat, h.lon, rt.hazard, cfg, state.llm(), check[place])
                state.audit_ai('ai.public_note_drafted', 'area', place, {'model': note['model'], 'prompt_version': note['prompt_version'],
                                                                        'unsupported_figures': note['unsupported_figures']})
                st.session_state['public_note'] = note
            except ModelError as exc:
                st.error(str(exc), icon=':material/error:')
    note = st.session_state.get('public_note')
    if note and note['place'] == place:
        from floodcat.ai.public_note import review, to_markdown
        left, right = st.columns(2, gap='large')
        for col, lang, title in ((left, 'english', 'English'), (right, 'kiswahili', 'Kiswahili')):
            with col.container(border=True, height='stretch'):
                st.markdown(f"**{title}** · {note[lang]['title']}")
                for p in note[lang]['paragraphs']: st.write(p)
                if note['unsupported_figures'][lang]:
                    st.warning('Not in the facts: ' + ', '.join(note['unsupported_figures'][lang]) + ' — redraft before using.', icon=':material/report:')
                else:
                    st.badge('all figures match the facts', color='green', icon=':material/fact_check:')
        with st.popover(f"{len(note['facts'])} facts used", icon=':material/list:'):
            for f in note['facts']: st.markdown(f"- {f['text']} · *{f['provenance']}*")
        if note['status'] == 'reviewed':
            st.success(f"Kiswahili checked by {note['reviewed_by']} on {note['reviewed_at']}.", icon=':material/verified:')
        else:
            with st.form('review_note', border=False):
                reader = st.text_input('Kiswahili reader who checked this note', max_chars=120)
                if st.form_submit_button('Confirm the translation', icon=':material/verified:'):
                    try:
                        st.session_state['public_note'] = note = review(note, reader)
                        state.audit_ai('public_note.reviewed', 'area', place, {'status': 'reviewed'})
                        st.rerun()
                    except ModelError as exc:
                        st.error(str(exc), icon=':material/error:')
        st.download_button('Download the note' + ('' if note['status'] == 'reviewed' else ' (draft)'), to_markdown(note),
                           f"flood_note_{place.lower().replace(' ', '_')}.md", 'text/markdown', icon=':material/download:')
        st.caption(f"AI-drafted by {note['model']}. Figures come from the hazard maps; the note gives no financial information.")
