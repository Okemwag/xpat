import streamlit as st
from ui import site

site.css()
site.hero(
    "Solutions",
    "Flood risk answers for each role in the decision",
    "Underwriters, portfolio managers, reinsurers and public bodies ask different questions of the same flood. "
    "Xpat answers each one from one transparent model.",
)
st.space("small")
site.cta_row(key="sol_hero")

AUDIENCES = [
    (
        "",
        "Underwriters & risk analysts",
        "What should I budget for at the 1-in-100 level — and can I defend it?",
        [
            "Loss at every return period, with the likely range",
            "Average annual loss for pricing conversations",
            "Property-level trace of how each loss was calculated",
            "Sensitivity to depth, curves and frequency in one click",
        ],
        "Loss curve · Property explorer · Assumptions",
    ),
    (
        "",
        "Portfolio & exposure managers",
        "How much insured value sits where one storm could hit it all at once?",
        [
            "Map of value, hazard and loss together",
            "Concentration by 1 km grid cell and by named flood area",
            "Top properties and areas driving the loss",
            "Share of loss outside the known flood hotspots",
        ],
        "Accumulation map · Overview",
    ),
    (
        "",
        "Reinsurers, cedants & brokers",
        "Can I get a consistent first view of a flood portfolio — fast?",
        [
            "Upload any portfolio CSV, or describe it in words",
            "Validation report before anything is modelled",
            "Gross and insured loss after per-property deductibles and limits",
            "Exportable summary, JSON report and property-level CSVs",
        ],
        "Portfolio · Reports & history",
    ),
    (
        "",
        "Counties & disaster-management bodies",
        "Where do flood hazard and valuable assets meet — and where is the map blind?",
        [
            "The 24 named flood areas checked against the hazard map",
            "Where drainage-driven flooding is invisible to the baseline",
            "A reviewed route to add local flood reports",
            "Plain-English explanations for non-specialists",
        ],
        "Data & honesty · AI flood evidence",
    ),
]

site.section("By role", "Pick your question")
for icon, title, question, outcomes, where in AUDIENCES:
    with st.container(border=True):
        a, b = st.columns([2, 3], gap="large")
        with a:
            if icon:
                st.html(f"<div class='x-icon'>{icon}</div>")
            st.subheader(title)
            st.markdown(f"*“{question}”*")
            st.caption(f"Where in Xpat: {where}")
        with b:
            for o in outcomes:
                st.markdown(f":material/check_circle: {o}")

site.section("By capability", "The building blocks")
site.cards(
    [
        (
            "",
            "Hazard intelligence",
            "Five flood-severity maps read at every property, with coverage checks — never a silent zero.",
            (
                "Automatic lookup for any uploaded location",
                "Named-hotspot validation",
                "AI drainage evidence to close the gaps",
            ),
        ),
        (
            "",
            "Vulnerability",
            "Published JRC depth-damage curves adapted per construction class, compared openly with the reference.",
            (
                "Informal, semi-permanent, masonry, concrete",
                "Damage caps of 80–95% of value",
                "Editable and documented",
            ),
        ),
        (
            "",
            "Exposure management",
            "Validation that handles real-world spreadsheets and explains every rejected row.",
            (
                "Excel encodings and separators",
                "Money like “KES 2.5m” or “300k”",
                "Swapped or missing coordinates flagged",
            ),
        ),
        (
            "",
            "Financial engine",
            "From damage to money: scenario losses, a 10,000-year simulation and average annual loss.",
            (
                "EP curve to 1-in-10,000",
                "Damage-uncertainty ranges",
                "Optional deductibles and limits",
            ),
        ),
        (
            "",
            "AI that changes the answer",
            "Gemini reads what spreadsheets and maps cannot — with people in control.",
            (
                "Plain-English portfolio intake",
                "Flood reports → reviewed evidence",
                "Measured on held-out tests",
            ),
        ),
        (
            "",
            "Governance",
            "Every run is reproducible and every number carries its provenance.",
            (
                "Config and input fingerprints",
                "Roles: analyst, reviewer, admin",
                "Downloadable audit trail",
            ),
        ),
    ]
)

site.section(
    "Starting point",
    "Nairobi urban flood today — more perils and cities next",
    "Nairobi surface-water flooding is the first use case. The same pipeline runs riverine depth maps and other "
    "African cities without changing the engine.",
)
site.band(
    "Try it on the sample portfolio",
    "Six hundred synthetic Nairobi properties, ready to run.",
)
st.space("small")
_, mid, _ = st.columns([1, 2, 1])
with mid:
    site.cta_row(key="sol_footer")
site.footer()
