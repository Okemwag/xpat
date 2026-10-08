"""Rebuild the Day 1 outputs (hazard → vulnerability → exposure → financial engine).

Usage: uv run --extra geo python scripts/build_day1_outputs.py [--config PATH]

Hazard is read from the five GeoTIFFs (raster lookup) and checked against the scores
pre-attached in exposure_nairobi_with_hazard.csv; the run fails if they disagree.
"""

import argparse
import csv
import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from floodcat.core.config import load_config
from floodcat.core.constants import TIERS, CLASSES
from floodcat.core.errors import ModelError
from floodcat.exposure.loaders import read_csv
from floodcat.exposure.validation import validate_rows
from floodcat.hazard.hotspots import load_hotspots, hotspot_check, nearest_hotspot
from floodcat.hazard.raster import RasterHazard
from floodcat.services.analysis import analyse
from floodcat.services.sensitivity import assumption_sensitivity
from floodcat.financial.uncertainty import uncertainty_ranges
from floodcat.financial.ylt import ylt_for_report
from floodcat.vulnerability.functions import matrix

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "outputs"
EXPOSURE = DATA / "exposure_nairobi_with_hazard.csv"
HOTSPOTS = DATA / "nairobi_hotspots_geocoded.csv"
LOOKUP_TOLERANCE = 1e-9


def kes(value):
    return f"KES {Decimal(value):,.0f}"


def write_csv(name, rows):
    with open(OUT / name, "w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def md_table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(
        lines + ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config")
    args = parser.parse_args()
    config = load_config(args.config)
    OUT.mkdir(exist_ok=True)
    rows = read_csv(EXPOSURE)
    assets, _ = validate_rows(rows)
    hotspots = load_hotspots(HOTSPOTS)

    with RasterHazard(DATA) as rasters:
        # Step 1 — hazard: raster lookup per building, checked against the attached scores.
        lookup, worst = [], 0.0
        for asset in assets:
            scores = rasters.scores(asset)
            if any(scores[t] is None for t in TIERS):
                raise ModelError(
                    "hazard_unavailable", f"{asset.loc_id} lies outside raster coverage"
                )
            diff = max(abs(scores[t] - asset.hazard[t]) for t in TIERS)
            worst = max(worst, diff)
            lookup.append(
                {
                    "loc_id": asset.loc_id,
                    "lat": asset.lat,
                    "lon": asset.lon,
                    "housing_class": asset.housing_class,
                    **{f"raster_score_{t}": scores[t] for t in TIERS},
                    "max_abs_diff_vs_attached": diff,
                    **nearest_hotspot(asset.lat, asset.lon, hotspots, config),
                    "synthetic": asset.synthetic,
                    "source": asset.source,
                }
            )
        if worst > LOOKUP_TOLERANCE:
            raise ModelError(
                "raster_mismatch",
                f"Raster lookup differs from attached scores by {worst}",
            )
        check = hotspot_check(hotspots, rasters)
        report = analyse(rows, config, rasters, hotspots=hotspots, allow_partial=False)
    sensitivity = assumption_sensitivity(rows, config)
    sim = uncertainty_ranges(report, rows, config)["baseline"]["gross"]
    ylt = ylt_for_report(report, rows, config)["baseline"]["gross"]

    write_csv("nairobi_hazard_lookup.csv", lookup)
    write_csv(
        "nairobi_hotspot_check.csv",
        [
            {
                **{k: p[k] for k in ("name", "lat", "lon")},
                **{f"score_{t}": p[t] for t in TIERS},
                "flagged_any_tier": p["flagged_any_tier"],
            }
            for p in check["points"]
        ],
    )
    vm = matrix(config)
    write_csv(
        "nairobi_vulnerability_matrix.csv",
        [
            {
                "severity_score": s,
                "assumed_depth_m": d,
                **{c: round(vm["damage_ratio"][c][i], 4) for c in CLASSES},
            }
            for i, (s, d) in enumerate(zip(vm["scores"], vm["assumed_depth_m"]))
        ],
    )
    run = report["runs"]["baseline"]
    who_pays = "Policy terms and reinsurance are off in this configuration."
    if "insured" in run:
        ins = {p["tier"]: p["loss_kes"] for p in run["insured"]["ep_curve"]}
        split = {t["tier"]: t for t in run["reinsurance"]["by_tier"]} if "reinsurance" in run else {}
        terms = run["insured"]["terms"]
        header = ["Return period", "Ground-up loss", "Gross loss"] + (["Reinsurance recoveries", "Net loss"] if split else [])
        rows_ = [
            [f"1-in-{p['return_period_years']:g}", kes(p["loss_kes"]), kes(ins[p["tier"]])]
            + ([kes(split[p["tier"]]["ceded"]), kes(split[p["tier"]]["net"])] if split else [])
            for p in run["ep_curve"]
        ]
        rows_.append(["AAL", kes(run["aal"]["aal_kes"]), kes(run["insured"]["aal"]["aal_kes"])]
                     + ([kes(run["reinsurance"]["ceded"]["aal"]["aal_kes"]), kes(run["reinsurance"]["net"]["aal"]["aal_kes"])] if split else []))
        who_pays = (f"Gross loss = ground-up loss after a {terms['deductible_pct_of_tiv']:.0%} deductible per property (limit "
                    f"{terms['limit_pct_of_tiv']:.0%} of value). ")
        if split:
            st_ = run["reinsurance"]["structure"]
            who_pays += (f"Net loss = gross loss after an illustrative programme: {st_['quota_share_cession']:.0%} quota share, then a catastrophe excess of loss of "
                         f"{kes(st_['xol_limit_kes'])} above {kes(st_['xol_retention_kes'])} per catastrophe on the insurer's share. "
                         "Not a real treaty; no reinstatements, aggregate covers or second events in a year.")
        who_pays += "\n\n" + md_table(header, rows_)
    write_csv(
        "nairobi_property_losses.csv",
        [
            {"tier": t, "return_period_years": config.return_periods[t], **row}
            for t in TIERS
            for row in run["property_losses"][t]
        ],
    )
    write_csv(
        "nairobi_ep_curve.csv",
        [
            {
                k: p[k]
                for k in (
                    "tier",
                    "return_period_years",
                    "annual_exceedance_probability",
                    "loss_kes",
                    "loss_pct_of_tiv",
                )
            }
            for p in run["ep_curve"]
        ],
    )
    write_csv(
        "nairobi_accumulation.csv",
        [
            {
                "tier": t,
                "return_period_years": config.return_periods[t],
                "dimension": dim,
                **item,
            }
            for t in TIERS
            for dim in ("construction", "hotspot_area", "geographic_grid")
            for item in run["breakdowns"][t][dim]
        ],
    )
    write_csv(
        "nairobi_sensitivity.csv",
        [
            {
                "case": case,
                **{f"loss_{t}_kes": v["loss_kes_by_tier"][t] for t in TIERS},
                "aal_kes": v["aal_kes"],
            }
            for case, v in sensitivity["cases"].items()
        ],
    )

    write_csv("nairobi_ylt_ep_curve.csv", ylt["curve"])
    write_csv(
        "nairobi_uncertainty_ranges.csv",
        [{"tier": t, **v} for t, v in sim["by_tier"].items()]
        + [{"tier": "aal", "return_period_years": "", **sim["aal"]}],
    )
    tiv = Decimal(report["modelled_tiv_kes"])
    curve = {p["tier"]: p for p in run["ep_curve"]}
    rp100 = next(t for t in TIERS if config.return_periods[t] == 100.0)
    rarest = TIERS[-1]
    tagged = sum(r["within_hotspot_radius"] for r in lookup)
    md = f"""# Nairobi flood model — Day 1 results

Generated {date.today().isoformat()} by `scripts/build_day1_outputs.py`. Config `{
        config.version
    }` (fingerprint `{config.fingerprint[:12]}`).

> **Every number here is illustrative.** The 600 properties are SYNTHETIC, the hazard is a PROXY, and the return periods,
> score-to-depth conversion and class adjustments are ASSUMPTIONS. Nothing is calibrated to Kenyan claims.

## Inputs

| File | Label | SHA-256 |
|---|---|---|
| `data/exposure_nairobi_with_hazard.csv` | SYNTHETIC exposure | `{
        sha256(EXPOSURE)[:16]
    }…` |
| `data/nairobi_pluvial_proxy_*.tif` (5) | PROXY hazard | read directly |
| `data/nairobi_hotspots_geocoded.csv` | REAL names, approximate points | `{
        sha256(HOTSPOTS)[:16]
    }…` |

## Headline (ground-up loss)

{
        md_table(
            ["Measure", "Value", "Plain English"],
            [
                [
                    "Total insured value",
                    kes(tiv),
                    f"{report["modelled_count"]} synthetic properties",
                ],
                [
                    f"1-in-{config.return_periods[rp100]:g} loss",
                    kes(curve[rp100]["loss_kes"]),
                    f"{curve[rp100]["loss_pct_of_tiv"]:.2f}% of value; a loss this size or larger has an assumed 1% chance each year",
                ],
                [
                    f"1-in-{config.return_periods[rarest]:g} loss",
                    kes(curve[rarest]["loss_kes"]),
                    f"{curve[rarest]["loss_pct_of_tiv"]:.2f}% of value; assumed 0.4% chance each year",
                ],
                [
                    "Average annual loss",
                    kes(run["aal"]["aal_kes"]),
                    "Long-run yearly average implied by the curve and the AAL assumptions",
                ],
            ],
        )
    }

## Loss by return period (EP curve)

{
        md_table(
            ["Tier", "Return period", "Annual chance", "Loss", "% of TIV"],
            [
                [
                    p["tier"],
                    f"1-in-{p['return_period_years']:g}",
                    f"{p['annual_exceedance_probability']:.1%}",
                    kes(p["loss_kes"]),
                    f"{p['loss_pct_of_tiv']:.2f}%",
                ]
                for p in run["ep_curve"]
            ],
        )
    }

Tier names describe how extreme a cell is, not how often it floods: `extreme` keeps the top 5% of cells (narrowest
footprint, most frequent event); `common` keeps the top 40% (widest footprint, rarest event).

## Ground-up, gross and net loss (ASSUMPTION terms)

{who_pays}

## EP curve from {ylt["years"]:,} simulated years

{
        md_table(
            [
                "Rarity",
                "Loss",
                f"Simulation range ({ylt['band_pct'][0]:g}–{ylt['band_pct'][1]:g}th pct)",
                "Modelled from",
            ],
            [
                [
                    f"1-in-{p['return_period_years']:,.0f}",
                    kes(p["loss_kes"]),
                    f"{kes(p['band_low_kes'])} – {kes(p['band_high_kes'])}",
                    "hazard tiers"
                    if p["return_period_years"] <= ylt["rarest_modelled_return_period"]
                    else "damage uncertainty only",
                ]
                for p in ylt["table"]
            ],
        )
    }

Average annual loss from the simulation: {kes(ylt["aal"]["aal_kes"])} (range {
        kes(ylt["aal"]["band_low_kes"])
    } – {kes(ylt["aal"]["band_high_kes"])});
{ylt["zero_loss_years"]:,} of {
        ylt[
            "years"
        ]:,} years have no loss. Each simulated year draws its rarity and one damage-uncertainty
trial, and reads the loss between the five scenario points (linear in annual chance). {
        ylt["note"]
    }

## Likely ranges per scenario (damage-ratio uncertainty, ASSUMPTION)

{
        md_table(
            [
                "Return period",
                f"{sim['interval_pct'][0]:g}th pct",
                "Median",
                f"{sim['interval_pct'][1]:g}th pct",
            ],
            [
                [
                    f"1-in-{v['return_period_years']:g}",
                    kes(v["p_low_kes"]),
                    kes(v["median_kes"]),
                    kes(v["p_high_kes"]),
                ]
                for v in sim["by_tier"].values()
            ]
            + [
                [
                    "Average annual loss",
                    kes(sim["aal"]["p_low_kes"]),
                    kes(sim["aal"]["median_kes"]),
                    kes(sim["aal"]["p_high_kes"]),
                ]
            ],
        )
    }

{
        sim[
            "trials"
        ]:,} simulations; each property's damage ratio varies around its curve with log-spread σ={
        sim["damage_sigma"]:g}, of which a
share ρ={sim["correlation"]:g} is common to the whole portfolio. {sim["note"]}

## Loss by housing class (1-in-{config.return_periods[rp100]:g})

{
        md_table(
            ["Class", "Properties", "Insured value", "Loss", "Share of loss"],
            [
                [
                    i["id"],
                    i["property_count"],
                    kes(i["tiv_kes"]),
                    kes(i["loss_kes"]),
                    f"{i['loss_share_pct']:.1f}%",
                ]
                for i in run["breakdowns"][rp100]["construction"]
            ],
        )
    }

## Accumulation near named hotspots (1-in-{config.return_periods[rp100]:g})

Each property is tagged with its nearest named hotspot; it is grouped under that hotspot only within
{config.hotspot_tag_radius_m:g} m ({tagged} of {
        len(lookup)
    } properties). Every property belongs to exactly one group.

{
        md_table(
            ["Area", "Properties", "Insured value", "Loss", "Share of loss"],
            [
                [
                    i["id"],
                    i["property_count"],
                    kes(i["tiv_kes"]),
                    kes(i["loss_kes"]),
                    f"{i['loss_share_pct']:.1f}%",
                ]
                for i in run["breakdowns"][rp100]["hotspot_area"][: config.top_n]
            ],
        )
    }

## Top {config.top_n} properties by loss (1-in-{config.return_periods[rarest]:g})

{
        md_table(
            [
                "Property",
                "Class",
                "Insured value",
                "Score",
                "Assumed depth",
                "Damage",
                "Loss",
                "Nearest hotspot",
            ],
            [
                [
                    r["loc_id"],
                    r["housing_class"],
                    kes(r["tiv_kes"]),
                    f"{r['hazard_score']:.3f}",
                    f"{r['assumed_depth_m']:.2f} m",
                    f"{r['damage_ratio']:.1%}",
                    kes(r["loss_kes"]),
                    f"{r['nearest_hotspot']} ({r['hotspot_distance_m'] / 1000:.1f} km)",
                ]
                for r in run["breakdowns"][rarest]["top_properties"]
            ],
        )
    }

## Hazard checks

- Raster lookup reproduces the attached scores for all {
        len(lookup)
    } properties (largest difference {worst:.1e}).
- Named hotspots flagged (score > 0): **{check["flagged_any_tier"]} of {
        check["hotspot_count"]
    }** in any tier; by tier
  {
        ", ".join(f"{t} {n}" for t, n in check["flagged_by_tier"].items())
    }. The misses are drainage-driven areas the proxy cannot see.
- {sum(all(r[f"raster_score_{t}"] == 0 for t in TIERS) for r in lookup)} of {
        len(lookup)
    } properties score zero in every tier and so carry
  no modelled loss. Zero means "not flagged by this proxy", not "cannot flood".

## Vulnerability

Base curve: {config.vulnerability_source}.

{
        md_table(
            ["JRC depth (m)"] + [f"{d:g}" for d in config.jrc_depth_m],
            [["Damage factor"] + [f"{v:.2f}" for v in config.jrc_damage_factor]],
        )
    }

{
        md_table(
            ["Class", "JRC depth scale", "Damage cap", "Meaning"],
            [
                [
                    c,
                    f"{a['jrc_depth_scale']:g}",
                    f"{a['damage_cap']:.0%}",
                    f"reaches the JRC damage for depth d at {a['jrc_depth_scale']:g}·d",
                ]
                for c, a in config.class_adjustments.items()
            ],
        )
    }

Vulnerability matrix at max depth {config.max_depth_m:g} m (damage ratio):

{
        md_table(
            ["Score", "Assumed depth"] + list(CLASSES),
            [
                [f"{s:g}", f"{d:.2f} m"]
                + [f"{vm['damage_ratio'][c][i]:.1%}" for c in CLASSES]
                for i, (s, d) in enumerate(zip(vm["scores"], vm["assumed_depth_m"]))
            ],
        )
    }

## Assumptions

{
        md_table(
            ["Assumption", "Value", "Label"],
            [
                [
                    "Tier → return period",
                    ", ".join(f"{t} {config.return_periods[t]:g} yr" for t in TIERS),
                    "ASSUMPTION",
                ],
                [
                    "Score → depth",
                    f"depth = score × {config.max_depth_m:g} m (pluvial base case)",
                    "ASSUMPTION",
                ],
                ["Class depth scales and caps", "see Vulnerability", "ASSUMPTION"],
                [
                    "AAL",
                    f"trapezoid over annual chance; zero loss at 1-in-{config.aal_zero_loss_return_period:g}; rarest loss held beyond 1-in-{config.return_periods[rarest]:g}",
                    "ASSUMPTION",
                ],
                [
                    "Insured value",
                    "supplied `tiv_kes` used as is (≈10× floor area × cost/m²; flagged on every row)",
                    "SYNTHETIC",
                ],
                [
                    "Policy terms",
                    "none: gross loss = insured value × damage ratio",
                    "ASSUMPTION",
                ],
            ],
        )
    }

## Sensitivity (assumption scenarios, not confidence intervals)

{
        md_table(
            ["Case"] + [f"1-in-{config.return_periods[t]:g}" for t in TIERS] + ["AAL"],
            [
                [case]
                + [kes(v["loss_kes_by_tier"][t]) for t in TIERS]
                + [kes(v["aal_kes"])]
                for case, v in sensitivity["cases"].items()
            ],
        )
    }

## Limitations

{chr(10).join("- " + item for item in report["limitations"])}

## Files

`nairobi_hazard_lookup.csv`, `nairobi_hotspot_check.csv`, `nairobi_vulnerability_matrix.csv`, `nairobi_property_losses.csv`,
`nairobi_ep_curve.csv`, `nairobi_accumulation.csv`, `nairobi_sensitivity.csv`, `nairobi_uncertainty_ranges.csv`, `nairobi_ylt_ep_curve.csv`.
"""
    (OUT / "nairobi_day1_results.md").write_text(md)
    print(f"Wrote outputs to {OUT}")


if __name__ == "__main__":
    main()
