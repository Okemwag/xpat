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
        self.data_dir = Path(data_dir or os.getenv('FLOODCAT_DATA_DIR') or ROOT/'data')
        self.store_dir = Path(store_dir or os.getenv('FLOODCAT_STORE_DIR') or ROOT/'runtime'/'store')
        self.config = load_config(config_path)
        self.hazard = RasterHazard(self.data_dir).load()
        self.hotspots = load_hotspots(self.data_dir/'nairobi_hotspots_geocoded.csv')
        self.sample_path = self.data_dir/'exposure_nairobi_with_hazard.csv'
        self.blank_sample_path = self.data_dir/'exposure_nairobi_synthetic.csv'

    @cached_property
    def class_defaults(self):
        from ..ai.ingestion import class_defaults
        assets, _ = validate_rows(read_csv(self.sample_path))
        return class_defaults(assets)

    def llm(self):
        from ..ai.gemini import GeminiClient
        return GeminiClient()

    def gazetteer(self, with_ai_fallback=True):
        from ..ai.geocode import Gazetteer
        llm = None
        if with_ai_fallback:
            try: llm = self.llm()
            except ModelError: llm = None
        return Gazetteer(self.store_dir/'geocode_cache.json', llm=llm, online=os.getenv('FLOODCAT_OFFLINE') != '1')

    def sample_rows(self):
        return read_csv(self.sample_path)

    def parse_upload(self, data):
        return parse_csv_text(data)

    @property
    def synthetic_only(self):
        return os.getenv('FLOODCAT_SYNTHETIC_ONLY') == '1'

    def run(self, rows, *, config=None, declare_synthetic=False, data_origin=None, source_label=None, assign_missing_ids=False,
            allow_partial=False, ai_adjustment=False, evidence=None):
        rows, notes = apply_declarations(rows, declare_synthetic, source_label, assign_missing_ids, data_origin)
        # Callers pass the organisation's evidence explicitly (tenant-scoped); none means no adjustment input.
        result = analyse(rows, config or self.config, self.hazard, evidence=evidence or (), allow_partial=allow_partial,
                         hotspots=self.hotspots, ai_adjustment=ai_adjustment, synthetic_only=self.synthetic_only)
        result['declarations'] = notes
        return result
