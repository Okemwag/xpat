"""Score free-text ingestion against held-out labelled cases. Pure: no network, no model calls."""
from decimal import Decimal

TIV_TOLERANCE = 0.02

def _norm(text):
    return ''.join(ch for ch in str(text or '').lower() if ch.isalnum())

def _match(expected, predicted):
    """Pair each expected group with at most one predicted group: same place name, else best remaining."""
    pairs, free = [], list(range(len(predicted)))
    for e in expected:
        hit = next((i for i in free if e['location'] and _norm(e['location']) in _norm(predicted[i]['location_name'])), None)
        if hit is None and e['location'] is None:
            hit = next((i for i in free if predicted[i]['housing_class'] in (e['housing_class'], '—')), free[0] if free else None)
        if hit is not None: free.remove(hit)
        pairs.append((e, predicted[hit] if hit is not None else None))
    return pairs, [predicted[i] for i in free]

def score_case(case, result):
    groups = result['groups']
    pairs, extra = _match(case['expected'], groups)
    fields = {'found': [], 'housing_class': [], 'count': [], 'tiv_kes_each': [], 'located': [], 'quote_verified': []}
    for e, g in pairs:
        fields['found'].append(g is not None)
        if g is None: continue
        got_class = None if g['housing_class'] in ('—', '') else g['housing_class']
        fields['housing_class'].append(got_class == e['housing_class'])
        fields['count'].append(g['count'] == e['count'])
        if e['tiv_kes_each'] is not None:
            got = None if g['tiv_kes_each'] in ('—', '') else float(Decimal(g['tiv_kes_each']))
            fields['tiv_kes_each'].append(got is not None and abs(got-e['tiv_kes_each']) <= TIV_TOLERANCE*e['tiv_kes_each'])
        fields['located'].append(not any('could not locate' in f for f in g['flags']))
        fields['quote_verified'].append(g['quote_verified'])
    expected_buildings = sum(e['count'] for e in case['expected'])
    predicted_buildings = sum(g['count'] for g in groups)
    return {'id': case['id'], 'fields': fields, 'extra_groups': len(extra),
            'expected_buildings': expected_buildings, 'predicted_buildings': predicted_buildings,
            'exact': all(all(v) for v in fields.values()) and not extra and expected_buildings == predicted_buildings}

def summarise(scores):
    def rate(key):
        values = [v for s in scores for v in s['fields'][key]]
        return {'correct': sum(values), 'total': len(values), 'rate': (sum(values)/len(values)) if values else None}
    return {'cases': len(scores), 'cases_fully_correct': sum(s['exact'] for s in scores),
            'groups_found': rate('found'), 'housing_class': rate('housing_class'), 'count': rate('count'),
            'tiv_kes_each': rate('tiv_kes_each'), 'located': rate('located'), 'quote_verified': rate('quote_verified'),
            'extra_groups': sum(s['extra_groups'] for s in scores),
            'building_count_exact': sum(s['expected_buildings'] == s['predicted_buildings'] for s in scores)}
