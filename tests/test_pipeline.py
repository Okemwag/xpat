from copy import deepcopy
from decimal import Decimal
import math
import pytest
from floodcat.core.config import ModelConfig
from floodcat.core.errors import ModelError
from floodcat.core.constants import TIERS, CLASSES
from floodcat.services.analysis import analyse
from floodcat.vulnerability.functions import damage_ratio
from floodcat.ai.model import HotspotModel
from floodcat.ai.evidence import Evidence, evidence_signal
from floodcat.exposure.validation import parse_row

def model():
    return HotspotModel({'features':['baseline_common','impervious_fraction','drainage_deficit','evidence_signal'],
                         'coefficients':[1,2,3,4],'intercept':-2,'training_provenance':'test fixture only'})

def test_financial_reconciliation(rows):
    report=analyse(rows)
    assert report['modelled_tiv_kes']=='29480000.00'
    curve=report['runs']['baseline']['ep_curve']
    assert [p['tier'] for p in curve]==list(TIERS)
    assert [p['return_period_years'] for p in curve]==[10,25,50,100,250]
    assert [Decimal(p['loss_kes']) for p in curve]==sorted(Decimal(p['loss_kes']) for p in curve)
    for tier in TIERS:
        property_rows=report['runs']['baseline']['property_losses'][tier]
        total=sum(Decimal(r['loss_kes']) for r in property_rows)
        point=next(x for x in curve if x['tier']==tier)
        assert total==Decimal(point['loss_kes'])
        for category in ['construction','geographic_grid']:
            assert sum(Decimal(g['loss_kes']) for g in report['runs']['baseline']['breakdowns'][tier][category])==total
        assert all(0<=Decimal(r['loss_kes'])<=Decimal(r['tiv_kes']) for r in property_rows)
    assert report['ai_contribution']['enabled'] is False

@pytest.mark.parametrize('value',['NaN','inf','-inf',None,True])
def test_bad_money_rejected(rows,value):
    rows[0]['tiv_kes']=value
    with pytest.raises(ModelError): analyse(rows)

def test_duplicate_and_partial_denominator(rows):
    rows.append(deepcopy(rows[0]))
    with pytest.raises(ModelError): analyse(rows)
    report=analyse(rows,allow_partial=True)
    assert report['rejected_count']==1
    assert report['accepted_tiv_kes']=='29480000.00'
    assert report['partial']

def test_outside_is_unknown_not_zero(rows):
    rows[1]['lon']='37.02'
    with pytest.raises(ModelError): analyse(rows)
    report=analyse(rows,allow_partial=True)
    assert report['modelled_count']==3
    assert report['unmodelled_accepted_tiv_kes']=='24000000.00'
    assert report['excluded_from_hazard']==['DEMO-002']

@pytest.mark.parametrize('change',[{'housing_class':'unknown'},{'hazard_score_common':''},{'synthetic':'false'}, {'hazard_score_extreme':'0.9'}])
def test_bad_records_fail_closed(rows,change):
    rows[0].update(change)
    with pytest.raises(ModelError): analyse(rows)

def test_vulnerability_invariants():
    config=ModelConfig()
    for c in CLASSES:
        ys=[damage_ratio(x/100,c,config) for x in range(101)]
        assert ys[0]==0 and max(ys)<=.95 and ys==sorted(ys)
    assert damage_ratio(.3,'informal_iron_sheet',config)>damage_ratio(.3,'concrete_rcc',config)

def test_configuration_rejects_wrong_frequency_direction():
    with pytest.raises(ModelError): ModelConfig(return_periods=dict(zip(TIERS,[250,100,50,25,10])))

def test_ai_propagates_to_losses(rows):
    report=analyse(rows,model=model())
    assert report['ai_contribution']['changed_properties']==4
    assert all(Decimal(v)>0 for v in report['ai_contribution']['loss_delta_kes'].values())
    assert report['ai_contribution']['model_fingerprint']

def test_missing_ml_features_not_silently_baseline(rows):
    del rows[0]['drainage_deficit']
    with pytest.raises(ModelError): analyse(rows,model=model())

def test_unapproved_evidence_cannot_change_model(rows):
    raw=Evidence('e1','source','flood report','2026-03-01','place',-1.28,36.86,1,1)
    a=analyse(rows,model=model(),evidence=[raw])
    b=analyse(rows,model=model())
    assert a['runs']==b['runs']
    from dataclasses import replace
    approved=replace(raw,approved=True,reviewer='reviewer')
    c=analyse(rows,model=model(),evidence=[approved])
    assert c['ai_contribution']['loss_delta_kes']!=b['ai_contribution']['loss_delta_kes']
    assert evidence_signal(parse_row(rows[0]),[approved,approved],ModelConfig())==1

def test_tiv_anomaly_flagged_not_recomputed(rows):
    rows[0]['tiv_kes']='800000'
    report=analyse(rows)
    assert any(i['code']=='tiv_mismatch' for i in report['issues'])
    assert report['accepted_tiv_kes']=='30200000.00'


def test_ai_low_probability_does_not_make_every_zero_cell_a_hotspot():
    from floodcat.hazard.interpretation import enhance
    config=ModelConfig()
    scores={t:0. for t in TIERS}
    assert enhance(scores,.3,config)==scores

@pytest.mark.parametrize('bad_config',[{'curves':None},{'return_periods':[]},{'severity_knots':['x']},{'grid_size_m':True}])
def test_malformed_configuration_reports_domain_error(bad_config):
    with pytest.raises(ModelError): ModelConfig(**bad_config)
