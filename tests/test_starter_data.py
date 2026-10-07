from decimal import Decimal
from pathlib import Path

from floodcat.exposure.loaders import read_csv
from floodcat.services.data_audit import audit_data
from floodcat.services.sensitivity import assumption_sensitivity


DATA = Path(__file__).parents[1] / 'data'


def test_supplied_data_matches_rasters_and_hotspot_baseline():
    report = audit_data(DATA)
    assert report['exposure_count'] == 600
    assert report['unique_ids'] == 600
    assert report['hotspot_count'] == 24
    assert report['base_fields_match_prepared']
    assert report['prepared_score_mismatches'] == 0
    assert report['baseline_common_hotspots_positive'] == 12
    assert report['score_ordered_count'] == 600
    assert report['tier_score_summary']['common']['positive_properties'] == 259
    assert report['tier_score_summary']['extreme']['positive_properties'] == 32
    assert Decimal(report['tiv_kes']) == Decimal('63635075000')


def test_sensitivity_keeps_assumptions_separate():
    rows = read_csv(DATA / 'exposure_nairobi_with_hazard.csv')
    scenarios = assumption_sensitivity(rows)
    losses = scenarios['loss_kes_by_tier']
    assert Decimal(losses['area_times_cost_tiv']['common']) < Decimal(losses['supplied_tiv']['common'])
    assert Decimal(losses['vulnerability_75_percent']['common']) < Decimal(losses['supplied_tiv']['common'])
    assert Decimal(losses['vulnerability_125_percent']['common']) > Decimal(losses['supplied_tiv']['common'])
    assert scenarios['doubled_return_period_mapping'][-1]['loss_kes'] == losses['supplied_tiv']['common']
