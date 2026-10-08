import streamlit as st
from floodcat.platform import identity, orgs
from ui import state
from ui.components import kpis, page_header

p = state.principal()
page_header(
    "Teams",
    'Group people by desk or line of business. Analyses shared with "team" are visible to that team.',
)
with state.platform().tx() as conn:
    teams = orgs.list_teams(conn, p.org_id)
    members = [m for m in identity.list_members(conn, p) if m["status"] == "active"]
names = {m["id"]: m["display_name"] for m in members}
in_team = set().union(*(set(t["member_ids"]) for t in teams)) if teams else set()
kpis(
    [
        ("Teams", len(teams)),
        ("People in a team", f"{len(in_team & set(names))} of {len(names)}"),
        (
            "Without a team",
            len(set(names) - in_team),
            "Their “team” analyses stay private",
        ),
    ]
)
with st.form("team", clear_on_submit=True):
    name = st.text_input("New team name", placeholder="e.g. Facultative property")
    if st.form_submit_button("Create team") and name:
        if state.guarded(orgs.create_team, name) is not state.FAILED:
            st.rerun()
for t in teams:
    with st.container(border=True):
        head = st.container(horizontal=True, vertical_alignment="center")
        head.markdown(f"**{t['name']}**")
        head.badge(
            f"{len(t['member_ids'])} member(s)", color="blue", icon=":material/group:"
        )
        chosen = st.multiselect(
            "Members",
            list(names),
            default=[u for u in t["member_ids"] if u in names],
            format_func=names.get,
            key=f"tm_{t['id']}",
        )
        actions = st.container(horizontal=True)
        if actions.button("Save", key=f"ts_{t['id']}", type="primary"):
            if (
                state.guarded(orgs.set_team_members, t["id"], chosen)
                is not state.FAILED
            ):
                st.success("Saved.")
        if actions.button("Delete team", key=f"td_{t['id']}", icon=":material/delete:"):
            if state.guarded(orgs.delete_team, t["id"]) is not state.FAILED:
                st.rerun()
if not teams:
    st.info(
        "No teams yet. Without teams, analyses are private or shared with the whole organisation."
    )
