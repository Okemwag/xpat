from decimal import Decimal
import pytest
from floodcat.core.errors import ModelError, ReviewRequired
from floodcat.exposure.loaders import parse_csv_text
from floodcat.exposure.validation import apply_declarations, parse_money, summarise_issues, validate_rows
from floodcat.services.analysis import analyse
from conftest import row

HEADER = 'loc_id,lat,lon,housing_class,tiv_kes,synthetic,source\n'

def codes(issues, severity='error'):
    return {i['code'] for i in issues if i['severity'] == severity}

@pytest.mark.parametrize('data', [b'', b'   \n', HEADER.encode()])
def test_empty_files_are_rejected_clearly(data):
    with pytest.raises(ModelError) as exc:
        parse_csv_text(data)
    assert exc.value.code in ('empty_file', 'empty_portfolio')

def test_excel_semicolon_cp1252_with_bom_variants():
    text = 'Loc ID;Latitude;Longitude;Construction;TIV;Synthetic;Source\nA1;-1,28;36,82;Concrete;1000;yes;café test\n'
    # Semicolon CSVs from European Excel use decimal commas; we only normalise headers, not locales.
    rows = parse_csv_text(text.encode('cp1252'))
    assert set(rows[0]) == {'loc_id', 'lat', 'lon', 'housing_class', 'tiv_kes', 'synthetic', 'source'}
    assert rows[0]['source'] == 'café test'

def test_utf8_bom_and_blank_lines_and_trailing_spaces():
    rows = parse_csv_text(('﻿'+HEADER+'\n A1 ,-1.28,36.82, concrete_rcc ,1000,True,x\n\n').encode('utf-8'))
    assert len(rows) == 1 and rows[0]['loc_id'] == 'A1' and rows[0]['housing_class'] == 'concrete_rcc'

def test_duplicate_columns_after_normalising():
    with pytest.raises(ModelError) as exc:
        parse_csv_text('lat,Latitude,lon\n1,2,3\n')
    assert exc.value.code == 'invalid_header'

def test_row_with_extra_values_rejected():
    with pytest.raises(ModelError):
        parse_csv_text(HEADER+'A,-1.28,36.82,concrete_rcc,1,True,x,EXTRA\n')

def test_missing_columns_reported_once_with_hint():
    with pytest.raises(ModelError) as exc:
        validate_rows([{'loc_id': 'A', 'lat': '-1.28', 'lon': '36.82', 'housing_class': 'concrete_rcc', 'tiv_kes': '1'}])
    assert exc.value.code == 'missing_columns' and 'real or synthetic' in str(exc.value)

def test_declaration_fills_only_blanks_and_is_recorded():
    rows, notes = apply_declarations([{'loc_id': ''}, {'loc_id': 'B', 'synthetic': 'False', 'source': 's'}],
                                     declare_synthetic=True, assign_missing_ids=True)
    assert rows[0]['synthetic'] == 'True' and rows[0]['loc_id'] == 'UPL-00001'
    assert rows[1]['synthetic'] == 'False'  # an explicit "real" flag is never overwritten
    assert notes

@pytest.mark.parametrize('text,expected', [('1,250,000', '1250000.00'), ('KES 2.5m', '2500000.00'), ('300k', '300000.00'),
                                           ('Ksh 1bn', '1000000000.00'), ('  42 ', '42.00')])
def test_money_formats(text, expected):
    assert parse_money(text) == Decimal(expected)

@pytest.mark.parametrize('text', ['abc', '-5', '1.2.3', 'nan', 'inf', '£100'])
def test_bad_money_rejected(text):
    with pytest.raises(ModelError):
        parse_money(text)

@pytest.mark.parametrize('overrides,code', [
    ({'lat': '36.82', 'lon': '-1.28'}, 'swapped_coordinates'),
    ({'lat': '0', 'lon': '0'}, 'missing_coordinates'),
    ({'lat': '-1.0', 'lon': '36.8'}, 'outside_coverage'),
    ({'lat': 'abc'}, 'invalid_number'),
    ({'housing_class': 'castle'}, 'unknown_construction'),
    ({'tiv_kes': '-1'}, 'invalid_money'),
    ({'synthetic': 'maybe'}, 'invalid_synthetic'),
    ({'floor_area_m2': '0', 'cost_per_m2_kes': '100'}, 'invalid_replacement_cost'),
    ({'hazard_score_common': '1.5'}, 'out_of_range'),
    ({'loc_id': 'x'*600}, 'text_too_long'),
    ({'tiv_kes': ''}, 'missing_fields'),
])
def test_row_level_errors(overrides, code):
    _, issues = validate_rows([row(**overrides)])
    assert code in codes(issues)

def test_class_aliases_are_reported():
    assets, issues = validate_rows([row(housing_class='Reinforced Concrete'), row(loc_id='T-2', housing_class='mabati')])
    assert [a.housing_class for a in assets] == ['concrete_rcc', 'informal_iron_sheet']
    assert 'class_alias' in codes(issues, 'warning')

def test_duplicates_shared_points_zero_tiv_and_outliers():
    rows = [row(loc_id=f'T-{i}', lat=str(-1.28-i/1000)) for i in range(12)]
    rows += [row(loc_id='T-0'), row(loc_id='DUP-LOC'), row(loc_id='ZERO', tiv='0', lat='-1.30'), row(loc_id='BIG', tiv='1bn', lat='-1.31')]
    _, issues = validate_rows(rows)
    assert 'duplicate_id' in codes(issues)
    assert {'shared_coordinates', 'zero_tiv', 'tiv_outlier'} <= codes(issues, 'warning')

def test_real_records_accepted_unless_deployment_is_synthetic_only():
    assets, issues = validate_rows([row(synthetic='no')])
    assert len(assets) == 1 and not codes(issues)
    _, issues = validate_rows([row(synthetic='no')], synthetic_only=True)
    assert 'real_data_disabled' in codes(issues)

def test_declared_real_origin_fills_blanks():
    rows, notes = apply_declarations([{'loc_id': 'A'}], data_origin='real', source_label='broker doc')
    assert rows[0]['synthetic'] == 'False' and rows[0]['source'] == 'broker doc' and 'real' in notes[0]
    with pytest.raises(ModelError): apply_declarations([{}], data_origin='maybe')

def test_review_required_carries_issues_then_partial_runs(config):
    rows = [row(), row(loc_id='BAD', lat='36.82', lon='-1.28')]
    with pytest.raises(ReviewRequired) as exc:
        analyse(rows, config)
    assert exc.value.accepted_count == 1 and summarise_issues(exc.value.issues)[0]['code'] == 'swapped_coordinates'
    report = analyse(rows, config, allow_partial=True)
    assert report['modelled_count'] == 1 and report['partial']

def test_all_rows_invalid_even_with_partial(config):
    with pytest.raises(ReviewRequired):
        analyse([row(housing_class='castle')], config, allow_partial=True)

def test_zero_hazard_portfolio_gives_zero_curve(config):
    report = analyse([row(scores=(0, 0, 0, 0, 0))], config)
    run = report['runs']['baseline']
    assert all(Decimal(p['loss_kes']) == 0 for p in run['ep_curve']) and Decimal(run['aal']['aal_kes']) == 0

def test_zero_tiv_portfolio_has_no_percentage(config):
    report = analyse([row(tiv='0')], config)
    assert report['runs']['baseline']['ep_curve'][0]['loss_pct_of_tiv'] is None

def test_non_monotonic_supplied_scores_are_rejected_not_reordered(config):
    with pytest.raises(ReviewRequired) as exc:
        analyse([row(scores=(0.5, 0.4, 0.3, 0.2, 0.1))], config)
    assert 'nonmonotonic_hazard' in codes(exc.value.issues)

def test_summary_groups_identical_warnings(starter_rows):
    _, issues = validate_rows(starter_rows)
    groups = summarise_issues(issues)
    assert groups[0]['code'] == 'tiv_mismatch' and groups[0]['count'] == 600 and len(groups[0]['loc_ids']) == 10
