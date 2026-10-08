"""Process-wide context for live use (Streamlit, API): load once, analyse many uploads."""

import os
from functools import cached_property
from pathlib import Path
from ..core.config import load_config
from ..core.errors import ModelError
from ..exposure.loaders import parse_csv_text, read_csv
from ..exposure.validation import apply_declarations, validate_rows
from ..hazard.hotspots import load_hotspots
from ..hazard.raster import RasterHazard
from .analysis import analyse

ROOT = Path(__file__).resolve().parents[3]


class Runtime:
    def __init__(self, data_dir=None, store_dir=None, config_path=None):
        self.data_dir = Path(
            data_dir or os.getenv("FLOODCAT_DATA_DIR") or ROOT / "data"
        )
        from ..platform.db import store_dir as default_store

        self.store_dir = Path(store_dir) if store_dir else default_store()
        self.config = load_config(config_path)
        self.hazard = RasterHazard(self.data_dir).load()
        self.hotspots = load_hotspots(self.data_dir / "nairobi_hotspots_geocoded.csv")
        self.sample_path = self.data_dir / "exposure_nairobi_with_hazard.csv"
        self.blank_sample_path = self.data_dir / "exposure_nairobi_synthetic.csv"

    @cached_property
    def class_defaults(self):
        from ..ai.ingestion import class_defaults

        assets, _ = validate_rows(read_csv(self.sample_path))
        return class_defaults(assets)

    def llm(self, provider=None):
        """A model client: the given provider (gemini | ollama), else the server default."""
        from ..ai.llm import make_client

        return make_client(provider)

    def gazetteer(self, with_ai_fallback=True, llm=None):
        """Place lookup. The AI fallback uses ``llm`` when given, so it follows the same model choice as the request."""
        from ..ai.geocode import Gazetteer

        if llm is not None:
            return Gazetteer(
                self.store_dir / "geocode_cache.json",
                llm=llm,
                online=os.getenv("FLOODCAT_OFFLINE") != "1",
            )
        if with_ai_fallback:
            try:
                llm = self.llm()
            except ModelError:
                llm = None
        return Gazetteer(
            self.store_dir / "geocode_cache.json",
            llm=llm,
            online=os.getenv("FLOODCAT_OFFLINE") != "1",
        )

    def sample_rows(self):
        return read_csv(self.sample_path)

    def parse_upload(self, data):
        return parse_csv_text(data)

    @property
    def synthetic_only(self):
        return os.getenv("FLOODCAT_SYNTHETIC_ONLY") == "1"

    @property
    def drainage_layers_path(self):
        return Path(
            os.getenv("FLOODCAT_DRAINAGE_LAYERS")
            or ROOT / "runtime" / "drainage" / "osm_layers.json"
        )

    @cached_property
    def drainage_layers(self):
        """OSM drains, culverts and buildings (scripts/build_drainage_layers.py), or None when not built on this server."""
        from ..hazard.drainage import DrainageLayers

        return (
            DrainageLayers.load(self.drainage_layers_path)
            if self.drainage_layers_path.exists()
            else None
        )

    def drainage_adjustment(
        self, evidence=(), config=None, extra_positives=(), layers=None
    ):
        """The drainage model, learned from the organisation's approved independent evidence when there is enough of it."""
        from ..hazard.drainage import DrainageAdjustment, fit

        layers = layers or self.drainage_layers
        if layers is None:
            raise ModelError(
                "missing_layers",
                "Drainage layers are not built on this server. Run: uv run python scripts/build_drainage_layers.py",
            )
        config = config or self.config
        return DrainageAdjustment(
            layers,
            fit(layers, self.hazard, tuple(evidence or ()), config, extra_positives),
            config,
        )

    def run(
        self,
        rows,
        *,
        config=None,
        declare_synthetic=False,
        data_origin=None,
        source_label=None,
        assign_missing_ids=False,
        allow_partial=False,
        ai_adjustment=False,
        evidence=None,
        drainage=False,
        drainage_evidence=None,
        drainage_extra_positives=(),
    ):
        rows, notes = apply_declarations(
            rows, declare_synthetic, source_label, assign_missing_ids, data_origin
        )
        config = config or self.config
        # Callers pass the organisation's evidence explicitly (tenant-scoped); none means no adjustment input.
        adjustment = (
            self.drainage_adjustment(
                drainage_evidence or evidence or (), config, drainage_extra_positives
            )
            if drainage
            else None
        )
        result = analyse(
            rows,
            config,
            self.hazard,
            evidence=evidence or (),
            allow_partial=allow_partial,
            hotspots=self.hotspots,
            ai_adjustment=ai_adjustment,
            synthetic_only=self.synthetic_only,
            drainage=adjustment,
        )
        result["declarations"] = notes
        return result
