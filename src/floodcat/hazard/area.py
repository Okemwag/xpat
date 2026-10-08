"""Hazard profile of an area: share of ground flagged in each tier around a point. No exposure, no money.

Points on a regular lattice (``public_notes.spacing_m``) within ``radius_m`` of the centre are looked up in the hazard maps;
the share with a score above zero is reported per tier (PROXY). Used by the public risk notes (ai/public_note.py).
"""
import math
from types import SimpleNamespace
from ..core.constants import TIERS
from ..core.errors import ModelError
from ..core.geo import in_coverage

M_PER_DEG = 111195.08

def lattice(lat, lon, radius_m, spacing_m):
    steps = int(radius_m//spacing_m)
    points = []
    for i in range(-steps, steps+1):
        for j in range(-steps, steps+1):
            if (i*spacing_m)**2+(j*spacing_m)**2 > radius_m**2: continue
            p_lat = lat+i*spacing_m/M_PER_DEG; p_lon = lon+j*spacing_m/(M_PER_DEG*math.cos(math.radians(lat)))
            if in_coverage(p_lon, p_lat): points.append((p_lat, p_lon))
    return points

def area_profile(provider, lat, lon, config):
    n = config.public_notes
    points = lattice(lat, lon, n['radius_m'], n['spacing_m'])
    scored = []
    for p_lat, p_lon in points:
        s = provider.scores(SimpleNamespace(lat=p_lat, lon=p_lon, hazard={}))
        if all(s[t] is not None for t in TIERS): scored.append(s)
    if not scored: raise ModelError('hazard_unavailable', 'This place is outside the hazard maps')
    share = lambda t: round(100*sum(s[t] > 0 for s in scored)/len(scored))
    return {'points': len(scored), 'radius_m': n['radius_m'], 'spacing_m': n['spacing_m'],
            'flagged_pct': {t: share(t) for t in TIERS},
            'mean_common_score': round(sum(s[TIERS[-1]] for s in scored)/len(scored), 2)}
