"""Every page renders for every role, before and after a run (headless). Navigation only offers what a role may use."""

import os
import sys
import pytest
from conftest import DATA

pytest.importorskip("streamlit")
pytest.importorskip("rasterio")
sys.path.insert(0, str(DATA.parent / "tests"))
sys.path.insert(0, str(DATA.parent / "app"))
from streamlit.testing.v1 import AppTest

APP = str(DATA.parent / "app" / "streamlit_app.py")
PAGES = [
    "overview",
    "portfolio",
    "submissions",
    "decision",
    "notifications",
    "results",
    "map",
    "property",
    "assumptions",
    "evidence",
    "hazard_checks",
    "public_notes",
    "honesty",
    "method",
    "history",
    "account",
    "admin",
    "admin_teams",
    "admin_security",
    "admin_settings",
    "admin_review",
    "admin_audit",
]
ROLES = [
    "owner",
    "admin",
    "head_uw",
    "underwriter",
    "analyst",
    "reviewer",
    "viewer",
    "auditor",
]


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    path = tmp_path_factory.mktemp("ui_pages")
    saved = {
        k: os.environ.get(k) for k in ("FLOODCAT_STORE_DIR", "FLOODCAT_DATABASE_URL")
    }
    os.environ["FLOODCAT_STORE_DIR"] = str(path)
    os.environ["FLOODCAT_DATABASE_URL"] = (
        f"sqlite:///{path}/platform.db"  # wins over any .env value
    )
    from ui import state

    state.platform.clear()
    yield path
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    state.platform.clear()


def app(token):
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["_test_session_token"] = token
    at.run()
    return at


def visit(at, page):
    try:
        at.switch_page(f"views/{page}.py")
    except ValueError:
        return None  # not in this role's navigation
    at.run()
    return [e.value for e in at.exception]


@pytest.mark.parametrize("role", ROLES)
def test_every_visible_page_renders(store, role):
    from ui_helpers import make_session

    token = make_session(
        store, roles=(role,), org_name=f"Org {role}", email=f"{role}@test.re"
    )
    at = app(token)
    assert not at.exception, at.exception[0].value
    seen = []
    for page in PAGES:
        errors = visit(at, page)
        if errors is None:
            continue
        seen.append(page)
        assert not errors, f"{role} on {page}: {errors[0][:400]}"
    if role in ("owner", "admin"):
        assert {"admin", "admin_security", "admin_audit"} <= set(seen)
    if role in ("viewer", "auditor", "reviewer"):
        assert "portfolio" not in seen and "admin" not in seen
    if role == "auditor":
        assert "admin_audit" in seen


def test_pages_with_a_run_loaded(store):
    from ui_helpers import make_session

    token = make_session(
        store, roles=("head_uw",), org_name="Run Re", email="head@run.re"
    )
    at = app(token)
    at.switch_page("views/portfolio.py")
    at.run()
    next(b for b in at.button if b.label == "Run the sample portfolio").click()
    at.run()
    assert not at.exception and "result" in at.session_state
    for page in PAGES:
        errors = visit(at, page)
        if errors is not None:
            assert not errors, f"{page}: {errors[0][:400]}"


def test_signed_out_sees_public_pages_only(store):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    with pytest.raises(ValueError):
        at.switch_page("views/overview.py")
    for page in ("landing", "solutions", "signin", "method"):
        at.switch_page(f"views/{page}.py")
        at.run()
        assert not at.exception, page


def test_admin_and_workflow_actions_through_pages(store):
    from ui_helpers import make_session
    from floodcat.platform.email import recent
    from floodcat.platform.service import Platform

    token = make_session(
        store,
        roles=("owner", "head_uw", "analyst"),
        org_name="Flow Re",
        email="boss@flow.re",
    )
    plat = Platform(f"sqlite:///{store}/platform.db")
    at = app(token)
    # Invite a colleague.
    at.switch_page("views/admin.py")
    at.run()
    next(t for t in at.text_input if t.label == "Work e-mail").input(
        "colleague@flow.re"
    )
    next(b for b in at.button if b.label == "Send invitation").click()
    at.run()
    assert not at.exception and any("Invitation sent" in s.value for s in at.success)
    with plat.tx() as c:
        assert any(m["kind"] == "invitation" for m in recent(c, "colleague@flow.re"))
    # Security change needs a fresh password check (session older than 10 minutes).
    from sqlalchemy import update
    from floodcat.platform.db import sessions
    from floodcat.platform.identity import now, timedelta

    with plat.tx() as c:
        c.execute(update(sessions).values(reauth_at=now() - timedelta(hours=1)))
    at.switch_page("views/admin_security.py")
    at.run()
    next(b for b in at.button if b.label == "Save policy").click()
    at.run()
    assert not at.exception and any(
        "confirm your password" in w.value.lower() for w in at.warning
    )
    # Submission: create, refer.
    at.switch_page("views/submissions.py")
    at.run()
    next(t for t in at.text_input if t.label == "Name").input("Landmark Plaza")
    next(b for b in at.button if b.label == "Create").click()
    at.run()
    assert not at.exception
    from floodcat.platform.db import submissions
    from sqlalchemy import select

    with plat.tx() as c:
        assert c.execute(select(submissions.c.name)).scalars().all() == [
            "Landmark Plaza"
        ]
    # Assumption proposal from a sandbox change.
    at.switch_page("views/assumptions.py")
    at.run()
    at.slider[0].set_value(2.0)
    next(b for b in at.button if b.label == "Apply to my sandbox and re-run").click()
    at.run()
    next(t for t in at.text_area if t.label.startswith("Why should")).input(
        "Survey of 2026 flood depths"
    )
    next(b for b in at.button if b.label == "Submit proposal").click()
    at.run()
    assert not at.exception and any("Proposal submitted" in s.value for s in at.success)
    # The same person cannot approve their own proposal (separation of duties).
    at.run()
    next(b for b in at.button if b.label == "Approve and make house view").click()
    at.run()
    assert any("Someone other than the proposer" in e.value for e in at.error)


def test_briefing_from_overview(store, monkeypatch):
    from ui_helpers import make_session

    token = make_session(
        store, roles=("underwriter",), org_name="Brief Re", email="uw@brief.re"
    )
    at = app(token)
    at.switch_page("views/portfolio.py")
    at.run()
    next(b for b in at.button if b.label == "Run the sample portfolio").click()
    at.run()
    at.switch_page("views/overview.py")
    at.run()
    assert not at.exception
    # Inject a fake model through the cached runtime used by the page.
    from ui import state

    class FakeLLM:
        model = "fake-gemini"

        def generate_json(self, system, prompt, schema):
            return {
                "headline": "Loss of KES 1.70 bn at 1-in-100",
                "sections": [
                    {
                        "heading": "What the results say",
                        "paragraphs": ["KES 1.70 bn; also 4,321."],
                    }
                ],
                "checks": ["Check the depth assumption."],
            }

    monkeypatch.setattr(state, "ai_enabled", lambda kind="extraction": True)
    monkeypatch.setattr(state, "llm", lambda client_data=False: FakeLLM())
    at.run()
    next(b for b in at.button if b.label == "Draft briefing").click()
    at.run()
    assert not at.exception
    assert any("4321" in w.value for w in at.warning)


def test_underwriting_decision_flow(store, monkeypatch):
    from ui_helpers import make_session
    from floodcat.platform.service import Platform
    from floodcat.platform.db import decisions
    from sqlalchemy import select

    token = make_session(
        store, roles=("underwriter",), org_name="Decide Re", email="uw@decide.re"
    )
    at = app(token)
    at.switch_page("views/portfolio.py")
    at.run()
    next(b for b in at.button if b.label == "Run the sample portfolio").click()
    at.run()
    at.switch_page("views/decision.py")
    at.run()
    assert not at.exception and any(
        "Enter the offered premium" in i.value for i in at.info
    )
    next(n for n in at.number_input if n.label.startswith("Offered premium")).set_value(
        400_000_000.0
    )
    next(n for n in at.number_input if n.label.startswith("Offered share")).set_value(
        20.0
    )
    next(b for b in at.button if b.label == "Get recommendation").click()
    at.run()
    assert not at.exception and any("Recommended share" == m.label for m in at.metric)
    from ui import state

    class FakeLLM:
        model = "fake-gemini"

        def generate_json(self, system, prompt, schema):
            return {
                "summary": "Price is adequate; capacity is the limit.",
                "drivers": ["The 1-in-250 loss."],
                "what_would_change_it": ["A smaller share."],
                "trust": "Proxy hazard.",
                "questions_for_broker": ["Confirm the locations."],
            }

    monkeypatch.setattr(state, "ai_enabled", lambda kind="extraction": True)
    monkeypatch.setattr(state, "llm", lambda client_data=False: FakeLLM())
    at.run()
    next(b for b in at.button if b.label == "Explain this recommendation").click()
    at.run()
    assert not at.exception and any(
        "capacity is the limit" in m.value for m in at.markdown
    )
    next(b for b in at.button if b.label == "Record decision").click()
    at.run()
    assert not at.exception
    with Platform(f"sqlite:///{store}/platform.db").tx() as c:
        row = c.execute(select(decisions)).mappings().first()
    assert (
        row and not row["overrode"] and row["rationale"]["summary"].startswith("Price")
    )
    assert {b.label for b in at.get("download_button")} >= {
        "PDF report",
        "Word report",
        "Excel workbook",
    }


def test_ask_results_and_drainage_page(store, monkeypatch):
    from ui_helpers import make_session

    token = make_session(
        store, roles=("analyst",), org_name="Ask Re", email="an@ask.re"
    )
    at = app(token)
    at.switch_page("views/portfolio.py")
    at.run()
    next(b for b in at.button if b.label == "Run the sample portfolio").click()
    at.run()
    from ui import state

    class FakeLLM:
        model = "fake-gemini"

        def generate_json(self, system, prompt, schema):
            return {
                "answerable": True,
                "answer": "Average annual loss is in the facts; 9,876 is not.",
                "fact_labels": ["Average annual loss"],
                "chart": "loss_curve",
            }

    monkeypatch.setattr(state, "ai_enabled", lambda kind="extraction": True)
    monkeypatch.setattr(state, "llm", lambda client_data=False: FakeLLM())
    at.switch_page("views/overview.py")
    at.run()
    next(t for t in at.text_input if t.label == "Your question").input(
        "What is the average annual loss?"
    )
    next(b for b in at.button if b.label == "Ask").click()
    at.run()
    assert not at.exception, at.exception[0].value
    assert "ask_overview_answer" in at.session_state
    assert at.session_state["ask_overview_answer"][1]["unsupported_figures"] == ["9876"]
    # Drainage page with small in-memory layers (the real ones are built by scripts/build_drainage_layers.py).
    from floodcat.hazard.drainage import DrainageLayers

    monkeypatch.setitem(
        state.runtime().__dict__,
        "drainage_layers",
        DrainageLayers(
            drains=[[[36.80, -1.40], [36.80, -1.15]]],
            culverts=[[36.80, -1.30]],
            buildings=[[36.78, -1.31]] * 200,
            source="test",
        ),
    )
    at.switch_page("views/hazard_checks.py")
    at.run()
    assert not at.exception, at.exception[0].value
    assert any(m.label == "Named hotspots flagged" for m in at.metric)
    next(
        b
        for b in at.button
        if b.label == "Re-run the current portfolio with the drainage model"
    ).click()
    at.run()
    assert not at.exception, at.exception[0].value
    assert at.session_state["result"]["ai_contribution"]["drainage"]["mode"] == "prior"


def test_admin_approves_join_request_and_edits_own_roles(store):
    from ui_helpers import make_session, PW
    from floodcat.platform import identity, registration
    from floodcat.platform.email import recent
    from floodcat.platform.service import Platform
    import re

    token = make_session(
        store, roles=("owner",), org_name="Admin Re", email="boss@adminre.test"
    )
    plat = Platform(f"sqlite:///{store}/platform.db")
    with plat.tx() as c:
        p, _ = identity.resolve_session(c, token)
        from floodcat.platform import orgs

        identity.reauthenticate(c, p, password=PW)
        orgs.update_settings(c, p, {"allowed_domains": ["adminre.test"]})
        registration.register(
            c, "join", "ula@adminre.test", "Ula", PW, request={"ip": "1.1.1.1"}
        )
    at = app(token)
    at.switch_page("views/admin.py")
    at.run()
    assert not at.exception, at.exception[0].value
    assert any("Ula" in m.value for m in at.markdown)
    next(b for b in at.button if b.label == "Approve").click()
    at.run()
    assert not at.exception, at.exception[0].value
    from sqlalchemy import select
    from floodcat.platform.db import memberships, users

    with plat.tx() as c:
        ula = c.execute(
            select(users.c.id).where(users.c.email == "ula@adminre.test")
        ).scalar()
        assert [o["name"] for o in identity.user_orgs(c, ula)] == ["Admin Re"]
    # The owner can add working roles to their own account (and keeps the owner role).
    assert any(e.label == "Your own roles" for e in at.expander)
    own = next(m for m in at.multiselect if m.label == "Your roles")
    own.set_value(["owner", "head_uw"])
    next(b for b in at.button if b.label == "Save my roles").click()
    at.run()
    assert not at.exception, at.exception[0].value
    with plat.tx() as c:
        roles = c.execute(
            select(memberships.c.roles)
            .join(users, users.c.id == memberships.c.user_id)
            .where(users.c.email == "boss@adminre.test")
        ).scalar()
    assert sorted(roles) == ["head_uw", "owner"]
