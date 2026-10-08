"""The eight AI enhancements (docs/AI_ENHANCEMENTS.md). Fake LLM, fetcher and rasters only: no test touches the network."""

import json
from decimal import Decimal
from pathlib import Path
import numpy as np
import pytest
from floodcat.ai.evidence import Evidence
from floodcat.core.config import ModelConfig, load_config, merge_defaults
from floodcat.core.constants import TIERS
from floodcat.core.errors import ModelError
from floodcat.exposure.validation import validate_rows
from floodcat.hazard.hotspots import Hotspot, hotspot_check
from floodcat.services.analysis import analyse
from conftest import row

DATA = Path(__file__).resolve().parents[1] / "data"


class FakeLLM:
    model = "fake-gemini"

    def __init__(self, response):
        self.response = response
        self.calls = []

    def generate_json(self, system, prompt, schema):
        self.calls.append((system, prompt, schema))
        return self.response


class EastProvider:
    """Scores rise to the east of 36.85 and are zero to the west (a stand-in for the proxy rasters)."""

    def scores(self, asset):
        base = 0.0 if asset.lon < 36.85 else min(0.9, (asset.lon - 36.85) * 4)
        return {t: min(1.0, base * (1 + i * 0.1)) for i, t in enumerate(TIERS)}


def evidence(i, lat, lon, independent=True, approved=True, mechanism="drainage"):
    return Evidence(
        f"ev-{i}",
        f"https://news.example/{i}",
        "Drains overflowed and homes flooded.",
        "2024-04-24",
        f"Place {i}",
        lat,
        lon,
        "manual",
        mechanism,
        0.9,
        independent,
        approved,
        "Reviewer" if approved else None,
    )


# 1 · Drainage-aware hazard ------------------------------------------------------------------------------------------
def layers_west_dense():
    from floodcat.hazard.drainage import DrainageLayers

    rng = np.random.default_rng(1)
    # Dense buildings and no drains around 36.78 (west); a mapped drain along 36.92 (east).
    buildings = [
        [36.78 + float(x), -1.30 + float(y)]
        for x, y in rng.uniform(-0.004, 0.004, size=(400, 2))
    ]
    return DrainageLayers(
        drains=[[[36.92, -1.40], [36.92, -1.15]]],
        culverts=[[36.92, -1.30]],
        buildings=buildings,
        source="test",
    )


def test_drainage_features_are_bounded_and_respond_to_inputs(config):
    layers = layers_west_dense()
    dense = layers.features(-1.30, 36.78, 0.0, config)
    empty = layers.features(-1.20, 36.66, 0.0, config)
    for f in (dense, empty):
        assert set(f) == {
            "low_terrain",
            "built_density",
            "drain_gap",
            "culvert_proximity",
        } and all(0 <= v <= 1 for v in f.values())
    assert dense["built_density"] > 0.5 > empty["built_density"]
    near_drain = layers.features(-1.30, 36.9205, 0.0, config)
    assert near_drain["drain_gap"] < 0.2 and near_drain["culvert_proximity"] > 0.5


def test_drainage_falls_back_to_prior_without_enough_independent_evidence(config):
    from floodcat.hazard.drainage import fit

    items = [evidence(i, -1.30, 36.78 + i * 0.001) for i in range(3)] + [
        evidence(9, -1.30, 36.79, independent=False)
    ]
    model = fit(layers_west_dense(), EastProvider(), items, config)
    assert (
        model.mode == "prior"
        and "3 independent flood point" in model.training["reason"]
    )
    assert model.weights == config.drainage_model["prior_weights"]


def test_drainage_fit_learns_from_evidence_and_never_uses_hotspots(config):
    from floodcat.hazard.drainage import fit, training_points

    items = [
        evidence(i, -1.30 + 0.0005 * (i % 4), 36.778 + 0.001 * (i // 4))
        for i in range(12)
    ]
    items.append(evidence(99, -1.25, 36.70, approved=False))
    assert (
        len(training_points(items, config)) == 12
    )  # unapproved excluded; nothing from any hotspot list
    model = fit(layers_west_dense(), EastProvider(), items, config)
    assert model.mode == "fitted" and model.training["positives"] == 12
    assert model.training["mean_p_positive"] > model.training["mean_p_background"]
    assert model.weights["built_density"] > 0


def test_drainage_uplift_respects_threshold_and_tier_order(config):
    from floodcat.hazard.drainage import DrainageAdjustment, DrainageModel

    layers = layers_west_dense()
    never = DrainageAdjustment(
        layers,
        DrainageModel(
            "prior", -50.0, {k: 0.0 for k in config.drainage_model["prior_weights"]}
        ),
        config,
    )
    base = {t: 0.0 for t in TIERS}
    assert (
        never.signal(-1.30, 36.78, base) == 0
        and never.adjust(-1.30, 36.78, base) == base
    )
    always = DrainageAdjustment(
        layers,
        DrainageModel(
            "prior", 50.0, {k: 0.0 for k in config.drainage_model["prior_weights"]}
        ),
        config,
    )
    adjusted = always.adjust(-1.30, 36.78, base)
    assert (
        all(adjusted[a] <= adjusted[b] for a, b in zip(TIERS, TIERS[1:]))
        and adjusted[TIERS[-1]] > 0
    )


def test_analyse_with_drainage_keeps_baseline_and_invariants(config):
    from floodcat.hazard.drainage import DrainageAdjustment, prior_model

    rows = [
        row(f"T-{i}", lat=str(-1.30 + 0.0003 * i), lon="36.78", scores=(0, 0, 0, 0, 0))
        for i in range(5)
    ]
    rows += [row("E-1", lon="36.95", scores=(0.1, 0.2, 0.3, 0.4, 0.5))]
    adjustment = DrainageAdjustment(layers_west_dense(), prior_model(config), config)
    plain = analyse(rows, config)
    report = analyse(rows, config, drainage=adjustment)
    assert report["runs"]["baseline"]["aal"] == plain["runs"]["baseline"]["aal"]
    ai = report["ai_contribution"]
    assert (
        ai["enabled"]
        and not ai["evidence_enabled"]
        and ai["drainage"]["mode"] == "prior"
        and ai["changed_properties"] >= 1
    )
    for run in report["runs"].values():
        losses = [Decimal(p["loss_kes"]) for p in run["ep_curve"]]
        assert all(a <= b for a, b in zip(losses, losses[1:]))
        for t in TIERS:
            total = sum(Decimal(r["loss_kes"]) for r in run["property_losses"][t])
            assert total == Decimal(
                next(p["loss_kes"] for p in run["ep_curve"] if p["tier"] == t)
            )
    enhanced = {
        p["tier"]: Decimal(p["loss_kes"])
        for p in report["runs"]["enhanced"]["ep_curve"]
    }
    baseline = {
        p["tier"]: Decimal(p["loss_kes"])
        for p in report["runs"]["baseline"]["ep_curve"]
    }
    assert all(enhanced[t] >= baseline[t] for t in TIERS)
    assert all(
        r["synthetic"] is True
        for r in report["runs"]["enhanced"]["property_losses"][TIERS[-1]]
    )


def test_drainage_hit_rate_reports_before_and_after(config):
    from floodcat.hazard.drainage import DrainageAdjustment, hit_rate, prior_model

    hotspots = [
        Hotspot("Dense west", -1.30, 36.78),
        Hotspot("Empty west", -1.20, 36.66),
        Hotspot("East", -1.30, 36.95),
    ]
    result = hit_rate(
        hotspots,
        EastProvider(),
        DrainageAdjustment(layers_west_dense(), prior_model(config), config),
    )
    assert (
        result["before_flagged"]
        == hotspot_check(hotspots, EastProvider())["flagged_any_tier"]
        == 1
    )
    assert (
        result["after_flagged"] >= result["before_flagged"]
        and "Empty west" not in result["newly_flagged"]
    )
    assert result["caveats"]


def test_drainage_layers_file_round_trip(tmp_path, config):
    from floodcat.hazard.drainage import DrainageLayers

    path = tmp_path / "layers.json"
    path.write_text(
        json.dumps(
            {
                "drains": [[[36.8, -1.3], [36.81, -1.3]]],
                "culverts": [],
                "buildings": [[36.8, -1.3]],
                "source": "OSM",
            }
        )
    )
    layers = DrainageLayers.load(path)
    assert layers.counts == {"drain_segments": 1, "culverts": 0, "buildings": 1}
    with pytest.raises(ModelError):
        DrainageLayers.load(tmp_path / "missing.json")


# 2 · Evidence harvester -----------------------------------------------------------------------------------------------
ARTICLE = (
    "<html><script>var x=1;</script><nav>Home News Sport</nav><p>Residents of Kayole Junction said blocked drains flooded more than forty homes "
    "on 24 April 2024 after heavy overnight rain.</p><p>Call 0722 123 456 for help. The county said culverts along Spine Road were full of "
    "rubbish and water stood for two days in the estate.</p></html>"
)
LIST_ARTICLE = (
    "<p>The county listed flood-prone areas identified this season: Mathare, Kibera, Mukuru, Kawangware and Westlands, "
    "urging residents to move to higher ground immediately.</p>"
)


def fake_fetch(pages):
    def fetch(url):
        if "gdeltproject" in url:
            return pages["search"]
        if url not in pages:
            raise ModelError("fetch_failed", "not found")
        return pages[url]

    return fetch


class Gaz:
    def lookup(self, name):
        return {"lat": -1.27, "lon": 36.90, "method": "nominatim"}


def test_harvest_parses_dedupes_extracts_and_marks_list_dependence(config):
    from floodcat.ai.harvest import harvest

    search = json.dumps(
        {
            "articles": [
                {"url": "https://news.ke/a", "title": "Kayole floods"},
                {"url": "https://www.news.ke/a/", "title": "Kayole floods"},
                {"url": "https://news.ke/b", "title": "Hotspots"},
                {"url": "https://news.ke/old", "title": "Old"},
                {"url": "ftp://bad", "title": "x"},
            ]
        }
    )
    pages = {
        "search": search,
        "https://news.ke/a": ARTICLE,
        "https://news.ke/b": LIST_ARTICLE * 3,
    }
    quote = "Residents of Kayole Junction said blocked drains flooded more than forty homes on 24 April 2024 after heavy overnight rain."
    llm = FakeLLM(
        {
            "items": [
                {
                    "location_name": "Kayole Junction",
                    "event_date": "2024-04-24",
                    "mechanism": "drainage",
                    "quote": quote,
                    "confidence": 0.9,
                }
            ]
        }
    )
    result = harvest(
        config,
        llm,
        Gaz(),
        ["Mathare", "Kibera", "Mukuru", "Kawangware", "Westlands"],
        fetch=fake_fetch(pages),
        known_sources=["https://news.ke/old"],
        queries=["Nairobi floods"],
    )
    status = {a["url"]: a["status"] for a in result["articles"]}
    assert status == {
        "https://news.ke/a": "extracted",
        "https://news.ke/b": "extracted",
        "https://news.ke/old": "already in library",
    }
    first = [c for c in result["candidates"] if c["source"] == "https://news.ke/a"]
    assert (
        first
        and first[0]["independent_of_hotspot_list"]
        and first[0]["status"] == "needs_review"
    )
    assert not [
        c for c in result["candidates"] if c["source"] == "https://news.ke/b"
    ]  # quote not in that article → dropped
    assert next(a for a in result["articles"] if a["url"] == "https://news.ke/b")[
        "reproduces_hotspot_list"
    ]
    assert "0722" not in llm.calls[0][1]  # contact details removed before the AI call


def test_harvest_stops_at_quota_and_survives_bad_search(config):
    from floodcat.ai.harvest import harvest

    pages = {
        "search": json.dumps(
            {"articles": [{"url": "https://news.ke/a", "title": "a"}]}
        ),
        "https://news.ke/a": ARTICLE,
    }
    result = harvest(
        config,
        FakeLLM({"items": []}),
        Gaz(),
        [],
        fetch=fake_fetch(pages),
        allow_call=lambda: False,
        queries=["q"],
    )
    assert result["stopped"] and result["articles"][0]["status"].startswith("stopped")
    broken = harvest(
        config,
        FakeLLM({"items": []}),
        Gaz(),
        [],
        fetch=fake_fetch({"search": "<html>rate limited</html>"}),
        queries=["q"],
    )
    assert broken["searched"][0]["results"] == 0 and "error" in broken["searched"][0]


def test_harvest_text_extraction_and_url_safety():
    from floodcat.ai.harvest import _public_host, article_text, http_fetch, search_url

    text = article_text(ARTICLE)
    assert "blocked drains" in text and "var x" not in text and "Home News" not in text
    assert "sourcecountry%3Akenya" in search_url("Nairobi floods")
    assert (
        not _public_host("http://127.0.0.1/admin")
        and not _public_host("file:///etc/passwd")
        and not _public_host("http://10.0.0.1/")
    )
    with pytest.raises(ModelError):
        http_fetch("http://localhost:8000/")


# 3 · Satellite flood check --------------------------------------------------------------------------------------------
def geotiff(path, array, west=36.60, north=-1.10, size=0.01, dtype="uint8", nodata=255):
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=dtype,
        crs="EPSG:4326",
        transform=from_origin(west, north, size, size),
        nodata=nodata,
    ) as ds:
        ds.write(array.astype(dtype), 1)
    return path


def test_satellite_check_scores_hits_and_dry_ground(tmp_path, config):
    from floodcat.hazard.satellite import FloodExtent, compare, training_points

    grid = np.zeros((35, 40))
    grid[:, 30:] = 1  # flooded in the east (lon ≥ 36.90), where the provider scores > 0
    grid[0, 0] = 255  # one unobserved pixel
    extent = FloodExtent.read(geotiff(tmp_path / "flood.tif", grid))
    result = compare(
        extent,
        EastProvider(),
        config,
        hotspots=[Hotspot("East", -1.30, 36.95), Hotspot("West", -1.30, 36.70)],
    )
    assert result["hit_rate_any_pct"] == 100.0 and result["dry_flag_rate_any_pct"] < 50
    assert {
        h["name"]: h["flooded_nearby"] for h in result["hotspots_with_observed_water"]
    } == {"East": True, "West": False}
    assert (
        result["labels"] == {"flood_map": "REAL", "comparison": "PROXY"}
        and result["caveats"]
    )
    assert all(lon >= 36.90 for _, lon in training_points(extent, config, 20))
    bytes_extent = FloodExtent.read((tmp_path / "flood.tif").read_bytes())
    assert (
        bytes_extent.summary()["flooded_pixels"] == extent.summary()["flooded_pixels"]
    )


def test_satellite_check_rejects_non_binary_maps(tmp_path):
    from floodcat.hazard.satellite import FloodExtent

    with pytest.raises(ModelError):
        FloodExtent.read(geotiff(tmp_path / "bad.tif", np.full((5, 5), 7)))
    with pytest.raises(ModelError):
        FloodExtent.read(b"not a tiff")


# 4 · Building attributes from imagery ---------------------------------------------------------------------------------
def test_storeys_from_building_heights_fill_blanks_only_and_change_loss(
    tmp_path, config
):
    from floodcat.exposure.buildings import HeightRaster, apply_floors, propose_floors

    heights = np.full((100, 100), np.nan)
    heights[60:80, 20:40] = 12.0
    heights[10:20, 10:20] = 0.5
    # 0.001° pixels from (36.70, -1.20): row 70, col 30 → lat -1.2705, lon 36.7305
    raster = HeightRaster.read(
        geotiff(
            tmp_path / "h.tif",
            heights,
            west=36.70,
            north=-1.20,
            size=0.001,
            dtype="float32",
            nodata=np.nan,
        )
    )
    rows = [
        row("B-1", lat="-1.2705", lon="36.7305", scores=(0.5,) * 5),
        row("B-2", lat="-1.2705", lon="36.7305", floors_above_ground="2"),
        row("B-3", lat="-1.2155", lon="36.7155"),
        row("B-4", lat="-1.4", lon="36.9"),
    ]
    proposals = propose_floors(rows, raster, config)
    by_id = {p["loc_id"]: p for p in proposals}
    assert set(by_id) == {"B-1", "B-3", "B-4"}  # B-2 already has storeys
    assert by_id["B-1"]["floors"] == 4 and by_id["B-1"]["status"] == "proposed"
    assert (
        by_id["B-3"]["status"] == "no_building" and by_id["B-4"]["status"] == "no_data"
    )
    filled = apply_floors(rows, proposals, [by_id["B-1"]["row"]])
    assert (
        filled[0]["floors_above_ground"] == "4"
        and "AI (Open Buildings" in filled[0]["ai_field_provenance"]
    )
    assert (
        rows[0]["floors_above_ground"] if "floors_above_ground" in rows[0] else True
    )  # input untouched
    assets, issues = validate_rows(filled)
    assert len(assets) == 4 and not [i for i in issues if i["severity"] == "error"]
    before = analyse(rows[:1], config)["runs"]["baseline"]["aal"]["aal_kes"]
    after = analyse(filled[:1], config)["runs"]["baseline"]["aal"]["aal_kes"]
    assert Decimal(after) < Decimal(before)  # only the ground storey is flood-exposed


# 5 · Schedule quality reviewer ----------------------------------------------------------------------------------------
DEFAULTS = {"permanent_masonry": {"floor_area_m2": 100.0, "cost_per_m2_kes": 30000.0}}


def test_quality_review_flags_and_fixes_pass_validation(config):
    from floodcat.exposure.quality import apply_fixes, review, summarise

    rows = [
        row(
            "Q-1", floor_area_m2="100", cost_per_m2_kes="30000", tiv="30000000"
        ),  # 10× area × cost
        row(
            "Q-1", lat="-1.29", floor_area_m2="100", cost_per_m2_kes="30000", tiv="3000"
        ),  # duplicate id; value in thousands
        row("Q-3", lat="36.82", lon="-1.28"),  # swapped
        row(
            "Q-4", floor_area_m2="100", cost_per_m2_kes="300000", tiv="30000000"
        ),  # cost outlier (and 1×)
        row("Q-5", lat="-1.28", lon="36.82", tiv="1000000"),
    ]  # same as Q-... ? different class/tiv
    flags = review(rows, DEFAULTS, config)
    codes = {(f["loc_id"], f["code"]) for f in flags}
    assert {
        ("Q-1", "tiv_about_10x"),
        ("Q-1", "duplicate_id"),
        ("Q-1", "tiv_units"),
        ("Q-3", "swapped_coordinates"),
        ("Q-4", "cost_outlier"),
    } <= codes
    assert summarise(flags)[0]["severity"] == "error"
    fixed = apply_fixes(rows, flags, [i for i, f in enumerate(flags) if f["fix"]])
    assets, issues = validate_rows(fixed)
    assert len(assets) == len(fixed) and not [
        i for i in issues if i["severity"] == "error"
    ]
    by_id = {r["loc_id"]: r for r in fixed}
    assert (
        by_id["Q-1"]["tiv_kes"] == "3000000.00"
        and by_id["Q-1-dup2"]["tiv_kes"] == "3000000.00"
    )
    assert (
        by_id["Q-3"]["lat"] == "-1.28"
        and "user-accepted fix" in by_id["Q-3"]["review_note"]
    )
    assert apply_fixes(rows, flags, []) == rows


def test_quality_duplicate_record_can_be_dropped(config):
    from floodcat.exposure.quality import apply_fixes, review

    rows = [row("D-1"), row("D-2")]
    flags = review(rows, {}, config)
    assert [f["code"] for f in flags] == ["duplicate_record"]
    assert [r["loc_id"] for r in apply_fixes(rows, flags, [0])] == ["D-1"]


def test_quality_ai_explains_known_codes_only_and_checks_figures():
    from floodcat.ai.quality import explain

    groups = [
        {
            "code": "tiv_units",
            "severity": "warning",
            "count": 2,
            "fixable": 2,
            "examples": [
                "Insured value 3,000 is far below area × cost (KES 3,000,000)"
            ],
        }
    ]
    llm = FakeLLM(
        {
            "items": [
                {
                    "code": "tiv_units",
                    "why_it_matters": "Values of 3,000 would make losses 1000 times too small, about 777 each.",
                    "question": "Are values in thousands?",
                },
                {"code": "invented", "why_it_matters": "x", "question": "y"},
            ]
        }
    )
    out = explain(groups, llm)
    assert set(out["explanations"]) == {"tiv_units"}
    assert "777" in out["explanations"]["tiv_units"]["unsupported_figures"]
    schema = llm.calls[0][2]["properties"]["items"]["items"]["properties"]
    assert set(schema) == {
        "code",
        "why_it_matters",
        "question",
    }  # no field for a value or a fix


# 6 · Ask the results --------------------------------------------------------------------------------------------------
FACTS = [
    {
        "label": "Scenario 1-in-100",
        "text": "occasional hazard tier, assumed 1-in-100 year event: loss KES 1.20 bn",
        "provenance": "ASSUMPTION",
    },
    {
        "label": "Average annual loss",
        "text": "average annual loss KES 85.0 m",
        "provenance": "ASSUMPTION",
    },
]


def test_ask_answers_from_cited_facts_and_flags_invented_figures(config):
    from floodcat.ai.ask import ask, method_facts

    facts = FACTS + method_facts(config)
    llm = FakeLLM(
        {
            "answerable": True,
            "answer": "The 1-in-100 loss is KES 1.20 bn, about 4.4% of value.",
            "fact_labels": ["Scenario 1-in-100", "Made up"],
            "chart": "loss_curve",
        }
    )
    out = ask("What is the 1-in-100 loss? email me at a@b.com", facts, llm)
    assert (
        out["fact_labels"] == ["Scenario 1-in-100"]
        and out["provenance"] == ["ASSUMPTION"]
        and out["chart"] == "loss_curve"
    )
    assert out["unsupported_figures"] == ["4.4"] and "a@b.com" not in llm.calls[0][1]
    assert '"What is the 1-in-100 loss?' in llm.calls[0][1]


def test_ask_without_cited_facts_is_not_answerable(config):
    from floodcat.ai.ask import ask

    out = ask(
        "Will it rain tomorrow?",
        FACTS,
        FakeLLM(
            {
                "answerable": True,
                "answer": "Probably.",
                "fact_labels": [],
                "chart": "weird",
            }
        ),
    )
    assert not out["answerable"] and out["chart"] == "none"
    with pytest.raises(ModelError):
        ask("", FACTS, FakeLLM({}))
    with pytest.raises(ModelError):
        ask("x" * 501, FACTS, FakeLLM({}))
    with pytest.raises(ModelError):
        ask("ok", FACTS, FakeLLM({"answer": ""}))


def test_method_facts_keep_tier_mapping_and_score_wording(config):
    from floodcat.ai.ask import method_facts

    text = " ".join(f["text"] for f in method_facts(config))
    assert (
        "extreme = 1-in-10" in text
        and "common = 1-in-250" in text
        and "not a depth" in text
        and "not confidence intervals" in text
    )


# 7 · Referral and quote memo ------------------------------------------------------------------------------------------
def recommendation():
    from test_underwriting import RULES, report
    from floodcat.underwriting.decision import recommend

    return recommend(report(), 2_500_000, 10, RULES)


def test_memo_cannot_change_the_outcome_and_checks_figures():
    from floodcat.ai.memo import SCHEMA, draft, to_docx, to_markdown

    assert not {"outcome", "share", "premium", "recommended_share_pct"} & set(
        SCHEMA["properties"]
    )
    llm = FakeLLM(
        {
            "subject": "Referral: Nairobi flood risk",
            "paragraphs": [
                "The rules recommend accepting at 10%.",
                "We could take 35% instead.",
            ],
            "open_questions": ["Can the broker confirm GPS points?"],
        }
    )
    memo = draft(recommendation(), llm, "referral", note="Broker is jane@broker.co.ke")
    assert memo["outcome"] == "accept" and "35" in memo["unsupported_figures"]
    assert (
        "jane@broker.co.ke" not in llm.calls[0][1]
        and "referral note" in llm.calls[0][0]
    )
    assert "Open questions" in to_markdown(memo) and to_docx(memo)[:2] == b"PK"
    with pytest.raises(ModelError):
        draft(recommendation(), llm, "bind")
    with pytest.raises(ModelError):
        draft(recommendation(), FakeLLM({"subject": ""}), "quote")


# 8 · Public risk explainer --------------------------------------------------------------------------------------------
def test_public_note_uses_hazard_only_and_checks_both_languages(config):
    from floodcat.ai.public_note import build_facts, draft, review, to_markdown

    facts, profile = build_facts(
        "Donholm", -1.30, 36.89, EastProvider(), config, {"flagged_any_tier": True}
    )
    text = " ".join(f["text"] for f in facts)
    assert (
        "KES" not in text
        and "insured" not in text
        and "not a depth" in text
        and "drains" in text
    )
    assert profile["flagged_pct"][TIERS[0]] <= profile["flagged_pct"][TIERS[-1]]
    pct = profile["flagged_pct"][TIERS[-1]]
    response = {
        "english": {
            "title": "Flood risk in Donholm",
            "paragraphs": [
                f"In the 1-in-250 year scenario {pct}% of the ground is flagged."
            ],
        },
        "kiswahili": {
            "title": "Hatari ya mafuriko Donholm",
            "paragraphs": [
                f"Katika hali ya 1-in-250, asilimia {pct} ya ardhi, na 63 zaidi."
            ],
        },
    }
    note = draft("Donholm", -1.30, 36.89, EastProvider(), config, FakeLLM(response))
    assert (
        note["status"] == "draft"
        and note["unsupported_figures"]["english"] == []
        and "63" in note["unsupported_figures"]["kiswahili"]
    )
    with pytest.raises(ModelError):
        review(note, "Amina")  # unsupported figure blocks confirmation
    clean = {**note, "unsupported_figures": {"english": [], "kiswahili": []}}
    with pytest.raises(ModelError):
        review(clean, "  ")
    reviewed = review(clean, "Amina")
    assert (
        reviewed["status"] == "reviewed"
        and "checked by Amina" in to_markdown(reviewed)
        and "DRAFT" in to_markdown(note)
    )


# Config -----------------------------------------------------------------------------------------------------------------
def test_stored_assumption_sets_without_new_sections_still_load(config):
    stored = {
        k: v
        for k, v in config.to_dict().items()
        if k not in ("drainage_model", "evidence_harvest", "public_notes")
    }
    assert ModelConfig(**merge_defaults(stored)).drainage_model == config.drainage_model


@pytest.mark.parametrize(
    "change",
    [
        {"drainage_model": {"weight": 2}},
        {"evidence_harvest": {"timespan": "forever"}},
        {"quality_checks": {"tiv_ratio_band": [12, 8]}},
        {"building_attributes": {"storey_height_m": 0}},
        {"drainage_model": {"probability_threshold": 1.0}},
    ],
)
def test_invalid_ai_settings_are_rejected(config, change):
    ((section, values),) = change.items()
    with pytest.raises(ModelError):
        config.replace(**{section: {**config.to_dict()[section], **values}})
