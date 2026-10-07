import hashlib
import json
import math
from ..core.constants import FEATURES
from ..core.errors import ModelError
from ..core.numeric import finite, bounded

class HotspotModel:
    """JSON logistic artifact, no executable pickle; probability is susceptibility, not AEP."""
    def __init__(self,artifact):
        if artifact.get('features')!=list(FEATURES): raise ModelError('invalid_model','Feature schema mismatch')
        self.artifact=artifact
        self.weights=[finite(x,'coefficient') for x in artifact['coefficients']]
        self.intercept=finite(artifact['intercept'],'intercept')
        if len(self.weights)!=len(FEATURES): raise ModelError('invalid_model','Coefficient count mismatch')
        if not artifact.get('training_provenance'): raise ModelError('invalid_model','Training provenance required')
    @classmethod
    def load(cls,path):
        with open(path) as stream: return cls(json.load(stream))
    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.artifact,sort_keys=True).encode()).hexdigest()
    def predict(self,features):
        if set(features)!=set(FEATURES): raise ModelError('missing_ai_features','Every trained feature is required')
        z=self.intercept+sum(w*bounded(features[f],f) for w,f in zip(self.weights,FEATURES))
        return 1/(1+math.exp(-max(-700.,min(700.,z))))
