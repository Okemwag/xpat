"""Drainage-aware hazard (AI enhancement 1): a drainage-failure probability added to the terrain-and-river proxy.

The baseline proxy finds 12 of 24 named hotspots; the misses flood because drains are blocked, undersized or absent,
which terrain cannot show (WRI 2026, Flooding in Nairobi's informal settlements: blocked drains, solid waste and spreading
hard surfaces). This module scores each point on four features, all scaled 0–1:

- ``low_terrain``       the proxy's own common-tier score (REAL terrain + OSM rivers → PROXY)
- ``built_density``     OSM building centroids within ``density_radius_m``, saturating at ``density_saturation``
                        (a stand-in for sealed, impervious ground)
- ``drain_gap``         distance to the nearest mapped drain or ditch (OSM ``waterway=drain|ditch``) over ``drain_reach_m``,
                        capped at 1 — far from any mapped drain = nowhere for water to go. OSM maps drains unevenly, so in
                        informal areas a gap can mean "not mapped" rather than "no drain"; this is stated wherever it is shown.
- ``culvert_proximity`` closeness to a mapped culvert (OSM ``tunnel=culvert``), where debris blocks flow

p = logistic(intercept + Σ wᵢ·xᵢ). Two modes:

- ``prior``  — weights from ``configs/default.json`` (ASSUMPTION), used until there is enough evidence to learn from.
- ``fitted`` — L2-regularised logistic regression (AI) on approved, independent drainage evidence (positives) against
               seeded random background points (pseudo-absences). The 24 named hotspots are NEVER used for fitting:
               they are the test set for the hit rate.

The probability raises hazard through the same uplift formula as reviewed evidence (``hazard.interpretation.enhance``)
with its own weight, only where p exceeds ``probability_threshold`` (signal = (p − t)/(1 − t)). It is a severity uplift, not a depth and not a measured probability of flooding.
"""
import json
import math
from dataclasses import dataclass, asdict, field
from pathlib import Path
import numpy as np
from ..core.config import DRAINAGE_FEATURES
from ..core.constants import NAIROBI_BOUNDS, TIERS
from ..core.errors import ModelError
from ..core.geo import distance_m, in_coverage
from ..core.numeric import bounded
from .hotspots import hotspot_check
from .interpretation import enhance, validate_scores

FEATURES = DRAINAGE_FEATURES
_LAT0 = -1.275
_M_PER_DEG = 111195.08
CELL_M = 50.0

def _xy(lon, lat):
    """Local equirectangular metres, origin at the south-west corner of the hazard maps."""
    west, south, _, _ = NAIROBI_BOUNDS
    return (np.asarray(lon, float)-west)*_M_PER_DEG*math.cos(math.radians(_LAT0)), (np.asarray(lat, float)-south)*_M_PER_DEG

class DrainageLayers:
    """OSM drains, culverts and building centroids held in memory for fast feature lookups.

    Built by ``scripts/build_drainage_layers.py`` (Overpass API) into ``runtime/drainage/osm_layers.json``:
    ``{"drains": [[[lon, lat], ...], ...], "culverts": [[lon, lat], ...], "buildings": [[lon, lat], ...], "source": "...", "fetched": "..."}``.
    """
    def __init__(self, drains=(), culverts=(), buildings=(), source='', fetched=''):
        segments = []
        for line in drains:
            pts = [(float(p[0]), float(p[1])) for p in line]
            segments += [(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:])]
        seg = np.array(segments, float).reshape(-1, 4)
        x1, y1 = _xy(seg[:, 0], seg[:, 1]); x2, y2 = _xy(seg[:, 2], seg[:, 3])
        self.segments = np.column_stack([x1, y1, x2, y2])
        c = np.array([(float(p[0]), float(p[1])) for p in culverts], float).reshape(-1, 2)
        self.culverts = np.column_stack(_xy(c[:, 0], c[:, 1])) if len(c) else np.zeros((0, 2))
        b = np.array([(float(p[0]), float(p[1])) for p in buildings], float).reshape(-1, 2)
        west, south, east, north = NAIROBI_BOUNDS
        width, height = _xy(east, north)
        self.shape = (int(math.ceil(float(height)/CELL_M)), int(math.ceil(float(width)/CELL_M)))
        grid = np.zeros(self.shape)
        if len(b):
            bx, by = _xy(b[:, 0], b[:, 1])
            rows = np.clip((by//CELL_M).astype(int), 0, self.shape[0]-1); cols = np.clip((bx//CELL_M).astype(int), 0, self.shape[1]-1)
            np.add.at(grid, (rows, cols), 1)
        # Summed-area table: building count in any rectangle in O(1).
        self.cumulative = np.pad(grid.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        self.counts = {'drain_segments': len(self.segments), 'culverts': len(self.culverts), 'buildings': int(len(b))}
        self.source, self.fetched = source, fetched

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict): raise ModelError('invalid_layers', 'Drainage layers must be a JSON object')
        return cls(data.get('drains') or (), data.get('culverts') or (), data.get('buildings') or (), str(data.get('source', '')), str(data.get('fetched', '')))

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists(): raise ModelError('missing_layers', f'Drainage layers not found: {path}. Run scripts/build_drainage_layers.py')
        try: return cls.from_dict(json.loads(path.read_text()))
        except (ValueError, TypeError, IndexError) as exc: raise ModelError('invalid_layers', f'Drainage layers file is malformed ({exc})') from None

    def _nearest_segment_m(self, x, y):
        if not len(self.segments): return math.inf
        x1, y1, x2, y2 = self.segments.T
        dx, dy = x2-x1, y2-y1
        length2 = dx*dx+dy*dy
        t = np.clip(np.where(length2 > 0, ((x-x1)*dx+(y-y1)*dy)/np.where(length2 > 0, length2, 1), 0), 0, 1)
        return float(np.sqrt((x1+t*dx-x)**2+(y1+t*dy-y)**2).min())

    def _buildings_within(self, x, y, radius):
        r0 = int(max(0, (y-radius)//CELL_M)); r1 = int(min(self.shape[0], (y+radius)//CELL_M+1))
        c0 = int(max(0, (x-radius)//CELL_M)); c1 = int(min(self.shape[1], (x+radius)//CELL_M+1))
        if r0 >= r1 or c0 >= c1: return 0.
        s = self.cumulative
        square = s[r1, c1]-s[r0, c1]-s[r1, c0]+s[r0, c0]
        # Square window → circle of the same radius (area ratio π/4); a building-density stand-in, not a count.
        return float(square)*math.pi/4

    def features(self, lat, lon, terrain_score, config):
        """Four 0–1 features at a point. ``terrain_score`` is the proxy's common-tier score there."""
        d = config.drainage_model
        x, y = (float(v) for v in _xy(lon, lat))
        drain = self._nearest_segment_m(x, y)
        culvert = float(np.sqrt(((self.culverts-[x, y])**2).sum(1)).min()) if len(self.culverts) else math.inf
        return {'low_terrain': bounded(terrain_score, 'terrain_score'),
                'built_density': min(1., self._buildings_within(x, y, d['density_radius_m'])/d['density_saturation']),
                'drain_gap': min(1., drain/d['drain_reach_m']),
                'culvert_proximity': max(0., 1-culvert/d['culvert_reach_m'])}

def _sigmoid(z):
    return 1/(1+math.exp(-max(-60., min(60., z))))

@dataclass(frozen=True)
class DrainageModel:
    mode: str
    intercept: float
    weights: dict
    training: dict = field(default_factory=dict)
    def probability(self, features):
        return _sigmoid(self.intercept+sum(self.weights[k]*features[k] for k in FEATURES))
    def to_dict(self): return asdict(self)

def prior_model(config, reason='Configured prior weights (ASSUMPTION)'):
    d = config.drainage_model
    return DrainageModel('prior', d['prior_intercept'], dict(d['prior_weights']), {'reason': reason})

def fit_logistic(X, y, l2, iterations=50):
    """L2-regularised logistic regression by Newton's method (intercept unpenalised). Returns (intercept, weights)."""
    X = np.column_stack([np.ones(len(X)), np.asarray(X, float)]); y = np.asarray(y, float)
    beta = np.zeros(X.shape[1]); penalty = np.full(X.shape[1], float(l2)); penalty[0] = 0
    for _ in range(iterations):
        p = 1/(1+np.exp(-np.clip(X@beta, -60, 60)))
        gradient = X.T@(p-y)+penalty*beta
        hessian = X.T@(X*(p*(1-p))[:, None])+np.diag(penalty)+1e-9*np.eye(X.shape[1])
        step = np.linalg.solve(hessian, gradient)
        beta -= step
        if np.abs(step).max() < 1e-8: break
    return float(beta[0]), beta[1:]

def background_points(n, seed, avoid=(), exclusion_m=0.):
    """Seeded random points inside the hazard maps, kept away from known flood points (pseudo-absences)."""
    rng = np.random.default_rng(seed)
    west, south, east, north = NAIROBI_BOUNDS
    points = []
    for _ in range(n*20):
        if len(points) >= n: break
        lat, lon = float(rng.uniform(south+1e-6, north)), float(rng.uniform(west, east-1e-6))
        if not in_coverage(lon, lat): continue
        if any(distance_m(lat, lon, a, b) < exclusion_m for a, b in avoid): continue
        points.append((lat, lon))
    return points

def _terrain(provider, lat, lon):
    from types import SimpleNamespace
    scores = provider.scores(SimpleNamespace(lat=lat, lon=lon, hazard={}))
    return scores.get(TIERS[-1])

def training_points(evidence, config, extra_positives=()):
    """Positives: approved, independent drainage / runoff evidence (+ optional satellite flood points). Never the hotspot list."""
    from ..ai.evidence import usable
    positives = [(e.lat, e.lon, f'evidence {e.evidence_id}') for e in usable(evidence, config) if e.independent_of_hotspot_list]
    positives += [(float(lat), float(lon), 'satellite flood pixel') for lat, lon in extra_positives]
    return positives

def fit(layers, provider, evidence, config, extra_positives=()):
    """Learn the weights from evidence when there is enough of it; otherwise return the prior and say why."""
    d = config.drainage_model
    positives = training_points(evidence, config, extra_positives)
    if len(positives) < d['min_training_positives']:
        return prior_model(config, f"{len(positives)} independent flood point(s); at least {d['min_training_positives']} are needed to learn weights, "
                                   'so the configured prior weights (ASSUMPTION) are used')
    negatives = background_points(d['background_points'], d['seed'], [(a, b) for a, b, _ in positives], d['background_exclusion_m'])
    X, y = [], []
    for points, label in ((positives, 1), ([(a, b, 'background') for a, b in negatives], 0)):
        for lat, lon, _ in points:
            terrain = _terrain(provider, lat, lon)
            if terrain is None: continue
            f = layers.features(lat, lon, terrain, config)
            X.append([f[k] for k in FEATURES]); y.append(label)
    if sum(y) < d['min_training_positives']:
        return prior_model(config, 'Too few flood points fall on the hazard maps to learn weights; prior weights (ASSUMPTION) used')
    intercept, weights = fit_logistic(X, y, d['l2'])
    p = 1/(1+np.exp(-(intercept+np.asarray(X)@weights)))
    return DrainageModel('fitted', intercept, {k: float(w) for k, w in zip(FEATURES, weights)},
                         {'positives': int(sum(y)), 'background': int(len(y)-sum(y)), 'seed': d['seed'], 'l2': d['l2'],
                          'mean_p_positive': float(p[np.asarray(y) == 1].mean()), 'mean_p_background': float(p[np.asarray(y) == 0].mean()),
                          'reason': 'Learned from approved independent evidence against random background points (pseudo-absences); '
                                    'the 24 named hotspots were not used and remain the test set'})

class DrainageAdjustment:
    """Applies the drainage probability as a hazard uplift. Used by services.analysis and the hotspot hit-rate check."""
    def __init__(self, layers, model, config):
        self.layers, self.model, self.config = layers, model, config
    def probability(self, lat, lon, baseline):
        return self.model.probability(self.layers.features(lat, lon, baseline[TIERS[-1]], self.config))
    def signal(self, lat, lon, baseline):
        """0 below the probability threshold, rising to 1 at p = 1, so low-probability places are left unchanged."""
        t = self.config.drainage_model['probability_threshold']
        return max(0., (self.probability(lat, lon, baseline)-t)/(1-t))
    def adjust(self, lat, lon, baseline):
        return enhance(baseline, self.signal(lat, lon, baseline), self.config, weight=self.config.drainage_model['weight'])
    def summary(self):
        return {'mode': self.model.mode, 'threshold': self.config.drainage_model['probability_threshold'], 'intercept': self.model.intercept, 'weights': dict(self.model.weights), 'training': dict(self.model.training),
                'weight': self.config.drainage_model['weight'], 'layers': dict(self.layers.counts), 'layers_source': self.layers.source,
                'layers_fetched': self.layers.fetched}

class DrainedHazard:
    """A hazard provider with the drainage uplift applied (for hit-rate and satellite checks)."""
    def __init__(self, provider, adjustment): self.provider, self.adjustment = provider, adjustment
    def scores(self, asset):
        base = validate_scores(self.provider.scores(asset))
        return self.adjustment.adjust(asset.lat, asset.lon, base)

def hit_rate(hotspots, provider, adjustment):
    """Named hotspots flagged before and after the drainage uplift, in the same plain terms as the baseline check."""
    before = hotspot_check(hotspots, provider)
    after = hotspot_check(hotspots, DrainedHazard(provider, adjustment))
    newly = [a['name'] for b, a in zip(before['points'], after['points']) if a['flagged_any_tier'] and not b['flagged_any_tier']]
    return {'hotspot_count': before['hotspot_count'], 'before_flagged': before['flagged_any_tier'], 'after_flagged': after['flagged_any_tier'],
            'newly_flagged': newly, 'mode': adjustment.model.mode,
            'points': [{'name': b['name'], 'before_common': b[TIERS[-1]], 'after_common': a[TIERS[-1]],
                        'before_flagged': b['flagged_any_tier'], 'after_flagged': a['flagged_any_tier']} for b, a in zip(before['points'], after['points'])],
            'caveats': ['A higher hit rate is not proof of accuracy: the uplift raises scores everywhere the features are high, including places that do not flood.',
                        'Only hotspots with a score of zero can change from missed to flagged; the rule is the same as the baseline check (score > 0).',
                        'OSM drains are mapped unevenly; a drain gap can mean "not mapped".']}
