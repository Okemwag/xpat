"""Flood reports → local embeddings → drainage-deficit factor: chunking, places, scoring, aggregation, sources, storage.

No network and no model files: the HashingEmbedder stands in for the local model, httpx.MockTransport for ReliefWeb,
and a fake LLM for Ollama/Gemini.
"""

import json
import httpx
import numpy as np
import pytest
from floodcat.ai import drainage
from floodcat.ai.embeddings import HashingEmbedder, chunk_text
from floodcat.ai.evidence import Evidence
from floodcat.ai.places import PlaceIndex
from floodcat.ai.reports import from_upload, ingest, reliefweb_search
from floodcat.core.config import ModelConfig, load_config, merge_defaults
from floodcat.core.errors import ModelError
from floodcat.platform import audit, data, orgs
from floodcat.platform.db import audit_events
from test_platform import PW, make_org, member, no_network, p  # noqa: F401  (pytest fixtures)

PLACES = [
    {"name": "Langata", "alt_names": ["Lang'ata"], "place": "suburb", "lat": -1.3622, "lon": 36.7537},
    {"name": "South C", "alt_names": [], "place": "suburb", "lat": -1.3200, "lon": 36.8300},
    {"name": "Kibera", "alt_names": [], "place": "suburb", "lat": -1.3133, "lon": 36.7880},
    {"name": "Ngong", "alt_names": [], "place": "town", "lat": -1.3530, "lon": 36.6680},
    {"name": "Harambee", "alt_names": [], "place": "neighbourhood", "lat": -1.29, "lon": 36.85},
    {"name": "Kianda", "alt_names": [], "place": "neighbourhood", "lat": -1.30, "lon": 36.78},
    {"name": "Kianda", "alt_names": [], "place": "neighbourhood", "lat": -1.25, "lon": 36.95},
]


@pytest.fixture
def places():
    return PlaceIndex(PLACES, ignore=["Harambee"], ambiguity_m=3000, not_before=["River", "Road"])


@pytest.fixture
def settings():
    s = load_config().drainage_reports
    # The hashing stand-in scores word overlap, not meaning: simple descriptions and lower thresholds.
    return {**s, "drainage_queries": ("blocked drains flooded the road",), "contrast_queries": ("the river burst its banks",),
            "min_similarity": 0.3, "min_margin": 0.1, "full_margin": 0.5}


@pytest.fixture
def embedder():
    return HashingEmbedder()


DRAIN = "Blocked drains flooded the road in South C after the storm."
RIVER = "The river burst its banks in Kibera and swept away houses."


# Chunking --------------------------------------------------------------------------------------------------------
def test_chunks_are_verbatim_slices_with_overlap():
    text = "First sentence here. Second one follows! Third? " + "Word " * 50 + "end. Last short one."
    chunks = chunk_text(text, max_words=20, overlap_sentences=1)
    assert all(text[c["start"]:c["end"]] == c["text"] for c in chunks)
    assert len(chunks) >= 3
    assert chunks[1]["start"] < chunks[0]["end"]  # one sentence shared with the previous window
    long = [c for c in chunks if len(c["text"].split()) > 20]
    assert len(long) == 1  # a sentence longer than the limit stays whole


# Places ----------------------------------------------------------------------------------------------------------
def test_place_matching_rules(places):
    found = {p["name"]: p["matched"] for p in places.find(
        "In Lang’ata and South C drains failed; the Ngong River rose; a harambee in Harambee; kibera was quiet; Kianda too.")}
    assert found == {"Langata": "Lang’ata", "South C": "South C"}
    assert "Kianda" in places.ambiguous  # same name, two places 19 km apart: dropped, not guessed
    assert places.find("Kibera-wide and LANGATA")[0]["name"] == "Kibera"


# Scoring ---------------------------------------------------------------------------------------------------------
def test_scorer_separates_drainage_from_river(embedder, settings):
    scorer = drainage.Scorer(embedder, settings)
    (dp, dn, ds), (rp, rn, rs) = scorer.score(embedder.embed([DRAIN, RIVER]))
    assert ds >= 0.5 and rs == 0 and dp - dn > rp - rn


def test_process_text_redacts_contacts_and_keeps_quotes_verbatim(embedder, settings):
    scorer = drainage.Scorer(embedder, settings)
    done = drainage.process_text(DRAIN + " Call 0722 123 456 or write to chief@example.org. " + RIVER, embedder, scorer, settings)
    assert "0722" not in done["text"] and "example.org" not in done["text"]
    assert all(done["text"][c["start"]:c["end"]] == c["text"] for c in done["chunks"])
    assert abs(float(np.linalg.norm(done["vector"])) - 1) < 1e-5
    with pytest.raises(ModelError):
        drainage.process_text("   ", embedder, scorer, settings)


def test_local_assessment_takes_places_from_drainage_chunks_only(embedder, settings, places):
    s = {**settings, "chunk_max_words": 12, "chunk_overlap_sentences": 0}
    done = drainage.process_text(DRAIN + " " + RIVER, embedder, drainage.Scorer(embedder, s), s)
    found = drainage.assess_local(done["chunks"], places)
    assert [a["place"] for a in found] == ["South C"] and found[0]["method"] == "gazetteer"
    assert found[0]["quote"] in DRAIN + " " + RIVER


# Aggregation -----------------------------------------------------------------------------------------------------
def _doc(i, strength, place="South C", independent=True, text=None, vec=None):
    v = vec if vec is not None else np.eye(4, dtype=np.float32)[i % 4]
    return {"id": f"d{i}", "title": f"Report {i}", "url": "", "published": f"2024-05-0{i}", "independent": independent,
            "content_hash": text or f"h{i}", "vector": v,
            "assessments": [{"place": place, "lat": -1.32, "lon": 36.83, "strength": strength, "quote": f"q{i}",
                             "method": "gazetteer"}]}


def test_factor_is_noisy_or_over_independent_reports_and_duplicates_count_once(settings):
    one = drainage.place_factors([_doc(1, 0.6)], settings)[0]
    assert one["factor"] == pytest.approx(0.6)
    two = drainage.place_factors([_doc(1, 0.6), _doc(2, 0.5)], settings)[0]
    assert two["factor"] == pytest.approx(1 - 0.4 * 0.5) and two["report_count"] == 2
    copy = drainage.place_factors([_doc(1, 0.6), _doc(2, 0.5, text="h1")], settings)[0]  # same text republished
    assert copy["report_count"] == 1 and copy["factor"] == pytest.approx(0.6)
    near = drainage.place_factors([_doc(1, 0.6), _doc(2, 0.5, vec=np.eye(4, dtype=np.float32)[1])], settings)[0]
    assert near["report_count"] == 1  # vectors identical → syndicated copy
    mixed = drainage.place_factors([_doc(1, 0.6), _doc(2, 0.5, independent=False)], settings)[0]
    assert mixed["all_independent"] is False


def test_place_becomes_valid_unapproved_drainage_evidence(settings):
    place = drainage.place_factors([_doc(1, 0.6), _doc(2, 0.7)], settings)[0]
    ev = drainage.to_evidence(place)
    assert isinstance(ev, Evidence) and not ev.approved
    assert ev.mechanism == "drainage" and ev.location_method == "gazetteer"
    assert ev.confidence == pytest.approx(place["factor"]) and ev.event_date == "2024-05-02"
    assert ev.quote == "q2" and drainage.to_evidence(place).evidence_id == ev.evidence_id  # stable id


# LLM modes -------------------------------------------------------------------------------------------------------
class FakeLLM:
    last_model = "fake-llm"

    def __init__(self, items):
        self.items, self.prompts = items, []

    def generate_json(self, system, prompt, schema):
        self.prompts.append(prompt)
        return {"items": self.items}


def test_llm_mode_reads_only_drainage_passages_and_keeps_drainage_items(embedder, settings, places):
    s = {**settings, "chunk_max_words": 12, "chunk_overlap_sentences": 0}
    done = drainage.process_text(DRAIN + " " + RIVER, embedder, drainage.Scorer(embedder, s), s)
    llm = FakeLLM([
        {"location_name": "South C", "event_date": None, "mechanism": "drainage", "quote": "Blocked drains flooded the road in South C", "confidence": 0.9},
        {"location_name": "Kibera", "event_date": None, "mechanism": "river_overflow", "quote": "Blocked drains flooded the road", "confidence": 0.9},
        {"location_name": "Atlantis", "event_date": None, "mechanism": "drainage", "quote": "Blocked drains flooded the road", "confidence": 0.9},
    ])
    found, model = drainage.assess_llm(done["chunks"], "Report", llm, places, s)
    assert [a["place"] for a in found] == ["South C"] and model == "fake-llm"
    assert "swept away" not in llm.prompts[0]  # the river passage never reaches the model
    assert found[0]["strength"] == pytest.approx(0.9 * done["chunks"][0]["strength"], abs=1e-3)


# Sources ---------------------------------------------------------------------------------------------------------
def test_csv_upload_gives_one_report_per_row_and_redacts():
    raw = b"title,text,url,date\nA,Drains blocked in South C. Call 0722 123 456,http://a,2024-04-30\nB,,,\n"
    out = from_upload(raw, "articles.csv")
    assert len(out) == 1 and out[0]["published"] == "2024-04-30" and "0722" not in out[0]["text"]
    with pytest.raises(ModelError):
        from_upload(b"title,body\nx,y\n", "bad.csv")
    assert from_upload(b"Plain report text.", "note.txt")[0]["title"] == "note"


def test_reliefweb_search_sends_kenya_filter_and_parses_reports():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["appname"] = request.url.params["appname"]
        return httpx.Response(200, json={"data": [{"fields": {
            "title": "Kenya: Floods Flash Update", "body": "<p>Blocked drains flooded South C.</p>",
            "url_alias": "https://reliefweb.int/x", "date": {"original": "2024-05-02T00:00:00+00:00"},
            "source": [{"shortname": "OCHA"}]}}, {"fields": {"title": "Empty", "body": ""}}]})

    out = reliefweb_search("flood", "2024-04-01", None, 5, appname="xpat-test", transport=httpx.MockTransport(handler))
    assert seen["appname"] == "xpat-test" and seen["body"]["limit"] == 5
    assert {"field": "country.iso3", "value": "KEN"} in seen["body"]["filter"]["conditions"]
    assert out == [{"title": "Kenya: Floods Flash Update — OCHA", "text": "Blocked drains flooded South C.",
                    "url": "https://reliefweb.int/x", "published": "2024-05-02", "source_kind": "reliefweb"}]
    with pytest.raises(ModelError) as exc:
        reliefweb_search("flood", appname="bad", transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    assert exc.value.code == "reliefweb_unavailable"


def test_reliefweb_needs_an_app_name(monkeypatch):
    monkeypatch.delenv("RELIEFWEB_APPNAME", raising=False)
    with pytest.raises(ModelError):
        reliefweb_search("flood")


# Config and settings -----------------------------------------------------------------------------------------------
def test_config_validates_drainage_settings_and_upgrades_old_sets(settings):
    cfg = load_config()
    with pytest.raises(ModelError):
        cfg.replace(drainage_reports={**cfg.drainage_reports, "min_margin": 0.5})
    with pytest.raises(ModelError):
        cfg.replace(drainage_reports={k: v for k, v in cfg.drainage_reports.items() if k != "llm_top_k"})
    legacy = {k: v for k, v in cfg.to_dict().items() if k not in ("drainage_reports", "imd_index")}
    assert ModelConfig(**merge_defaults(legacy)).drainage_reports["min_margin"] == cfg.drainage_reports["min_margin"]


def test_make_client_refuses_an_unconfigured_provider(monkeypatch):
    from floodcat.ai.llm import make_client

    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    with pytest.raises(ModelError):
        make_client("ollama")


# Storage (organisation-scoped, encrypted, audited) ------------------------------------------------------------------
def _ingested(embedder, settings, places, text=DRAIN):
    doc = ingest({"title": "Flash update", "text": text, "url": "", "published": "2024-05-01", "source_kind": "upload"},
                 embedder, drainage.Scorer(embedder, settings), places, settings)
    return {**doc, "independent": True}


def test_reports_are_stored_per_organisation_encrypted_and_audited(p, embedder, settings, places):
    _, owner, _ = make_org(p)
    uw, _ = member(p, owner, "uw@acme.re", ["underwriter"])
    viewer, _ = member(p, owner, "viewer@acme.re", ["viewer"])
    _, other, _ = make_org(p, "Other Re", "owner@other.re")
    other_uw, _ = member(p, other, "uw@other.re", ["underwriter"])
    doc = _ingested(embedder, settings, places)
    with p.tx() as c:
        doc_id = data.add_report(c, uw, doc)
        with pytest.raises(ModelError) as exc:
            data.add_report(c, uw, doc)
        assert exc.value.code == "duplicate_report"
        with pytest.raises(ModelError):
            data.add_report(c, viewer, doc)
        listed = data.list_reports(c, uw)
        assert [d["id"] for d in listed] == [doc_id] and listed[0]["assessments"][0]["place"] == "South C"
        chunks = data.report_chunks_for(c, uw)
        assert chunks[0]["text"] == DRAIN and chunks[0]["vector"].shape == (embedder.dim,)
        raw = c.exec_driver_sql("SELECT text_enc FROM report_chunks").scalar()
        assert "South C" not in raw  # encrypted at rest
        assert data.list_reports(c, other_uw) == [] and data.report_chunks_for(c, other_uw) == []
        with pytest.raises(ModelError):
            data.delete_report(c, other_uw, doc_id)
        events = [r.details for r in c.execute(audit_events.select().where(audit_events.c.action == "report.added"))]
        assert events and "South C" not in json.dumps(events) and "drains" not in json.dumps(events)
        data.update_report_assessments(c, uw, doc_id, [], "local")
        data.delete_report(c, uw, doc_id)
        assert data.list_reports(c, uw) == [] and data.report_chunks_for(c, uw) == []
        assert audit.verify_chain(c)[0]





def test_place_in_the_previous_sentence_is_used_but_never_from_a_river_sentence(places):
    chunks = [
        {"text": "Parts of South C were under water.", "strength": 0.0, "drainage_similarity": 0.5, "contrast_similarity": 0.4},
        {"text": "The drains were blocked.", "strength": 0.7, "drainage_similarity": 0.7, "contrast_similarity": 0.5},
        {"text": "The river burst its banks in Kibera.", "strength": 0.0, "drainage_similarity": 0.4, "contrast_similarity": 0.8},
        {"text": "Drains overflowed too.", "strength": 0.6, "drainage_similarity": 0.66, "contrast_similarity": 0.5},
    ]
    found = drainage.assess_local(chunks, places, lookback=1)
    assert [a["place"] for a in found] == ["South C"]
    assert found[0]["quote"] == "Parts of South C were under water. The drains were blocked."
    assert drainage.assess_local(chunks, places, lookback=0) == []
