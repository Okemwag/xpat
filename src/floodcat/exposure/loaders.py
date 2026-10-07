"""CSV intake for exposure files, including ones made by hand or exported from Excel."""
import csv
import io
import re
from pathlib import Path
from ..core.errors import ModelError

MAX_BYTES = 10_000_000
MAX_ROWS = 10_000
# Common header spellings mapped onto the exposure contract. Matching is case- and space-insensitive.
HEADER_ALIASES = {
    'latitude': 'lat', 'y': 'lat',
    'longitude': 'lon', 'long': 'lon', 'lng': 'lon', 'x': 'lon',
    'id': 'loc_id', 'location_id': 'loc_id', 'property_id': 'loc_id', 'building_id': 'loc_id',
    'construction': 'housing_class', 'construction_class': 'housing_class', 'building_type': 'housing_class', 'class': 'housing_class',
    'tiv': 'tiv_kes', 'insured_value': 'tiv_kes', 'insured_value_kes': 'tiv_kes', 'sum_insured': 'tiv_kes', 'value_kes': 'tiv_kes',
    'floor_area': 'floor_area_m2', 'area_m2': 'floor_area_m2',
    'cost_per_m2': 'cost_per_m2_kes',
}

def normalise_header(name):
    key = re.sub(r'[\s\-]+', '_', str(name).strip().lower()).strip('_')
    return HEADER_ALIASES.get(key, key)

def decode(data):
    """Return (text, encoding). Excel on Windows often writes cp1252 rather than UTF-8."""
    if isinstance(data, str): return data.lstrip('﻿'), 'text'
    if len(data) > MAX_BYTES: raise ModelError('file_too_large', 'CSV must be at most 10 MB')
    if not data.strip(): raise ModelError('empty_file', 'The file is empty')
    if data[:2] in (b'\xff\xfe', b'\xfe\xff'): return data.decode('utf-16').lstrip('﻿'), 'utf-16'
    try: return data.decode('utf-8-sig'), 'utf-8'
    except UnicodeDecodeError: return data.decode('cp1252', errors='replace'), 'cp1252'

def _dialect(text):
    sample = text[:20000]
    try: return csv.Sniffer().sniff(sample, delimiters=',;\t|')
    except csv.Error: return csv.excel

def parse_csv_text(text):
    text, _ = decode(text)
    if not text.strip(): raise ModelError('empty_file', 'The file is empty')
    reader = csv.reader(io.StringIO(text), _dialect(text))
    try: raw_header = next(reader)
    except StopIteration: raise ModelError('empty_file', 'The file is empty') from None
    header = [normalise_header(h) for h in raw_header]
    if not any(header): raise ModelError('invalid_header', 'The first row must contain column names')
    duplicates = sorted({h for h in header if h and header.count(h) > 1})
    if duplicates: raise ModelError('invalid_header', 'Duplicate columns after normalising names: '+', '.join(duplicates))
    rows = []
    for values in reader:
        if not any(v.strip() for v in values): continue
        if len(values) > len(header) and any(v.strip() for v in values[len(header):]):
            raise ModelError('invalid_csv', f'Data row {len(rows)+1} has more values than there are columns')
        rows.append({h: (values[i].strip() if i < len(values) else '') for i, h in enumerate(header) if h})
        if len(rows) > MAX_ROWS: raise ModelError('portfolio_too_large', f'Prototype supports at most {MAX_ROWS} records')
    if not rows: raise ModelError('empty_portfolio', 'The file has column names but no data rows')
    return rows

def read_csv(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES: raise ModelError('file_too_large', 'CSV must be at most 10 MB')
    return parse_csv_text(decode(path.read_bytes())[0])
