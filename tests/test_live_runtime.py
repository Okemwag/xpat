from decimal import Decimal
import pytest
from floodcat.core.errors import ReviewRequired
from conftest import DATA, row

pytest.importorskip('rasterio')

@pytest.fixture(scope='module')
def runtime(tmp_path_factory):
    from floodcat.services.runtime import Runtime
    return Runtime(data_dir=DATA, store_dir=tmp_path_factory.mktemp('store'))

def test_upload_without_scores_matches_prepared_file(runtime):
    blank = runtime.run(runtime.parse_upload((DATA/'exposure_nairobi_synthetic.csv').read_bytes()))
    prepared = runtime.run(runtime.sample_rows())
    assert [p['loss_kes'] for p in blank['runs']['baseline']['ep_curve']] == [p['loss_kes'] for p in prepared['runs']['baseline']['ep_curve']]

def test_wrong_supplied_scores_are_replaced_and_flagged(runtime):
    report = runtime.run([row(scores=(0.9, 0.9, 0.9, 0.9, 0.9))])
    assert any(i['code'] == 'supplied_scores_differ' for i in report['issues'])

def test_point_in_east_strip_without_raster_is_an_error_not_zero(runtime):
    # Inside the documented bounds but east of the raster's last column (36.99972).
    with pytest.raises(ReviewRequired) as exc:
        runtime.run([row(lon='36.9999', lat='-1.27')])
    assert any(i['code'] == 'hazard_unavailable' for i in exc.value.issues)

def test_declare_synthetic_for_files_without_label(runtime):
    rows = [{'loc_id': 'A', 'lat': '-1.2576', 'lon': '36.8962', 'housing_class': 'semi_permanent', 'tiv_kes': '3,300,000'}]
    report = runtime.run(rows, declare_synthetic=True)
    assert report['runs']['baseline']['property_losses']['common'][0]['synthetic'] is True
    assert report['declarations']

def test_runs_are_saved_and_listed(runtime):
    report = runtime.run([row()])
    runtime.store.save_analysis(report, owner='alice', label='test')
    assert runtime.store.list_analyses(owner='alice')[0]['analysis_id'] == report['analysis_id']
    assert runtime.store.get_analysis(report['analysis_id'])['modelled_count'] == 1
    assert runtime.store.list_analyses(owner='bob') == []

def test_config_override_changes_results(runtime):
    base = runtime.run(runtime.sample_rows())
    deeper = runtime.run(runtime.sample_rows(), config=runtime.config.replace(max_depth_m=4.0))
    assert Decimal(deeper['runs']['baseline']['aal']['aal_kes']) > Decimal(base['runs']['baseline']['aal']['aal_kes'])
