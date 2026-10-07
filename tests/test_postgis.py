import os
from pathlib import Path

import pytest
from sqlalchemy import text

from floodcat.storage.repository import Repository


def test_starter_import_is_idempotent_and_spatially_queryable():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('PostGIS integration requires TEST_DATABASE_URL')
    root = Path(__file__).parents[1] / 'data'
    repo = Repository(url)
    first = repo.import_starter_data(root / 'exposure_nairobi_with_hazard.csv',
                                     root / 'nairobi_hotspots_geocoded.csv')
    repeated = repo.import_starter_data(root / 'exposure_nairobi_with_hazard.csv',
                                        root / 'nairobi_hotspots_geocoded.csv')
    assert first['portfolio_id'] == repeated['portfolio_id']
    assert repeated['already_imported']
    assert first['asset_count'] == 600 and first['hotspot_count'] == 24
    with repo.engine.connect() as db:
        count = db.execute(text('SELECT count(*) FROM assets WHERE portfolio_id=:id'),
                           {'id': first['portfolio_id']}).scalar_one()
        near = db.execute(text('''SELECT count(*) FROM assets WHERE portfolio_id=:id
            AND ST_DWithin(location::geography,
                ST_SetSRID(ST_MakePoint(36.935883, -1.314897), 4326)::geography, 100)'''),
            {'id': first['portfolio_id']}).scalar_one()
        scored = db.execute(text('''SELECT count(*) FROM assets WHERE portfolio_id=:id
            AND hazard_scores ? 'common' AND hazard_scores ? 'extreme' '''),
            {'id': first['portfolio_id']}).scalar_one()
    assert count == scored == 600 and near >= 1
