"""Accumulation: how much loss the organisation would hold in one place if it writes this risk.

Unit: the model's 1 km grid cells (`grid_size_m`, ASSUMPTION), named after the nearest government-named flood area where one
lies within the hotspot radius. For each cell we take the loss at the PML return period the rules use (the tier whose
assumed return period is nearest at or above it) on the same run and basis as the recommendation.

- **This risk:** 100% loss and insured value per cell.
- **Our book:** for every analysis with a recorded *accept* or *smaller share* decision (latest decision per analysis),
  that share of its per-cell loss. Declined risks and deleted analyses do not count.
- **Limit (rule `max_area_pml_kes`):** our share of this risk plus the book in any cell must stay within it, which caps
  the share like the other capacity rules.
- **Warning (rule `max_area_tiv_pct`):** a cell holding more than this share of the submission's insured value is flagged,
  because one local flood would hit much of the risk at once. Only for submissions with more than one property: a
  single-site risk always has 100% in one cell, so it gets a plain note instead (the area limit and the book still apply).

Cells are co-location buckets, not independent events: a single storm can affect several. The figures are as good as the
hazard proxy behind them (no drainage, assumed return periods), which the advice states.
"""

from collections import Counter, defaultdict
from decimal import Decimal
from ..core.constants import TIERS
from ..core.geo import grid_cell


def pml_tier(config, pml_rp):
    """The hazard tier used for the PML loss: the first whose return period is at or above it, else the rarest."""
    rps = config["return_periods"]
    rarer = [t for t in TIERS if rps[t] >= pml_rp]
    return rarer[0] if rarer else TIERS[-1]


def area_exposure(report, run, basis, pml_rp):
    """{cell: {'name', 'tiv', 'loss', 'count'}} at 100% for one analysis (Decimal amounts); empty when the analysis
    carries no per-property losses (e.g. a summary-only record)."""
    config = report.get("config")
    if not config or "property_losses" not in report.get("runs", {}).get(run, {}):
        return {}
    tier = pml_tier(config, pml_rp)
    key = "insured_loss_kes" if basis == "insured" else "loss_kes"
    rows = report["runs"][run]["property_losses"][tier]
    cells = defaultdict(
        lambda: {"tiv": Decimal(0), "loss": Decimal(0), "count": 0, "names": Counter()}
    )
    for r in rows:
        cell = cells[grid_cell(r["lat"], r["lon"], config["grid_size_m"])]
        cell["tiv"] += Decimal(str(r["tiv_kes"]))
        cell["loss"] += Decimal(str(r.get(key, r["loss_kes"])))
        cell["count"] += 1
        if r.get("within_hotspot_radius"):
            cell["names"][r["nearest_hotspot"]] += 1
    return {
        k: {
            "name": (v["names"].most_common(1)[0][0] if v["names"] else None),
            "tiv": v["tiv"],
            "loss": v["loss"],
            "count": v["count"],
        }
        for k, v in cells.items()
    }


def book_exposure(entries):
    """Sum our share of each written analysis per cell. entries: (report, run, basis, pml_rp, share_pct)."""
    book = defaultdict(
        lambda: {"loss": Decimal(0), "tiv": Decimal(0), "risks": 0, "name": None}
    )
    for report, run, basis, pml_rp, share in entries:
        part = Decimal(str(share)) / 100
        for cell, v in area_exposure(report, run, basis, pml_rp).items():
            b = book[cell]
            b["loss"] += v["loss"] * part
            b["tiv"] += v["tiv"] * part
            b["risks"] += 1
            b["name"] = b["name"] or v["name"]
    return dict(book)


def area_label(cell, name):
    return f"{name} area" if name else f"Unnamed area {cell.removeprefix('grid-')}"


def assess(report, run, basis, pml_rp, rules, book=None, share_pct=None, written=0):
    """Per-cell figures, the share cap from the area limit, and warnings in plain words."""
    book = book or {}
    risk = area_exposure(report, run, basis, pml_rp)
    total_tiv = sum((v["tiv"] for v in risk.values()), Decimal(0))
    limit = Decimal(str(rules["max_area_pml_kes"]))
    cap, binding = None, None
    rows = []
    for cell, v in risk.items():
        held = book.get(cell, {}).get("loss", Decimal(0))
        if v["loss"] > 0:
            room = max(Decimal(0), limit - held)
            allowed = float(min(Decimal(100), room / v["loss"] * 100))
            if cap is None or allowed < cap:
                cap, binding = allowed, cell
        else:
            allowed = 100.0
        rows.append(
            {
                "cell": cell,
                "area": area_label(cell, v["name"] or book.get(cell, {}).get("name")),
                "properties": v["count"],
                "tiv_100_kes": v["tiv"],
                "tiv_share_pct": float(v["tiv"] / total_tiv * 100)
                if total_tiv
                else 0.0,
                "loss_100_kes": v["loss"],
                "book_loss_kes": held,
                "book_risks": book.get(cell, {}).get("risks", 0),
                "max_share_pct": allowed,
            }
        )
    rows.sort(key=lambda r: (-(r["loss_100_kes"]), -r["tiv_100_kes"]))
    share = share_pct
    properties = sum(r["properties"] for r in rows)
    for r in rows:
        ours = r["loss_100_kes"] * Decimal(str(share or 0)) / 100
        r["our_loss_kes"] = ours
        r["combined_loss_kes"] = ours + r["book_loss_kes"]
        r["over_limit"] = r["combined_loss_kes"] > limit
        # The rule spreads a schedule across areas; one building is in one place by definition.
        r["concentrated"] = properties > 1 and r["tiv_share_pct"] > rules["max_area_tiv_pct"]
    warnings = []
    if properties == 1 and rows:
        warnings.append(
            {
                "level": "info",
                "area": rows[0]["area"],
                "text": f"{rows[0]['area']}: a single-site risk, so all of it is in one place — normal for one building. "
                "What matters here is the area limit and how much we already hold nearby, both checked below.",
            }
        )
    for r in rows:
        if r["concentrated"]:
            warnings.append(
                {
                    "level": "warning",
                    "area": r["area"],
                    "text": f"{r['area']}: {r['tiv_share_pct']:.0f}% of this risk's insured value sits in one 1 km area "
                    f"(rule: at most {rules['max_area_tiv_pct']:g}%). One local flood would hit most of it at once.",
                }
            )
        if r["book_loss_kes"] > 0 and r["loss_100_kes"] > 0:
            warnings.append(
                {
                    "level": "info" if not r["over_limit"] else "warning",
                    "area": r["area"],
                    "text": f"{r['area']}: we already hold {_kes(r['book_loss_kes'])} of 1-in-{pml_rp:g} loss here from "
                    f"{r['book_risks']} written risk(s); this risk adds {_kes(r['our_loss_kes'])} at the recommended share.",
                }
            )
    if cap is not None and cap < 100:
        b = next(r for r in rows if r["cell"] == binding)
        warnings.insert(
            0,
            {
                "level": "limit",
                "area": b["area"],
                "text": f"{b['area']}: the area limit of {_kes(limit)} at 1-in-{pml_rp:g} allows at most {cap:.1f}% of this risk"
                + (
                    f", because our book already holds {_kes(b['book_loss_kes'])} there."
                    if b["book_loss_kes"] > 0
                    else "."
                ),
            },
        )
    return {
        "pml_return_period": pml_rp,
        "tier": pml_tier(report["config"], pml_rp) if report.get("config") else None,
        "available": bool(risk),
        "limit_kes": limit,
        "max_share_pct": cap,
        "binding_area": next((r["area"] for r in rows if r["cell"] == binding), None),
        "areas": rows,
        "warnings": warnings,
        "book_cells": len(book),
        "book_risks": written,
        "note": "1 km cells are co-location buckets, not independent events; one storm can reach several.",
    }


def _kes(value):
    from .decision import _kes as fmt

    return fmt(value)
