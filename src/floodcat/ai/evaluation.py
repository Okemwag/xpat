from ..core.numeric import bounded

def positive_hotspot_detection(baseline,enhanced,threshold):
    """Independent geocoded positive locations only; never call this accuracy."""
    threshold=bounded(threshold,'threshold')
    if len(baseline)!=len(enhanced): raise ValueError('Matched hotspot arrays required')
    paired=[(bounded(b,'baseline'),bounded(e,'enhanced')) for b,e in zip(baseline,enhanced) if b is not None and e is not None]
    return {'known_positive_count':len(baseline),'evaluated_count':len(paired),'uncovered_count':len(baseline)-len(paired),
            'baseline_detected':sum(b>threshold for b,e in paired),'enhanced_detected':sum(e>threshold for b,e in paired),
            'threshold':threshold,'false_positive_rate':None,'accuracy':None,
            'limitation':'Positive-only and approximate neighbourhood centres; do not train on evaluation hotspots'}
