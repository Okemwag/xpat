"""Schedule quality reviewer (AI enhancement 5), deterministic part: find likely data errors and propose fixes.

Runs on raw uploaded rows before validation. Each flag says what looks wrong and, where a fix is mechanical, proposes it.
Nothing changes until the user accepts a fix; fixed rows then pass ``exposure/validation.py`` like any CSV. The AI part
(``ai/quality.py``) only explains the flags in plain words; it never proposes or applies a value.

Thresholds are ASSUMPTIONS in ``configs/default.json`` → ``quality_checks``. Class medians come from the starter portfolio
(SYNTHETIC), the same reference used to fill missing values in AI ingestion.
"""
from ..core.constants import NAIROBI_BOUNDS
from ..core.errors import ModelError
from ..core.geo import in_coverage
from ..core.numeric import finite
from .validation import parse_class, parse_money

def _number(row, key):
    value = row.get(key)
    if value in (None, ''): return None
    try: return finite(str(value).replace(',', ''), key)
    except ModelError: return None

def _money(row, key='tiv_kes'):
    if row.get(key) in (None, ''): return None
    try: return float(parse_money(row[key], key))
    except ModelError: return None

def _fmt(value):
    return f'{value:,.0f}' if abs(value) >= 100 else f'{value:g}'

def review(rows, class_defaults, config):
    """Flags: [{row, loc_id, code, severity, message, fix}] where fix is None or {'action': 'drop'|'set', 'field', 'value'}."""
    q = config.quality_checks
    low, high = q['tiv_ratio_band']
    flags, ids, records, repeats = [], {}, {}, {}
    west, south, east, north = NAIROBI_BOUNDS
    def flag(index, row, code, message, fix=None, severity='warning'):
        flags.append({'row': index, 'loc_id': str(row.get('loc_id') or f'row {index+1}'), 'code': code, 'severity': severity, 'message': message, 'fix': fix})
    for index, row in enumerate(rows):
        loc_id = str(row.get('loc_id') or '').strip()
        lat, lon = _number(row, 'lat'), _number(row, 'lon')
        tiv, area, cost = _money(row), _number(row, 'floor_area_m2'), _number(row, 'cost_per_m2_kes')
        try: housing = parse_class(row.get('housing_class', ''))[0]
        except ModelError: housing = None
        if loc_id:
            if loc_id in ids:
                n = repeats[loc_id] = repeats.get(loc_id, 1)+1
                flag(index, row, 'duplicate_id', f"loc_id {loc_id} is also used on row {ids[loc_id]+1}; validation would drop this row",
                     {'action': 'set', 'field': 'loc_id', 'value': f'{loc_id}-dup{n}'})
            ids.setdefault(loc_id, index)
        if lat is not None and lon is not None:
            if south <= lon <= north and west <= lat <= east:
                flag(index, row, 'swapped_coordinates', f'lat {lat:g} and lon {lon:g} look swapped (Nairobi is about lat -1.3, lon 36.8)',
                     {'action': 'swap', 'field': 'lat/lon', 'value': None}, 'error')
            elif not in_coverage(lon, lat):
                flag(index, row, 'outside_coverage', f'({lat:g}, {lon:g}) is outside the Nairobi hazard maps and cannot be modelled', None, 'error')
            key = (round(lat, 5), round(lon, 5), housing, tiv)
            if key in records:
                flag(index, row, 'duplicate_record', f'Same place, class and value as row {records[key]+1} ({str(rows[records[key]].get("loc_id") or "")}); '
                     'possibly the same building listed twice', {'action': 'drop', 'field': None, 'value': None})
            records.setdefault(key, index)
        if tiv is not None and area and cost:
            expected = area*cost
            ratio = tiv/expected if expected else None
            if ratio and low <= ratio <= high:
                flag(index, row, 'tiv_about_10x', f'Insured value KES {_fmt(tiv)} is {ratio:.1f} times floor area × cost per m² (KES {_fmt(expected)}); '
                     'check whether a zero was added', {'action': 'set', 'field': 'tiv_kes', 'value': f'{expected:.2f}'})
            elif ratio and ratio*q['units_factor'] <= 1:
                for scale, word in ((1e3, 'thousands'), (1e6, 'millions')):
                    if 0.5 <= tiv*scale/expected <= 2:
                        flag(index, row, 'tiv_units', f'Insured value {_fmt(tiv)} is far below area × cost (KES {_fmt(expected)}); it may be in {word}',
                             {'action': 'set', 'field': 'tiv_kes', 'value': f'{tiv*scale:.2f}'}); break
                else:
                    flag(index, row, 'tiv_units', f'Insured value {_fmt(tiv)} is far below area × cost (KES {_fmt(expected)}); check the units')
        median = (class_defaults.get(housing) or {}).get('cost_per_m2_kes') if housing else None
        if cost and median and not 1/q['cost_ratio_factor'] <= cost/median <= q['cost_ratio_factor']:
            flag(index, row, 'cost_outlier', f'Cost per m² KES {_fmt(cost)} is {cost/median:.1f} times the {housing.replace("_", " ")} median of KES {_fmt(median)}',
                 {'action': 'set', 'field': 'cost_per_m2_kes', 'value': f'{median:.2f}'})
        if tiv == 0:
            flag(index, row, 'zero_value', 'Insured value is zero; this property cannot lose anything in the model')
    return flags

def apply_fixes(rows, flags, accepted):
    """Copy rows with the accepted fixes applied (indexes into ``flags``). Each fixed row records what changed in review_note."""
    accepted = [flags[i] for i in sorted(set(accepted)) if 0 <= i < len(flags) and flags[i]['fix']]
    drop = {f['row'] for f in accepted if f['fix']['action'] == 'drop'}
    out = []
    for index, row in enumerate(rows):
        if index in drop: continue
        row = dict(row); notes = []
        for f in (f for f in accepted if f['row'] == index):
            fix = f['fix']
            if fix['action'] == 'swap':
                row['lat'], row['lon'] = row.get('lon'), row.get('lat'); notes.append('lat/lon swapped')
            elif fix['action'] == 'set':
                notes.append(f"{fix['field']} {row.get(fix['field'])!s} → {fix['value']}")
                row[fix['field']] = fix['value']
        if notes: row['review_note'] = '; '.join(x for x in (row.get('review_note') or '', 'user-accepted fix: ' + ', '.join(notes)) if x)
        out.append(row)
    return out

def summarise(flags):
    groups = {}
    for f in flags:
        g = groups.setdefault(f['code'], {'code': f['code'], 'severity': f['severity'], 'count': 0, 'fixable': 0, 'examples': []})
        g['count'] += 1; g['fixable'] += bool(f['fix'])
        if len(g['examples']) < 3: g['examples'].append(f['message'])
    return sorted(groups.values(), key=lambda g: (g['severity'] != 'error', -g['count']))
