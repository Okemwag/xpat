"""PostgreSQL persistence for immutable runs, reviewed evidence, and spatial inputs."""

import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.numeric import money_string
from ..exposure.loaders import read_csv
from ..exposure.validation import validate_rows
from ..hazard.interpretation import validate_scores


class Repository:
    def __init__(self, url=None):
        self.url = url or os.getenv("FLOODCAT_DATABASE_URL")
        if not self.url or not self.url.startswith("postgresql+"):
            raise RuntimeError("Set FLOODCAT_DATABASE_URL to a PostgreSQL URL")
        self.engine = create_engine(self.url, pool_pre_ping=True)

    def save_analysis(self, result):
        with self.engine.begin() as db:
            db.execute(
                text("""INSERT INTO analysis_runs
                    (id, created_at, input_fingerprint, config_fingerprint,
                     evidence_snapshot, payload)
                    VALUES (:id, :created_at, :input_hash, :config_hash,
                            CAST(:evidence AS jsonb), CAST(:payload AS jsonb))"""),
                {
                    "id": result["analysis_id"],
                    "created_at": result["created_at"],
                    "input_hash": result["input_fingerprint"],
                    "config_hash": result["config_fingerprint"],
                    "evidence": json.dumps(
                        result["ai_contribution"]["approved_evidence_snapshot"]
                    ),
                    "payload": json.dumps(result, allow_nan=False),
                },
            )

    def get_analysis(self, identifier):
        with self.engine.connect() as db:
            row = db.execute(
                text("SELECT payload FROM analysis_runs WHERE id=:id"),
                {"id": identifier},
            ).scalar_one_or_none()
        if row is None:
            raise ModelError("not_found", "Analysis not found")
        return row if isinstance(row, dict) else json.loads(row)

    def list_analyses(self, limit=50):
        with self.engine.connect() as db:
            rows = (
                db.execute(
                    text(
                        "SELECT payload FROM analysis_runs ORDER BY created_at DESC, id DESC LIMIT :limit"
                    ),
                    {"limit": min(200, max(1, limit))},
                )
                .scalars()
                .all()
            )
        reports = [row if isinstance(row, dict) else json.loads(row) for row in rows]
        return [
            {
                "analysis_id": r["analysis_id"],
                "created_at": r["created_at"],
                "modelled_count": r["modelled_count"],
            }
            for r in reports
        ]

    def add_evidence(self, evidence):
        try:
            with self.engine.begin() as db:
                db.execute(
                    text("""INSERT INTO evidence (id, payload, approved, location)
                        VALUES (:id, CAST(:payload AS jsonb), false,
                                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"""),
                    {
                        "id": evidence.evidence_id,
                        "payload": json.dumps(evidence.to_dict()),
                        "lon": evidence.lon,
                        "lat": evidence.lat,
                    },
                )
        except IntegrityError:
            raise ModelError(
                "duplicate_evidence", "Evidence ID already exists"
            ) from None

    def list_evidence(self):
        from ..ai.evidence import Evidence

        with self.engine.connect() as db:
            rows = (
                db.execute(text("SELECT payload FROM evidence ORDER BY id"))
                .scalars()
                .all()
            )
        return [
            Evidence(**(row if isinstance(row, dict) else json.loads(row)))
            for row in rows
        ]

    def approve_evidence(self, identifier, reviewer):
        from dataclasses import replace
        from ..ai.evidence import Evidence

        with self.engine.begin() as db:
            row = db.execute(
                text("SELECT payload FROM evidence WHERE id=:id FOR UPDATE"),
                {"id": identifier},
            ).scalar_one_or_none()
            if row is None:
                raise ModelError("not_found", "Evidence not found")
            item = Evidence(**(row if isinstance(row, dict) else json.loads(row)))
            item = replace(item, approved=True, reviewer=reviewer)
            db.execute(
                text(
                    "UPDATE evidence SET payload=CAST(:payload AS jsonb), approved=true WHERE id=:id"
                ),
                {"id": identifier, "payload": json.dumps(item.to_dict())},
            )
        return item

    def import_starter_data(self, exposure_path, hotspot_path):
        """Import the supplied synthetic portfolio and named validation points once."""
        import csv
        import hashlib
        from decimal import Decimal

        exposure_path = Path(exposure_path)
        hotspot_path = Path(hotspot_path)
        rows = read_csv(exposure_path)
        assets, issues = validate_rows(rows)
        errors = [issue for issue in issues if issue["severity"] == "error"]
        if errors:
            raise ModelError("portfolio_review_required", str(errors))
        if any(set(asset.hazard) != set(TIERS) for asset in assets):
            raise ModelError(
                "missing_hazard",
                "Import requires the prepared exposure CSV with all five scores",
            )
        for asset in assets:
            validate_scores(asset.hazard)
        with hotspot_path.open(newline="", encoding="utf-8-sig") as stream:
            hotspots = list(csv.DictReader(stream))
        if not hotspots or any(
            not all(h.get(k) for k in ("name", "lat", "lon")) for h in hotspots
        ):
            raise ModelError(
                "invalid_hotspots", "Hotspot CSV requires name, lat and lon"
            )

        portfolio_id = str(uuid4())
        digest = hashlib.sha256(exposure_path.read_bytes()).hexdigest()
        total_tiv = sum((a.tiv_kes for a in assets), Decimal(0))
        with self.engine.begin() as db:
            previous = db.execute(
                text(
                    "SELECT id, asset_count, tiv_kes FROM portfolios WHERE source_sha256=:hash"
                ),
                {"hash": digest},
            ).first()
            if previous:
                return {
                    "portfolio_id": previous.id,
                    "asset_count": previous.asset_count,
                    "hotspot_count": len(hotspots),
                    "tiv_kes": money_string(previous.tiv_kes),
                    "validation_warning_count": len(issues),
                    "source_sha256": digest,
                    "already_imported": True,
                }
            db.execute(
                text("""INSERT INTO portfolios
                    (id, source_name, source_sha256, synthetic, asset_count, tiv_kes)
                    VALUES (:id, :name, :hash, true, :count, :tiv)"""),
                {
                    "id": portfolio_id,
                    "name": exposure_path.name,
                    "hash": digest,
                    "count": len(assets),
                    "tiv": total_tiv,
                },
            )
            db.execute(
                text("""INSERT INTO assets
                    (portfolio_id, loc_id, location, housing_class, floor_area_m2,
                     cost_per_m2_kes, tiv_kes, hazard_scores, source, synthetic)
                    VALUES (:portfolio_id, :loc_id,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                            :housing_class, :area, :cost, :tiv,
                            CAST(:hazard_scores AS jsonb), :source, true)"""),
                [
                    {
                        "portfolio_id": portfolio_id,
                        "loc_id": a.loc_id,
                        "lon": a.lon,
                        "lat": a.lat,
                        "housing_class": a.housing_class,
                        "area": a.floor_area_m2,
                        "cost": a.cost_per_m2_kes,
                        "tiv": a.tiv_kes,
                        "hazard_scores": json.dumps(a.hazard),
                        "source": a.source,
                    }
                    for a in assets
                ],
            )
            for row in hotspots:
                db.execute(
                    text("""INSERT INTO hotspots
                        (name, location, source_name, coordinate_precision, review_status)
                        VALUES (:name, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                                :source, 'neighbourhood_approximate', 'supplied')
                        ON CONFLICT (name) DO NOTHING"""),
                    {
                        "name": row["name"],
                        "lon": float(row["lon"]),
                        "lat": float(row["lat"]),
                        "source": hotspot_path.name,
                    },
                )
        return {
            "portfolio_id": portfolio_id,
            "asset_count": len(assets),
            "hotspot_count": len(hotspots),
            "tiv_kes": money_string(total_tiv),
            "validation_warning_count": len(issues),
            "source_sha256": digest,
            "already_imported": False,
        }
