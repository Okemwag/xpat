import hashlib
import json
from pathlib import Path
from ..core.constants import FEATURES
from ..core.numeric import bounded
from ..core.errors import ModelError

def train(path,output,provenance):
    """Spatial groups supplied by researchers, with explicit held-out test groups."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import confusion_matrix, precision_score, recall_score, roc_auc_score
    from ..exposure.loaders import read_csv
    rows=read_csv(path)
    if not provenance.strip(): raise ModelError('missing_provenance','State label origin and sampling method')
    if len(rows)<8: raise ModelError('insufficient_labels','At least 8 independently labelled records required')
    groups={'train':set(),'test':set()}; features={}; labels={}
    for split in groups:
        subset=[r for r in rows if r.get('split')==split]
        groups[split]={r['spatial_group'] for r in subset}
        features[split]=np.array([[bounded(r[f],f) for f in FEATURES] for r in subset])
        labels[split]=np.array([bounded(r['label'],'label') for r in subset])
        if not groups[split] or '' in groups[split] or set(labels[split])!={0.,1.}:
            raise ModelError('invalid_labels','Train and test must each include spatial groups and both binary labels')
    if any(r.get('split') not in groups for r in rows): raise ModelError('invalid_split','Only train/test accepted')
    if groups['train'] & groups['test']: raise ModelError('label_leakage','Spatial groups overlap train and test')
    model=LogisticRegression(random_state=42,max_iter=1000).fit(features['train'],labels['train'])
    probability=model.predict_proba(features['test'])[:,1]; predicted=(probability>=.5).astype(int)
    report={'held_out_count':len(predicted),'confusion_matrix':confusion_matrix(labels['test'],predicted,labels=[0,1]).tolist(),
            'precision':float(precision_score(labels['test'],predicted,zero_division=0)),
            'recall':float(recall_score(labels['test'],predicted,zero_division=0)),
            'roc_auc':float(roc_auc_score(labels['test'],probability)),
            'warning':'Metrics depend on label quality; unlabelled locations are not negative examples. Supplied positive-only hotspots cannot establish false-positive rate.'}
    artifact={'features':list(FEATURES),'coefficients':model.coef_[0].tolist(),'intercept':float(model.intercept_[0]),
              'training_provenance':provenance,'data_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
              'train_groups':sorted(groups['train']),'test_groups':sorted(groups['test']),'evaluation':report,
              'status':'uncalibrated_hotspot_susceptibility_classifier'}
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps(artifact,indent=2)+'\n')
    return artifact
