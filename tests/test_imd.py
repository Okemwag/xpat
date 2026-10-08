"""Infrastructure & Maintenance Deficit index: geometry, grid, index, uplift, config and the analysis wiring."""

from decimal import Decimal
from types import SimpleNamespace
import numpy as np
import pytest
from floodcat.core.config import ModelConfig, load_config, upgrade
from floodcat.core.constants import TIERS
from floodcat.core.errors import ModelError
from floodcat.financial.loss import total_loss
from floodcat.hazard.hotspots import Hotspot
from floodcat.hazard.imd import (
    Grid,
    ImdGrid,
    accumulate,
    area_comparison,
    footprint,
    hotspot_comparison,
    index_value,
    neighbourhood,
    scale,
    uplift,
)
from floodcat.services.analysis import analyse
from conftest import row

CELL = 3 / 3600


def square(lat, lon, side_m):
    dlat = side_m / 110_574.0
    dlon = side_m / (111_320.0 * np.cos(np.radians(lat)))
    return [(lat, lon), (lat + dlat, lon), (lat + dlat, lon + dlon), (lat, lon + dlon), (lat, lon)]


def fake_grid(built=0.0, density=0.0, west=36.6, north=-1.1, width=480, height=420):
    grid = Grid(west, north, CELL, width, height)
    bands = {"built_fraction": np.full((height, width), built), "buildings_per_ha": np.full((height, width), density)}
    return ImdGrid(bands, grid, {"source": "test"})


def enabled(config, **changes):
    return config.replace(imd_index={**config.imd_index, "enabled": True, **changes})


# Geometry and grid -----------------------------------------------------------------------------------------------
def test_footprint_area_and_centroid_of_a_square():
    area, (lat, lon) = footprint(square(-1.3, 36.8, 10))
    assert area == pytest.approx(100, rel=0.005)
    assert lat == pytest.approx(-1.3 + 5 / 110_574.0, abs=1e-7)
    assert lon > 36.8


def test_footprint_accepts_overpass_dicts_and_rejects_degenerate_rings():
    ring = [{"lat": a, "lon": b} for a, b in square(-1.3, 36.8, 20)]
    assert footprint(ring)[0] == pytest.approx(400, rel=0.005)
    assert footprint([(-1.3, 36.8), (-1.3, 36.8001), (-1.3, 36.8)]) is None
    assert footprint([(-1.3, 36.8), (-1.3, 36.8001), (-1.3, 36.8002), (-1.3, 36.8)]) is None  # collinear


def test_grid_index_uses_floor_rule_and_rejects_off_grid_points():
    g = Grid(36.6, -1.1, CELL, 10, 10)
    assert g.index(-1.1 - CELL * 0.5, 36.6 + CELL * 0.5) == (0, 0)
    assert g.index(-1.1 - CELL * 2.5, 36.6 + CELL * 3.5) == (2, 3)
    assert g.index(-1.0, 36.6) is None and g.index(-1.1 - CELL * 0.5, 36.59) is None
    assert Grid.covering(36.6, -1.45, 37.0, -1.1, CELL).width == 480


def test_neighbourhood_of_uniform_buildings_recovers_fraction_and_density():
    g = Grid(36.6, -1.1, CELL, 40, 40)
    cw, ch = g.cell_size_m()
    area = np.full((40, 40), 0.3 * cw * ch)  # 30% of every cell roofed
    count = np.full((40, 40), 2.0)
    comp = neighbourhood(area, count, g, 250)
    assert comp["built_fraction"][20, 20] == pytest.approx(0.3)
    assert comp["buildings_per_ha"][20, 20] == pytest.approx(2 / (cw * ch / 10_000))
    assert comp["built_fraction"][0, 0] < 0.3  # beyond the edge counts as empty, never invented


def test_accumulate_assigns_by_centroid():
    g = Grid(36.6, -1.1, CELL, 10, 10)
    fp = footprint(square(-1.1 - CELL * 1.2, 36.6 + CELL * 4.2, 15))
    area, count = accumulate([fp, fp], g)
    assert count.sum() == 2 and count[1, 4] == 2 and area[1, 4] == pytest.approx(2 * fp[0])


# Index and uplift ------------------------------------------------------------------------------------------------
def test_scale_and_index_are_bounded_and_zero_below_thresholds(config):
    s = config.imd_index
    assert scale(0.1, 0.15, 0.45) == 0 and scale(0.3, 0.15, 0.45) == pytest.approx(0.5) and scale(0.9, 0.15, 0.45) == 1
    assert index_value({"built_fraction": 0.1, "buildings_per_ha": 10}, s)[0] == 0
    assert index_value({"built_fraction": 0.9, "buildings_per_ha": 500}, s)[0] == 1
    mid, parts = index_value({"built_fraction": 0.30, "buildings_per_ha": 75}, s)
    assert mid == pytest.approx(0.5) and parts == {"built_fraction": pytest.approx(0.5), "buildings_per_ha": pytest.approx(0.5)}


def test_uplift_never_lowers_scores_keeps_tier_order_and_is_identity_at_zero(config):
    s = config.imd_index
    terrain = dict(zip(TIERS, (0.0, 0.0, 0.1, 0.2, 0.3)))
    assert uplift(terrain, 0.0, s) == terrain
    for idx in (0.25, 0.5, 1.0):
        out = uplift(terrain, idx, s)
        assert all(out[t] >= terrain[t] for t in TIERS)
        assert [out[t] for t in TIERS] == sorted(out[t] for t in TIERS)
    dry = uplift(dict.fromkeys(TIERS, 0.0), 1.0, s)
    assert dry["common"] == pytest.approx(s["weight"] * s["tier_factors"]["common"])
    with pytest.raises(ModelError):
        uplift(terrain, 1.5, s)


# Config ---------------------------------------------------------------------------------------------------------
def test_config_rejects_bad_index_settings(config):
    s = config.imd_index
    for bad in (
        {**s, "tier_factors": {**s["tier_factors"], "extreme": 0.9}},
        {**s, "built_fraction_range": [0.5, 0.2]},
        {**s, "component_weights": {"built_fraction": 0, "buildings_per_ha": 0}},
        {**s, "weight": 1.5},
        {k: v for k, v in s.items() if k != "weight"},
    ):
        with pytest.raises(ModelError):
            config.replace(imd_index=bad)


def test_shipped_index_thresholds_are_the_pre_registered_values(config):
    """Changing these after looking at the hotspot results would make the hit-rate check circular."""
    s = config.imd_index
    assert s["built_fraction_range"] == (0.15, 0.45) and s["density_per_ha_range"] == (25.0, 125.0)
    assert s["window_radius_m"] == 250 and s["weight"] == 0.4


def test_assumption_sets_saved_before_the_index_upgrade_with_it_switched_off(config):
    legacy = {k: v for k, v in config.to_dict().items() if k != "imd_index"}
    with pytest.raises(TypeError):
        ModelConfig(**legacy)
    upgraded = ModelConfig(**upgrade(legacy))
    assert upgraded.imd_index["enabled"] is False


# Analysis wiring -------------------------------------------------------------------------------------------------
def test_disabled_index_leaves_results_unchanged(starter_rows, config):
    a = analyse(starter_rows, config)
    b = analyse(starter_rows, config, imd=fake_grid(0.9, 500))
    assert a["runs"]["baseline"]["ep_curve"] == b["runs"]["baseline"]["ep_curve"]
    assert b["imd_adjustment"] == {"enabled": False}


def test_enabled_index_without_grid_fails_loudly(starter_rows, config):
    with pytest.raises(ModelError) as exc:
        analyse(starter_rows, enabled(config))
    assert exc.value.code == "missing_imd_grid"


def test_enabled_index_raises_losses_and_keeps_model_invariants(starter_rows, config):
    cfg = enabled(config)
    before = analyse(starter_rows, cfg.replace(imd_index={**cfg.imd_index, "enabled": False}))
    report = analyse(starter_rows, cfg, imd=fake_grid(0.30, 75))
    base = report["runs"]["baseline"]
    losses = [Decimal(p["loss_kes"]) for p in base["ep_curve"]]
    assert losses == sorted(losses)
    for t in TIERS:
        rows = base["property_losses"][t]
        assert total_loss(rows) >= total_loss(before["runs"]["baseline"]["property_losses"][t])
        assert all(r["hazard_score"] >= r["terrain_score"] and r["imd_index"] == 0.5 for r in rows)
        assert all("synthetic" in r for r in rows)
    imd = report["imd_adjustment"]
    assert imd["enabled"] and imd["changed_properties"] == report["modelled_count"]
    assert imd["terrain_only_loss_kes"] == {p["tier"]: p["loss_kes"] for p in before["runs"]["baseline"]["ep_curve"]}
    assert Decimal(imd["aal_delta_kes"]) > 0
    assert any(p["component"] == "infrastructure_deficit_index" for p in report["provenance"])


def test_dry_point_is_flagged_only_where_the_index_is_above_zero(config):
    cfg = enabled(config)
    dry = [row(scores=(0, 0, 0, 0, 0))]
    assert analyse(dry, cfg, imd=fake_grid(0.05, 5))["runs"]["baseline"]["ep_curve"][-1]["loss_kes"] == "0.00"
    wet = analyse(dry, cfg, imd=fake_grid(0.45, 125))["runs"]["baseline"]["property_losses"]["common"][0]
    assert wet["hazard_score"] == pytest.approx(cfg.imd_index["weight"]) and Decimal(wet["loss_kes"]) > 0


def test_ai_evidence_applies_on_top_of_the_index(starter_rows, config):
    report = analyse(starter_rows, enabled(config), imd=fake_grid(0.3, 75), ai_adjustment=True)
    assert report["imd_adjustment"]["enabled"] and report["ai_contribution"]["enabled"]
    assert report["runs"]["enhanced"]["ep_curve"] == report["runs"]["baseline"]["ep_curve"]  # no evidence supplied


# Hotspot check ---------------------------------------------------------------------------------------------------
class Provider:
    def __init__(self, wet):
        self.wet = wet

    def scores(self, asset):
        return dict.fromkeys(TIERS, 0.3 if asset.lon in self.wet else 0.0)


def test_hotspot_comparison_reports_before_after_and_misses(config):
    s = config.imd_index
    hs = [Hotspot("A", -1.2, 36.7), Hotspot("B", -1.3, 36.8), Hotspot("C", -1.31, 36.81)]
    imd = fake_grid()
    rc = imd.grid.index(-1.3, 36.8)
    imd.bands["built_fraction"][rc] = 0.45
    imd.bands["buildings_per_ha"][rc] = 125
    out = hotspot_comparison(hs, Provider({36.7}), imd, s)
    assert (out["flagged_terrain_only"], out["flagged_with_index"]) == (1, 2)
    assert out["newly_flagged"] == ["B"] and out["still_missed"] == ["C"]


def test_area_comparison_counts_flagged_share_of_the_map(config):
    s = config.imd_index
    imd = fake_grid(width=4, height=4)
    imd.bands["built_fraction"][0, 0] = 0.45
    terrain_grid = Grid(36.6, -1.1, CELL / 3, 12, 12)
    terrain = np.zeros((12, 12)); terrain[11, 11] = 0.2
    out = area_comparison(terrain, terrain_grid, imd, s)
    assert out["share_flagged_terrain_only"] == pytest.approx(1 / 144)
    assert out["share_flagged_with_index"] == pytest.approx(10 / 144)


# Build script: OSM PBF reader -------------------------------------------------------------------------------------
def test_build_script_reads_buildings_from_a_pbf(tmp_path):
    osmium = pytest.importorskip("osmium")
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("build_imd", Path(__file__).resolve().parents[1] / "scripts" / "build_imd_index.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    pbf = tmp_path / "tiny.osm.pbf"
    nodes, ways, nid = [], [], 1
    shapes = [((-1.30, 36.80), "yes"), ((-1.3005, 36.8005), "house"), ((-1.31, 36.81), "no"), ((-1.0, 36.0), "yes")]
    for wid, ((lat, lon), kind) in enumerate(shapes, 1):
        ring = square(lat, lon, 10)[:-1]
        ids = list(range(nid, nid + 4)); nid += 4
        nodes += [osmium.osm.mutable.Node(id=i, location=osmium.osm.Location(b, a), version=1) for i, (a, b) in zip(ids, ring)]
        ways.append(osmium.osm.mutable.Way(id=wid, nodes=ids + ids[:1], tags={"building": kind}, version=1))
    ways.append(osmium.osm.mutable.Way(id=99, nodes=[1, 2, 3, 1], tags={"highway": "service"}, version=1))
    with osmium.SimpleWriter(str(pbf)) as w:
        for n in nodes:
            w.add_node(n)
        for way in ways:
            w.add_way(way)
    g = Grid(36.6, -1.1, CELL, 480, 420)
    area, count, stats = build.read_buildings(pbf, g, lambda m: None)
    assert count.sum() == 2  # building=no, off-grid and non-building ways are left out
    assert area.sum() == pytest.approx(200, rel=0.01)
    assert stats["outside"] == 1
    assert not pbf.with_suffix(".nodes.idx").exists()
