import hashlib
import secrets
import pandas as pd
import streamlit as st
from floodcat.core.constants import CLASSES
from floodcat.core.errors import ModelError, ReviewRequired
from floodcat.exposure.validation import apply_declarations, validate_rows
from ui import state
from ui.charts import donut
from ui.components import (
    badges,
    explain,
    issues_panel,
    kpis,
    page_header,
    pipeline_strip,
    section,
)

TEMPLATE = (
    "loc_id,lat,lon,housing_class,floor_area_m2,cost_per_m2_kes,tiv_kes,synthetic,source\n"
    "P-001,-1.2576,36.8962,semi_permanent,33,10000,3300000,True,my test portfolio\n"
    "P-002,-1.3113,36.7890,informal_iron_sheet,12,8000,96000,True,my test portfolio\n"
    "P-003,-1.2630,36.8106,concrete_rcc,400,60000,24000000,True,my test portfolio\n"
)
EXAMPLES = [
    "20 iron-sheet houses in Mathare, about 300,000 shillings each. A three-storey concrete block of flats in Kileleshwa insured for 45 million.",
    "Five semi-permanent shops along Outer Ring Road in Donholm, roughly 40 square metres each. Twelve masonry homes in Kibera worth 1.2m each.",
]

page_header(
    "Portfolio",
    "Load the properties to model — a schedule, a broker document or a plain-English description. "
    "Every source goes through the same validation before any loss is calculated.",
)
pipeline_strip("Exposure")
if state.read_only():
    st.error(
        "Your organisation is suspended (read-only). New analyses are disabled.",
        icon=":material/block:",
    )
    st.stop()
if st.session_state.get("active_submission"):
    from floodcat.platform import data as _data

    try:
        with state.platform().tx() as _c:
            _sub = _data.get_submission(
                _c, state.principal(), st.session_state["active_submission"]
            )
        _a, _b = st.columns([5, 1], vertical_alignment="center")
        _a.info(
            f"Analyses you run now are linked to the submission **{_sub['name']}**.",
            icon=":material/work:",
        )
        if _b.button("Unlink"):
            st.session_state.pop("active_submission")
            st.rerun()
    except Exception:
        st.session_state.pop("active_submission", None)

ORIGIN_LABEL = {
    "real": "Real exposure — a client portfolio or broker submission",
    "synthetic": "Synthetic or test data",
}


def run_and_go(rows, label, settings):
    with st.spinner("Running hazard → vulnerability → loss…"):
        report, error = state.execute(rows, label, settings=settings)
    if error is None:
        st.session_state.pop("pending", None)
        st.session_state.pop("ai_draft", None)
        st.toast(
            f"{report['modelled_count']} properties modelled",
            icon=":material/check_circle:",
        )
        st.switch_page("views/overview.py")
    if isinstance(error, ReviewRequired):
        st.session_state["review_error"] = {
            "issues": error.issues,
            "accepted": error.accepted_count,
        }
    else:
        st.error(f"{error}", icon=":material/error:")


def preview(assets):
    """Where the valid records are and what they are made of, before anything is modelled."""
    if not assets:
        return
    left, right = st.columns([3, 2], gap="large")
    with left.container(border=True, height="stretch"):
        section("Where they are")
        st.map(
            pd.DataFrame(
                {"lat": [a.lat for a in assets], "lon": [a.lon for a in assets]}
            ),
            size=40,
            color="#2a78d6",
            height=280,
        )
    with right.container(border=True, height="stretch"):
        section("What they are made of", "Share of insured value by construction")
        mix = {}
        for a in assets:
            mix[a.housing_class] = mix.get(a.housing_class, 0) + float(a.tiv_kes)
        chart = donut(
            [
                {
                    "Class": state.class_label(c),
                    "Value": mix[c],
                    "Amount": state.kes(mix[c]),
                }
                for c in CLASSES
                if c in mix
            ],
            "Class",
            "Value",
            fmt="Amount",
            height=240,
        )
        if chart:
            st.altair_chart(
                chart, width="stretch", alt="Insured value by construction class"
            )
        explain(
            "How the insured value splits across the four construction classes.",
            "Fragile classes lose a larger share of value in a flood; concrete loses less per metre but often holds most of the value.",
            ["ASSUMPTION"],
        )


def review_and_run(rows, label_default, source_kind, key, origin_hint=None):
    """Shared review step: where the data comes from, validation summary, preview, explicit partial run."""
    columns = set().union(*(r.keys() for r in rows))
    missing_label = not {"synthetic", "source"} <= columns or any(
        r.get("synthetic") in (None, "") for r in rows
    )
    missing_ids = "loc_id" not in columns or any(
        r.get("loc_id") in (None, "") for r in rows
    )
    origin, authorised = None, True
    with st.container(border=True):
        st.markdown("**Before running**")
        if missing_label:
            choices = (
                ["synthetic"]
                if state.runtime().synthetic_only
                else ["real", "synthetic"]
            )
            default = choices.index(origin_hint) if origin_hint in choices else None
            origin = st.radio(
                "Where does this data come from?",
                choices,
                index=default,
                key=f"{key}_origin",
                format_func=ORIGIN_LABEL.get,
                help="Real data is labelled REAL throughout the results; synthetic data is labelled SYNTHETIC.",
            )
            if state.runtime().synthetic_only:
                st.caption("This deployment accepts synthetic data only.")
            if origin == "real":
                authorised = st.checkbox(
                    "I am authorised to process this data. It is kept on this server, contact details are not stored, "
                    "and results are indicative — not a price or underwriting advice.",
                    key=f"{key}_authorised",
                )
        assign = st.checkbox(
            "Give records without an ID a generated one (UPL-<row>)",
            value=False,
            key=f"{key}_ids",
            disabled=not missing_ids,
        )
        label = st.text_input(
            "Name this run", value=label_default, max_chars=80, key=f"{key}_label"
        )
    source_label = f"{source_kind}; {origin or 'as labelled'} data, confirmed by {state.user()['display_name']}"
    prepared, _ = apply_declarations(
        rows, False, source_label, assign, data_origin=origin
    )
    if missing_label and origin is None:
        st.info(
            "Choose whether this is real or synthetic data to continue.",
            icon=":material/help:",
        )
        return
    try:
        assets, issues = validate_rows(prepared, state.runtime().synthetic_only)
    except ModelError as exc:
        st.error(str(exc), icon=":material/error:")
        return
    real = sum(not x.synthetic for x in assets)
    kpis(
        [
            ("Records", f"{len(rows):,}"),
            (
                "Valid",
                f"{len(assets):,}",
                None,
                f"{len(rows) - len(assets)} cannot be modelled"
                if len(rows) > len(assets)
                else "all valid",
            ),
            ("Insured value (valid)", state.kes(sum(x.tiv_kes for x in assets))),
            (
                "Data",
                "REAL"
                if real == len(assets) and assets
                else "SYNTHETIC"
                if not real
                else "REAL + SYNTHETIC",
                "As declared for each record",
            ),
        ]
    )
    issues_panel(issues, expanded=True)
    preview(assets)
    errors = any(i["severity"] == "error" for i in issues)
    review = st.session_state.get("review_error")
    partial = False
    if errors or review:
        if review:
            st.error(
                "Some valid records could not be given a hazard value:",
                icon=":material/error:",
            )
            issues_panel([i for i in review["issues"] if i["severity"] == "error"])
        partial = st.checkbox(
            f"Run on the valid records only and report the rest as excluded",
            key=f"{key}_partial",
        )
    disabled = not assets or not authorised or (bool(errors or review) and not partial)
    if st.button(
        "Run analysis",
        type="primary",
        icon=":material/play_arrow:",
        disabled=disabled,
        key=f"{key}_run",
    ):
        st.session_state.pop("review_error", None)
        run_and_go(
            rows,
            label or label_default,
            {
                "data_origin": origin,
                "assign_missing_ids": assign,
                "allow_partial": partial,
                "source_label": source_label,
            },
        )


upload, describe, sample = st.tabs(
    [
        ":material/upload_file: Upload a file",
        ":material/edit_note: Describe in words (AI)",
        ":material/dataset: Sample portfolio",
    ]
)

with upload:
    left, right = st.columns([3, 2], gap="large")
    with right:
        with st.container(border=True):
            st.markdown("**What you can upload**")
            st.markdown(
                "- **A property schedule** — CSV or Excel (.xlsx). Read directly.\n"
                "- **A document** — a broker submission, placement memo, survey or schedule as PDF, Word (.docx) or text. "
                "Read by AI, with every value quoted from the document and checked before it is modelled."
            )
            st.markdown(
                "**Schedule columns** — required: `loc_id`, `lat`, `lon`, `housing_class`, `tiv_kes`; optional: `floor_area_m2`, "
                "`cost_per_m2_kes`, `floors_above_ground`, `basement_levels`, `deductible_kes`, `deductible_pct_of_loss`, `limit_kes`, "
                "`synthetic`, `source`. Common spellings (*Latitude*, *TIV*, *concrete*, *mabati*) and values like `KES 2.5m` are accepted. "
                "A schedule with unrecognised columns can be read by AI instead."
            )
            st.download_button(
                "Download schedule template",
                TEMPLATE,
                "xpat_portfolio_template.csv",
                "text/csv",
                icon=":material/download:",
            )
    with left:
        file = st.file_uploader(
            "Schedule or document",
            type=None,
            key="main_upload",
            help="CSV, Excel, PDF, Word or text — the type is detected from the file itself. Up to 15 MB.",
        )
        if file is not None:
            from floodcat.exposure.loaders import classify_upload, parse_xlsx

            data = file.getvalue()
            digest = hashlib.sha256(data).hexdigest()
            if not state.screen_upload(data, digest):
                st.stop()
            try:
                kind = classify_upload(data, file.name)
            except ModelError as exc:
                st.error(f"Could not read {file.name}: {exc}", icon=":material/error:")
                kind = None
            if kind in ("table", "xlsx"):
                if st.session_state.get("pending", {}).get("digest") != digest:
                    st.session_state.pop("review_error", None)
                    try:
                        rows = (
                            parse_xlsx(data)
                            if kind == "xlsx"
                            else state.runtime().parse_upload(data)
                        )
                        st.session_state["pending"] = {
                            "digest": digest,
                            "name": file.name,
                            "rows": rows,
                            "kind": kind,
                        }
                    except ModelError as exc:
                        st.session_state.pop("pending", None)
                        st.error(
                            f"Could not read {file.name}: {exc}",
                            icon=":material/error:",
                        )
                pending = st.session_state.get("pending")
                if pending and pending["digest"] == digest:
                    columns = set().union(*(r.keys() for r in pending["rows"]))
                    st.caption(
                        f"{pending['name']} · {'Excel' if pending['kind'] == 'xlsx' else 'CSV'} schedule · {len(pending['rows'])} rows · "
                        f"columns: {', '.join(sorted(columns))}"
                    )
                    from floodcat.exposure.loaders import CONTRACT

                    if len(CONTRACT & columns) < 3:
                        st.warning(
                            "These columns do not match the schedule format. Let AI read the schedule as a document instead:",
                            icon=":material/help:",
                        )
                        from ui.submission_view import submission_flow

                        text = "\n".join(
                            ", ".join(f"{k}: {v}" for k, v in r.items() if v)
                            for r in pending["rows"]
                        )
                        submission_flow(
                            text.encode("utf-8"), file.name + ".txt", review_and_run
                        )
                    else:
                        review_and_run(
                            pending["rows"],
                            pending["name"].rsplit(".", 1)[0],
                            f"uploaded file {pending['name']}",
                            "upload",
                        )
            elif kind == "document":
                from ui.submission_view import submission_flow

                submission_flow(data, file.name, review_and_run)

with describe:
    badges("AI", "ASSUMPTION")
    if not state.ai_enabled("extraction"):
        st.warning(
            "AI reading is unavailable here (not configured, or turned off by your organisation). Use a CSV or Excel schedule, or the sample portfolio, instead.",
            icon=":material/key_off:",
        )
    ev = state.ingestion_eval()
    if ev:
        st.caption(
            f"Tested on {ev['summary']['cases']} held-out descriptions: {ev['summary']['cases_fully_correct']} fully correct "
            f"(see Data & honesty). You still review every record."
        )
    st.write(
        "Describe buildings as you would to a colleague. The AI model turns your words into records; OpenStreetMap locates the places; "
        "anything you did not say is filled from a stated assumption and marked. You review every row before it is modelled."
    )
    ex = st.pills("Examples", ["Example 1", "Example 2"], key="example_pick")
    default_text = (
        EXAMPLES[int(ex[-1]) - 1] if ex else st.session_state.get("describe_text", "")
    )
    text = st.text_area(
        "Portfolio description",
        value=default_text,
        height=140,
        max_chars=8000,
        placeholder="e.g. 15 masonry homes in Kayole worth about 2 million each…",
    )
    st.session_state["describe_text"] = text
    if st.button(
        "Turn into records",
        type="primary",
        icon=":material/auto_awesome:",
        disabled=not state.ai_enabled("extraction") or not text.strip(),
    ):
        from floodcat.ai.ingestion import ingest

        if not state.ai_quota():
            st.stop()
        try:
            with st.spinner(
                f"{state.ai_name()} is reading the description; locating places…"
            ):
                rt = state.runtime()
                draft = ingest(
                    text,
                    rt.llm(),
                    rt.gazetteer(),
                    rt.class_defaults,
                    batch_id="AI" + secrets.token_hex(2).upper(),
                )
            st.session_state["ai_draft"] = draft
            st.session_state.pop("review_error", None)
        except ModelError as exc:
            st.error(str(exc), icon=":material/error:")
    draft = st.session_state.get("ai_draft")
    if draft:
        st.subheader("What the AI understood")
        st.caption(
            f"Model: {draft['model']} · prompt {draft['prompt_version']} · {len(draft['rows'])} records from {len(draft['groups'])} group(s)"
        )
        for g in draft["groups"]:
            with st.container(border=True):
                st.markdown(
                    f"**Group {g['group']}: {g['count']} × {state.class_label(g['housing_class'])} in {g['location_name'] or '?'}** — "
                    f"value each: {state.kes(g['tiv_kes_each'], compact=False) if g['tiv_kes_each'] != '—' else '—'}"
                )
                st.markdown(
                    f"> {g['source_quote']}"
                    + (
                        ""
                        if g["quote_verified"]
                        else "  \n:orange[quote not found in your text]"
                    )
                )
                st.caption(g["field_provenance"] or "no fields extracted")
                for flag in g["flags"]:
                    st.warning(flag, icon=":material/flag:")
        if draft["unparsed"]:
            with st.expander("Sentences the AI could not use"):
                for u in draft["unparsed"]:
                    st.write(f"- {u}")
        st.markdown(
            "**Edit records** — fix anything flagged; changes here override the AI."
        )
        frame = pd.DataFrame(draft["rows"])
        edited = st.data_editor(
            frame,
            hide_index=True,
            width="stretch",
            num_rows="dynamic",
            key="ai_editor",
            column_config={
                "housing_class": st.column_config.SelectboxColumn(
                    "housing_class", options=list(CLASSES)
                ),
                "source": None,
                "synthetic": None,
                "ai_group": None,
                "ai_field_provenance": st.column_config.TextColumn(
                    "provenance", disabled=True
                ),
            },
        )
        rows = [
            {k: ("" if pd.isna(v) else str(v)) for k, v in r.items()}
            for r in edited.to_dict("records")
        ]
        for r in rows:
            r["source"] = r.get("source") or draft["rows"][0]["source"]
        review_and_run(rows, "Described portfolio", "AI-ingested description", "ai")

with sample:
    badges("SYNTHETIC", "PROXY")
    sample_rows = state.runtime().sample_rows()
    by_class = {}
    for r in sample_rows:
        by_class[r["housing_class"]] = by_class.get(r["housing_class"], 0) + float(
            r["tiv_kes"]
        )
    kpis(
        [
            ("Properties", f"{len(sample_rows):,}", "Invented Nairobi buildings"),
            ("Insured value", state.kes(sum(by_class.values()))),
            ("Construction classes", len(by_class)),
            ("Origin", "SYNTHETIC", "Hackathon starter kit — not a real portfolio"),
        ]
    )
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.write(
            "600 synthetic Nairobi properties supplied with the hackathon starter kit. Their insured values are about "
            "10× floor area × cost per m² — the cause is unconfirmed, so the supplied values are used as they are and the gap is flagged."
        )
        with st.container(horizontal=True):
            if st.button(
                "Run the sample portfolio", type="primary", icon=":material/play_arrow:"
            ):
                run_and_go(sample_rows, "Starter kit sample (600 synthetic)", {})
            st.download_button(
                "Download the sample CSV",
                state.runtime().sample_path.read_bytes(),
                "exposure_nairobi_with_hazard.csv",
                "text/csv",
                icon=":material/download:",
            )
    with right.container(border=True):
        chart = donut(
            [
                {
                    "Class": state.class_label(c),
                    "Value": by_class[c],
                    "Amount": state.kes(by_class[c]),
                }
                for c in CLASSES
                if c in by_class
            ],
            "Class",
            "Value",
            fmt="Amount",
            height=200,
        )
        if chart:
            st.altair_chart(
                chart,
                width="stretch",
                alt="Sample portfolio insured value by construction class",
            )
        st.caption("Insured value by construction. Concrete holds most of the value.")
