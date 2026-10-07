"""Publish the supplied property-level Nairobi flood severity scores."""

import csv
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "exposure_nairobi_with_hazard.csv"
OUTPUT = ROOT / "outputs"
TIERS = ("common", "occasional", "moderate", "severe", "extreme")
COLUMNS = ("loc_id", "lat", "lon", *(f"hazard_score_{tier}" for tier in TIERS))


def main() -> None:
    with SOURCE.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("The prepared exposure file is empty")

    seen = set()
    for row in rows:
        if any(not row.get(column) for column in COLUMNS):
            raise ValueError(f"Missing output field for {row.get('loc_id', 'unknown row')}")
        if row["loc_id"] in seen:
            raise ValueError(f"Duplicate location ID: {row['loc_id']}")
        seen.add(row["loc_id"])
        values = [Decimal(row[f"hazard_score_{tier}"]) for tier in reversed(TIERS)]
        if any(value < 0 or value > 1 for value in values):
            raise ValueError(f"Score outside 0–1 for {row['loc_id']}")
        if any(left > right for left, right in zip(values, values[1:])):
            raise ValueError(f"Tier ordering is inconsistent for {row['loc_id']}")

    OUTPUT.mkdir(exist_ok=True)
    csv_path = OUTPUT / "nairobi_flood_severity.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({column: row[column] for column in COLUMNS} for row in rows)

    lines = [
        "# Nairobi flood severity dataset",
        "",
        f"**Coverage:** {len(rows)} synthetic Nairobi properties, each with five supplied hazard scores.",
        "**Source:** `data/exposure_nairobi_with_hazard.csv`. The values below are copied without transformation.",
        "The [CSV version](nairobi_flood_severity.csv) contains the same table for analysis.",
        "",
        "## What the values mean",
        "",
        "Each score is a **unitless, relative flood-susceptibility value from 0 to 1** for that property and supplied tier. A larger value means the supplied terrain/river proxy indicates stronger susceptibility. A value of **0** means the proxy did not flag the property in that tier; it does not prove the location cannot flood. **1** is the upper end of the index; it is not one metre of water, a 100% chance of flooding, or an observed flood depth.",
        "",
        "The supplied tier names are `common`, `occasional`, `moderate`, `severe`, and `extreme`. In these files, the positive footprint becomes narrower in that order. At a given property, `common` is always at least as large as `occasional`, then `moderate`, `severe`, and `extreme`. The names do not themselves establish annual probabilities, return periods, or measured depths. Any return periods used by the prototype loss model are separate assumptions.",
        "",
        "These scores are used **directly** by the baseline vulnerability function; no score-to-metres conversion is applied. The proxy can miss drainage-driven urban flooding. For limitations and validation, see [the full interpretation](../docs/FLOOD_SEVERITY.md).",
        "",
        "## Fields",
        "",
        "| Field | Meaning |",
        "|---|---|",
        "| `loc_id` | Synthetic property identifier. |",
        "| `lat`, `lon` | Property coordinates in decimal degrees. |",
        *(
            f"| `hazard_score_{tier}` | Relative 0–1 flood-susceptibility score for the supplied `{tier}` tier. |"
            for tier in TIERS
        ),
        "",
        "## All property values",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
    ]
    lines.extend("| " + " | ".join(row[column] for column in COLUMNS) + " |" for row in rows)
    (OUTPUT / "nairobi_flood_severity.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
