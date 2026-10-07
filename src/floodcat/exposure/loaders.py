import csv
import io
from pathlib import Path
from ..core.errors import ModelError

def parse_csv_text(text):
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames):
        raise ModelError('invalid_header','CSV requires unique column names')
    rows=[]
    for row in reader:
        if None in row: raise ModelError('invalid_csv','CSV row has more values than headers')
        rows.append(row)
        if len(rows)>10000: raise ModelError('portfolio_too_large','Prototype supports at most 10000 records')
    return rows

def read_csv(path):
    path=Path(path)
    if path.stat().st_size>10_000_000: raise ModelError('file_too_large','CSV must be at most 10 MB')
    return parse_csv_text(path.read_text(encoding='utf-8-sig'))
