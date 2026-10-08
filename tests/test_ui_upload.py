"""Drive the real Portfolio page's upload path. AppTest cannot upload files, so st.file_uploader is stubbed."""

import pytest
import sys
from conftest import DATA

sys.path.insert(0, str(DATA.parent / "tests"))

pytest.importorskip("streamlit")
pytest.importorskip("rasterio")
from streamlit.testing.v1 import AppTest

APP_DIR = DATA.parent / "app"


def page(store_dir, csv_bytes, name="upload.csv"):
    def script(app_dir, store_dir, csv_bytes, name, token, tests_dir):
        import os, sys

        os.environ["FLOODCAT_STORE_DIR"] = store_dir
        for path in (app_dir, tests_dir):
            if path not in sys.path:
                sys.path.insert(0, path)
        import streamlit as st

        class Uploaded:
            def __init__(self, data, name):
                self._data, self.name = data, name

            def getvalue(self):
                return self._data

        st.file_uploader = lambda *a, **k: Uploaded(csv_bytes, name)
        st.switch_page = lambda *a, **k: st.session_state.__setitem__(
            "switched_to", a[0]
        )
        from ui_helpers import page_preamble

        page_preamble(store_dir, token)
        exec(
            compile(
                open(f"{app_dir}/views/portfolio.py").read(), "portfolio.py", "exec"
            ),
            {"__name__": "__main__"},
        )

    from ui_helpers import make_session

    token = make_session(store_dir)
    return AppTest.from_function(
        script,
        args=(
            str(APP_DIR),
            str(store_dir),
            csv_bytes,
            name,
            token,
            str(DATA.parent / "tests"),
        ),
        default_timeout=60,
    )


def run_button(at):
    return next(b for b in at.button if b.label == "Run analysis")


def test_clean_upload_runs(tmp_path):
    at = page(tmp_path, (DATA / "exposure_nairobi_synthetic.csv").read_bytes())
    at.run()
    assert not at.exception
    assert run_button(at).disabled is False
    run_button(at).click()
    at.run()
    assert not at.exception and at.session_state["result"]["modelled_count"] == 600


def test_upload_with_errors_needs_explicit_partial(tmp_path):
    csv = (
        b"loc_id,lat,lon,housing_class,tiv_kes,synthetic,source\n"
        b"A,-1.28,36.82,concrete,1m,True,x\nB,36.82,-1.28,concrete,1m,True,x\n"
    )
    at = page(tmp_path, csv)
    at.run()
    assert not at.exception and run_button(at).disabled is True
    next(
        c for c in at.checkbox if c.label.startswith("Run on the valid records only")
    ).check()
    at.run()
    run_button(at).click()
    at.run()
    assert not at.exception and at.session_state["result"]["modelled_count"] == 1


def test_upload_without_synthetic_columns_needs_declaration(tmp_path):
    csv = b'id,latitude,longitude,construction,tiv\nA,-1.2576,36.8962,semi-permanent,"3,300,000"\n'
    at = page(tmp_path, csv)
    at.run()
    assert not at.exception and not [b for b in at.button if b.label == "Run analysis"]
    assert any("real or synthetic" in i.value for i in at.info)
    at.radio(key="upload_origin").set_value("real")
    at.run()
    assert run_button(at).disabled is True  # real data needs the authorisation box
    at.checkbox(key="upload_authorised").check()
    at.run()
    assert run_button(at).disabled is False
    run_button(at).click()
    at.run()
    assert not at.exception and at.session_state["result"]["modelled_count"] == 1
    assert at.session_state["result"]["exposure_origin"]["labels"] == ["REAL"]


def test_unreadable_file_shows_error_not_crash(tmp_path):
    at = page(tmp_path, b"\x00\x01\x02 not a csv")
    at.run()
    assert not at.exception


def doc_page(store_dir, doc_bytes, name):
    def script(app_dir, store_dir, doc_bytes, name, tests_dir, token):
        import os, sys

        os.environ["FLOODCAT_STORE_DIR"] = store_dir
        for p in (app_dir, tests_dir):
            if p not in sys.path:
                sys.path.insert(0, p)
        import streamlit as st

        class Uploaded:
            def __init__(self, data, name):
                self._data, self.name = data, name

            def getvalue(self):
                return self._data

        st.file_uploader = lambda *a, **k: (
            Uploaded(doc_bytes, name) if k.get("key") == "main_upload" else None
        )
        st.switch_page = lambda *a, **k: st.session_state.__setitem__(
            "switched_to", a[0]
        )
        from ui_helpers import page_preamble

        page_preamble(store_dir, token)
        import floodcat.ai.submission as submission
        from test_submission import FakeGaz, prop
        from ui import state

        state.ai_available = lambda: True
        state.ai_enabled = lambda kind="extraction": True

        def fake_extract(
            document, llm, gazetteer, provider, hotspots, config, defaults
        ):
            result = submission.build_submission(
                document["text"],
                {"properties": [prop()]},
                FakeGaz(),
                provider,
                hotspots,
                config,
                defaults,
                "fake-gemini",
            )
            return {
                **result,
                "filename": document["filename"],
                "kind": document["kind"],
                "pages": document["pages"],
                "chars": document["chars"],
                "name_mismatch": document["name_mismatch"],
            }

        submission.extract_submission = fake_extract
        state.runtime().llm = lambda: None
        state.runtime().gazetteer = lambda *a, **k: None
        exec(
            compile(
                open(f"{app_dir}/views/portfolio.py").read(), "portfolio.py", "exec"
            ),
            {"__name__": "__main__"},
        )

    from ui_helpers import make_session

    token = make_session(store_dir)
    return AppTest.from_function(
        script,
        args=(
            str(APP_DIR),
            str(store_dir),
            doc_bytes,
            name,
            str(DATA.parent / "tests"),
            token,
        ),
        default_timeout=60,
    )


def test_document_upload_extract_review_and_run(tmp_path):
    pytest.importorskip("pypdf")
    from test_submission import DOC_LINES, make_pdf

    at = doc_page(tmp_path, make_pdf(DOC_LINES), "OFFER.docx.pdf")
    at.run()
    assert not at.exception
    extract = next(b for b in at.button if b.label == "Extract properties with AI")
    assert extract.disabled  # nothing goes to Gemini without consent
    next(c for c in at.checkbox if c.label.startswith("Send the text above to")).check()
    at.run()
    next(b for b in at.button if b.label == "Extract properties with AI").click()
    at.run()
    assert not at.exception and "submission" in at.session_state
    assert any(
        "km from" in w.value for w in at.warning
    )  # GPS vs address conflict surfaced
    assert not [
        b for b in at.button if b.key == "doc_run"
    ]  # no run until the data origin is stated
    at.radio(key="doc_origin").set_value("real")
    at.run()
    at.checkbox(key="doc_authorised").check()
    at.run()
    next(
        b for b in at.button if b.label == "Run analysis" and b.key == "doc_run"
    ).click()
    at.run()
    assert not at.exception
    report = at.session_state["result"]
    row = report["runs"]["baseline"]["property_losses"]["common"][0]
    assert report["modelled_count"] == 1 and row["exposed_fraction"] == pytest.approx(
        0.15
    )
    assert (
        "insured" in report["runs"]["baseline"]
    )  # the document's deductible and limit applied
    assert (
        at.session_state["submission_review"]["label"] == at.session_state["run_label"]
    )
    assert report["exposure_origin"]["labels"] == ["REAL"]


def test_uploaded_values_are_escaped_in_map_tooltips(tmp_path):
    """A malicious ID in an uploaded CSV must not become live HTML in the map tooltip."""
    from floodcat.services.analysis import analyse
    from conftest import row

    report = analyse([row(loc_id="<img src=x onerror=alert(1)>")])
    import html

    r = report["runs"]["baseline"]["property_losses"]["common"][0]
    assert "<img" not in f"<b>{html.escape(r['loc_id'])}</b>"
    source = (DATA.parent / "app" / "views" / "map.py").read_text()
    assert "_h(r['loc_id'])" in source and "_h(r['nearest_hotspot'])" in source
