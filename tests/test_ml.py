import csv
from pathlib import Path
import pytest
from floodcat.ai.training import train
from floodcat.ai.model import HotspotModel
from floodcat.ai.evaluation import positive_hotspot_detection
from floodcat.core.errors import ModelError

def test_train_artifact_and_disjoint_groups(tmp_path):
    fixture=Path(__file__).parent/'fixtures/training.csv'
    output=tmp_path/'model.json'
    artifact=train(fixture,output,'Entirely illustrative synthetic labels; not Nairobi observations')
    assert set(artifact['train_groups']).isdisjoint(artifact['test_groups'])
    assert artifact['evaluation']['held_out_count']==4
    model=HotspotModel.load(output)
    p=model.predict(dict(baseline_common=.2,impervious_fraction=.8,drainage_deficit=.9,evidence_signal=.9))
    assert 0<p<1

def test_group_leakage_rejected(tmp_path):
    source=Path(__file__).parent/'fixtures/training.csv'
    rows=list(csv.DictReader(source.open()))
    rows[-1]['spatial_group']='train-a'
    target=tmp_path/'leaked.csv'
    with target.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    with pytest.raises(ModelError,match='overlap'): train(target,tmp_path/'model.json','test provenance')

def test_positive_only_validation_has_no_accuracy():
    report=positive_hotspot_detection([0.,.1,None],[.2,.1,None],0)
    assert report['baseline_detected']==1 and report['enhanced_detected']==2
    assert report['accuracy'] is None and report['false_positive_rate'] is None
    assert report['uncovered_count']==1
