import pandas as pd
import streamlit as st
from floodcat.platform import identity, orgs, registration
from floodcat.platform.rbac import ASSIGNABLE, ROLES
from ui import state
from collections import Counter
from ui.charts import hbars
from ui.components import kpis, page_header, section, when

p = state.principal()
page_header(
    "Users & invitations",
    "Approve people who registered, invite others, set everyone's roles (your own included) and remove access when they leave. "
    "Every change is audited.",
)
with state.platform().tx() as conn:
    members = identity.list_members(conn, p)
    invites = identity.list_invitations(conn, p)
    teams = orgs.list_teams(conn, p.org_id)
    org = orgs.get_org(conn, p.org_id)
    requests = registration.list_requests(conn, p)
members = [
    m for m in members if m["status"] != "pending"
]  # requests to join are listed separately
active = [m for m in members if m["status"] == "active"]
with_mfa = sum(bool(m["mfa_enabled_at"]) for m in active)
kpis(
    [
        ("Active users", len(active), None, f"{len(active)} of {org['seats']} seats"),
        ("Pending invitations", len([i for i in invites if not i["expired"]])),
        (
            "Requests to join",
            len(requests),
            "People who registered with your organisation's e-mail domain",
        ),
        (
            "Two-step verification",
            f"{with_mfa} of {len(active)}",
            "Active members with two-step turned on",
        ),
        (
            "Deactivated",
            sum(m["status"] == "deactivated" for m in members),
            "Access removed; their work kept",
        ),
    ]
)
role_label = lambda r: f"{r.replace('_', ' ').title()} — {ROLES[r]}"
grantable = [r for r in ASSIGNABLE if r != "owner" or "owner" in p.roles]

if requests:
    section(
        "Requests to join",
        "They registered with an address at your organisation's domain. Check who they are, then choose their access.",
    )
    for r in requests:
        with st.container(border=True):
            st.markdown(
                f"**{r['display_name']}** · {r['email']} · asked {when(r['created_at'])}"
            )
            with st.form(f"join_{r['id']}"):
                chosen = st.multiselect(
                    "Roles",
                    grantable,
                    default=["viewer"],
                    format_func=role_label,
                    key=f"join_roles_{r['id']}",
                )
                a, b = st.columns(2)
                approve = a.form_submit_button(
                    "Approve", type="primary", icon=":material/how_to_reg:"
                )
                decline = b.form_submit_button("Decline", icon=":material/person_off:")
            if (
                approve
                and state.guarded(registration.decide, r["id"], True, chosen)
                is not state.FAILED
            ):
                st.toast(
                    f"{r['display_name']} approved", icon=":material/check_circle:"
                )
                st.rerun()
            if (
                decline
                and state.guarded(registration.decide, r["id"], False)
                is not state.FAILED
            ):
                st.rerun()

with st.container(border=True):
    with state.platform().tx() as conn:
        code = registration.join_code(conn, p)
    left_c, right_c = st.columns([3, 1], vertical_alignment="center")
    with left_c:
        st.markdown(f"**Organisation code:** `{code}`")
        st.caption(
            "Share it with colleagues so they can request an account from the sign-in page (User, then Request an account), "
            "whatever e-mail they use. You still approve every request below. Replace the code if it was shared too widely."
        )
    with right_c:
        if st.button("Replace code", icon=":material/refresh:", key="new_join_code"):
            if state.guarded(registration.join_code, True) is not state.FAILED:
                st.rerun()

with st.expander(
    "Invite someone",
    icon=":material/person_add:",
    expanded=not invites and len(members) < 2,
):
    with st.form("invite", clear_on_submit=True):
        email = st.text_input("Work e-mail")
        roles = st.multiselect(
            "Roles", grantable, default=["underwriter"], format_func=role_label
        )
        team_ids = st.multiselect(
            "Teams",
            [t["id"] for t in teams],
            format_func={t["id"]: t["name"] for t in teams}.get,
        )
        domains = org["settings"]["allowed_domains"]
        if domains:
            st.caption(f"Only addresses at {', '.join(domains)} can be invited.")
        if st.form_submit_button("Send invitation", type="primary"):
            if (
                state.guarded(identity.invite, email, roles, team_ids)
                is not state.FAILED
            ):
                st.success(f"Invitation sent to {email}.")

if invites:
    section("Pending invitations")
    for inv in invites:
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            st.markdown(
                f"**{inv['email']}** · {', '.join(inv['roles'])} · {'expired' if inv['expired'] else 'expires ' + when(inv['expires_at'])}"
            )
            if st.button("Resend", key=f"resend_{inv['id']}"):
                if (
                    state.guarded(
                        identity.invite, inv["email"], inv["roles"], inv["team_ids"]
                    )
                    is not state.FAILED
                ):
                    st.rerun()
            if st.button("Revoke", key=f"revoke_{inv['id']}"):
                if (
                    state.guarded(identity.revoke_invitation, inv["id"])
                    is not state.FAILED
                ):
                    st.rerun()

left, right = st.columns([3, 1], gap="large")
with left.container(border=True, height="stretch"):
    section("Members")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Name": m["display_name"],
                    "E-mail": m["email"],
                    "Roles": m["roles"],
                    "Status": m["status"],
                    "Two-step": bool(m["mfa_enabled_at"]),
                    "Last sign-in": when(m["last_login_at"]),
                }
                for m in members
            ]
        ),
        hide_index=True,
        width="stretch",
        alt="Organisation members",
        column_config={
            "Roles": st.column_config.ListColumn(),
            "Two-step": st.column_config.CheckboxColumn(),
        },
    )
with right.container(border=True, height="stretch"):
    section("People per role")
    roles_count = Counter(r for m in active for r in m["roles"])
    chart = hbars(
        [
            {"Role": r.replace("_", " "), "People": n, "_label": str(n)}
            for r, n in roles_count.most_common()
        ],
        "Role",
        "People",
        "People",
        text="_label",
        height_per=26,
    )
    if chart:
        st.altair_chart(chart, width="stretch", alt="Active members per role")
me = next((m for m in members if m["id"] == p.user_id), None)
if me is not None:
    with st.expander("Your own roles", icon=":material/badge:"):
        st.caption(
            "Administrator roles (owner, admin) manage the organisation but do not run analyses. Add working roles such as "
            "head of underwriting or analyst to use the model yourself. You must keep an administrator role. Saving signs you "
            "out so the new roles apply at once; it needs a recent password check."
        )
        with st.form("own_roles"):
            own = st.multiselect(
                "Your roles",
                grantable,
                default=[r for r in me["roles"] if r in grantable],
                format_func=role_label,
            )
            if st.form_submit_button("Save my roles"):
                keep = [
                    r for r in me["roles"] if r not in grantable
                ]  # e.g. owner held by a non-owner editor is never dropped silently
                if (
                    state.guarded(
                        identity.set_roles,
                        p.user_id,
                        sorted(set(own) | set(keep)),
                        "changed own roles",
                    )
                    is not state.FAILED
                ):
                    st.success("Saved. Sign in again to continue with your new roles.")
                    st.link_button("Sign in again", state.auth_link("/auth/login"))
others = [m for m in members if m["id"] != p.user_id]
if others:
    section("Change a member")
    choice = st.selectbox(
        "Member",
        [m["id"] for m in others],
        format_func={
            m["id"]: f"{m['display_name']} ({m['email']}) — {m['status']}"
            for m in others
        }.get,
    )
    m = next(x for x in others if x["id"] == choice)
    roles_tab, leave_tab, mfa_tab = st.tabs(
        ["Roles", "Deactivate / reactivate", "Reset two-step"]
    )
    with roles_tab:
        with st.form("roles"):
            new_roles = st.multiselect(
                "Roles",
                grantable,
                default=[r for r in m["roles"] if r in grantable],
                format_func=role_label,
            )
            reason = st.text_input("Reason (recorded in the audit log)")
            if st.form_submit_button("Save roles"):
                if (
                    state.guarded(identity.set_roles, m["id"], new_roles, reason)
                    is not state.FAILED
                ):
                    st.success(
                        "Roles updated. Their sessions were signed out so the change applies at once."
                    )
    with leave_tab:
        if m["status"] == "active":
            st.write(
                "Removes access immediately: sessions and API tokens are revoked. Their analyses and submissions can be handed to someone else."
            )
            heirs = [x for x in active if x["id"] != m["id"]]
            heir = st.selectbox(
                "Hand their work to",
                [None] + [x["id"] for x in heirs],
                format_func=lambda i: (
                    "Nobody (keep under their name)"
                    if i is None
                    else next(x["display_name"] for x in heirs if x["id"] == i)
                ),
            )
            if st.button("Deactivate", type="primary"):
                if (
                    state.guarded(identity.deactivate, m["id"], heir)
                    is not state.FAILED
                ):
                    st.rerun()
        elif st.button("Reactivate"):
            if state.guarded(identity.reactivate, m["id"]) is not state.FAILED:
                st.rerun()
    with mfa_tab:
        st.write(
            "For a lost phone. They must set up two-step verification again at next sign-in. Requires your password and a reason."
        )
        reason = st.text_input("Reason / ticket number", key="mfa_reason")
        if st.button("Reset two-step verification"):
            if (
                state.guarded(identity.admin_reset_mfa, m["id"], reason)
                is not state.FAILED
            ):
                st.success("Reset. They have been signed out.")
