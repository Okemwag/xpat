import streamlit as st
from floodcat.platform import identity, orgs
from ui import state
from ui.components import page_header

p = state.principal()
page_header('Teams', 'Group people by desk or line of business. Analyses shared with "team" are visible to that team.')
with state.platform().tx() as conn:
    teams = orgs.list_teams(conn, p.org_id)
    members = [m for m in identity.list_members(conn, p) if m['status'] == 'active']
names = {m['id']: m['display_name'] for m in members}
with st.form('team', clear_on_submit=True):
    name = st.text_input('New team name', placeholder='e.g. Facultative property')
    if st.form_submit_button('Create team') and name:
        if state.guarded(orgs.create_team, name) is not state.FAILED: st.rerun()
for t in teams:
    with st.container(border=True):
        st.markdown(f"**{t['name']}** · {len(t['member_ids'])} member(s)")
        chosen = st.multiselect('Members', list(names), default=[u for u in t['member_ids'] if u in names], format_func=names.get, key=f"tm_{t['id']}")
        a, b = st.columns([1, 5])
        if a.button('Save', key=f"ts_{t['id']}"):
            if state.guarded(orgs.set_team_members, t['id'], chosen) is not state.FAILED: st.success('Saved.')
        if b.button('Delete team', key=f"td_{t['id']}"):
            if state.guarded(orgs.delete_team, t['id']) is not state.FAILED: st.rerun()
if not teams: st.info('No teams yet. Without teams, analyses are private or shared with the whole organisation.')
