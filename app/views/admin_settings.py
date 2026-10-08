import streamlit as st
from floodcat.platform import orgs
from ui import state
from ui.components import kpis, page_header, section

p = state.principal()
page_header(
    "Organisation settings",
    "AI use, data retention, sharing defaults, underwriting authority and your organisation profile.",
)
with state.platform().tx() as conn:
    org = orgs.get_org(conn, p.org_id)
s, profile = org["settings"], org["profile"] or {}
kpis(
    [
        (
            "AI use",
            {"off": "Off", "extraction": "Documents only", "full": "All features"}[
                s["ai_mode"]
            ],
        ),
        (
            "New analyses visible to",
            {"private": "Author", "team": "Team", "org": "Everyone"}[
                s["default_visibility"]
            ],
        ),
        ("Analyses kept", f"{s['retention_runs_days']} days"),
        (
            "Authority limit (value)",
            state.kes(s["authority_limit_tiv_kes"])
            if s["authority_limit_tiv_kes"]
            else "none",
        ),
        ("Plan", f"{org['plan']} · {org['seats']} seats", f"Status {org['status']}"),
    ]
)

with st.form("settings"):
    section("AI features")
    ai = st.radio(
        "AI may be used for",
        ["off", "extraction", "full"],
        index=["off", "extraction", "full"].index(s["ai_mode"]),
        format_func={
            "off": "Nothing — AI off",
            "extraction": "Reading documents and descriptions",
            "full": "Documents, descriptions and flood-evidence extraction",
        }.get,
    )
    st.caption(
        f"AI on this server: {state.ai_name()}. "
        + (
            "Text is processed by a model on this server and does not leave it. "
            if state.ai_local()
            else "Document text is sent to Google Gemini. "
        )
        + "E-mails and phone numbers are removed first, and users consent each time."
    )
    report_modes = st.multiselect(
        "Flood reports may be read with",
        ["local", "ollama", "gemini"],
        default=s.get("report_modes", ["local", "ollama", "gemini"]),
        format_func={
            "local": "Local embeddings only (offline)",
            "ollama": "Local embeddings + Ollama (offline)",
            "gemini": "Local embeddings + Gemini (online)",
        }.get,
        help="Users choose among these on the Flood evidence page. Empty turns flood-report processing off.",
    )
    section("Sharing and retention")
    vis = st.radio(
        "Default visibility of new analyses",
        ["private", "team", "org"],
        index=["private", "team", "org"].index(s["default_visibility"]),
        horizontal=True,
        format_func={
            "private": "Only the author",
            "team": "The author's team",
            "org": "Everyone in the organisation",
        }.get,
    )
    a, b = st.columns(2)
    runs_days = a.number_input(
        "Keep analyses and document extractions for (days)",
        30,
        3650,
        int(s["retention_runs_days"]),
    )
    audit_days = b.number_input(
        "Keep audit records for (days)", 365, 36500, int(s["retention_audit_days"])
    )
    section("Underwriting authority")
    st.caption(
        "Submissions and underwriting decisions above these limits must be referred to the head of underwriting before they can be quoted, "
        "bound or accepted. Pricing and capacity rules are set by the head of underwriting on the Underwriting decision page."
    )
    a, b = st.columns(2)
    tiv = a.number_input(
        "Insured value limit (KES, 0 = none)",
        0.0,
        value=float(s["authority_limit_tiv_kes"] or 0),
        step=1e7,
        format="%.0f",
    )
    loss = b.number_input(
        "Modelled rarest-scenario loss limit (KES, 0 = none)",
        0.0,
        value=float(s["authority_limit_loss_kes"] or 0),
        step=1e6,
        format="%.0f",
    )
    if st.form_submit_button("Save settings", type="primary"):
        changes = {
            "ai_mode": ai,
            "report_modes": report_modes,
            "default_visibility": vis,
            "retention_runs_days": int(runs_days),
            "retention_audit_days": int(audit_days),
            "authority_limit_tiv_kes": tiv or None,
            "authority_limit_loss_kes": loss or None,
        }
        if state.guarded(orgs.update_settings, changes) is not state.FAILED:
            st.success("Saved.")

with st.form("profile"):
    section("Organisation profile")
    a, b = st.columns(2)
    legal = a.text_input("Legal name", org["legal_name"] or "")
    country = b.text_input("Country", org["country"] or "")
    address = st.text_input("Address", profile.get("address", ""))
    a, b, c = st.columns(3)
    dpo = a.text_input("Data-protection contact", profile.get("dpo_contact", ""))
    tech = b.text_input("Technical contact", profile.get("technical_contact", ""))
    billing = c.text_input("Billing contact", profile.get("billing_contact", ""))
    if st.form_submit_button("Save profile"):
        if (
            state.guarded(
                orgs.update_profile,
                {
                    "legal_name": legal,
                    "country": country,
                    "address": address,
                    "dpo_contact": dpo,
                    "technical_contact": tech,
                    "billing_contact": billing,
                },
            )
            is not state.FAILED
        ):
            st.success("Saved.")

section("Export all data")
st.caption(
    "Everything your organisation holds in Xpat — members, teams, analyses, extractions, evidence, assumption sets, submissions and the audit log — as JSON."
)
if st.button("Prepare export"):
    data = state.guarded(orgs.export_org)
    if data is not state.FAILED:
        st.download_button(
            "Download export",
            data,
            f"xpat-export-{org['name'].lower().replace(' ', '-')}.json",
            "application/json",
        )
st.caption(
    f"Plan: {org['plan']} · {org['seats']} seats · status {org['status']}. To change plan or close the organisation, contact Xpat."
)
