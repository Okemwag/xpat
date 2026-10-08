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
    "latitude": "lat",
    "y": "lat",
    "longitude": "lon",
    "long": "lon",
    "lng": "lon",
    "x": "lon",
    "id": "loc_id",
    "location_id": "loc_id",
    "property_id": "loc_id",
    "building_id": "loc_id",
    "construction": "housing_class",
    "construction_class": "housing_class",
    "building_type": "housing_class",
    "class": "housing_class",
    "tiv": "tiv_kes",
    "insured_value": "tiv_kes",
    "insured_value_kes": "tiv_kes",
    "sum_insured": "tiv_kes",
    "value_kes": "tiv_kes",
    "floor_area": "floor_area_m2",
    "area_m2": "floor_area_m2",
    "cost_per_m2": "cost_per_m2_kes",
}


def normalise_header(name):
    key = re.sub(r"[\s\-]+", "_", str(name).strip().lower()).strip("_")
    return HEADER_ALIASES.get(key, key)


def decode(data):
    """Return (text, encoding). Excel on Windows often writes cp1252 rather than UTF-8."""
    if isinstance(data, str):
        return data.lstrip("﻿"), "text"
    if len(data) > MAX_BYTES:
        raise ModelError("file_too_large", "CSV must be at most 10 MB")
    if not data.strip():
        raise ModelError("empty_file", "The file is empty")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16").lstrip("﻿"), "utf-16"
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252"


def _dialect(text):
    sample = text[:20000]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def parse_csv_text(text):
    text, _ = decode(text)
    if not text.strip():
        raise ModelError("empty_file", "The file is empty")
    reader = csv.reader(io.StringIO(text), _dialect(text))
    try:
        raw_header = next(reader)
    except StopIteration:
        raise ModelError("empty_file", "The file is empty") from None
    header = [normalise_header(h) for h in raw_header]
    if not any(header):
        raise ModelError("invalid_header", "The first row must contain column names")
    duplicates = sorted({h for h in header if h and header.count(h) > 1})
    if duplicates:
        raise ModelError(
            "invalid_header",
            "Duplicate columns after normalising names: " + ", ".join(duplicates),
        )
    rows = []
    for values in reader:
        if not any(v.strip() for v in values):
            continue
        if len(values) > len(header) and any(v.strip() for v in values[len(header) :]):
            raise ModelError(
                "invalid_csv",
                f"Data row {len(rows) + 1} has more values than there are columns",
            )
        rows.append(
            {
                h: (values[i].strip() if i < len(values) else "")
                for i, h in enumerate(header)
                if h
            }
        )
        if len(rows) > MAX_ROWS:
            raise ModelError(
                "portfolio_too_large", f"Prototype supports at most {MAX_ROWS} records"
            )
    if not rows:
        raise ModelError(
            "empty_portfolio", "The file has column names but no data rows"
        )
    return rows


def read_csv(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ModelError("file_too_large", "CSV must be at most 10 MB")
    return parse_csv_text(decode(path.read_bytes())[0])


# Excel schedules ----------------------------------------------------------------------------------
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MAX_XLSX_XML_BYTES = 50_000_000


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    index = 0
    for ch in letters:
        index = index * 26 + ord(ch) - 64
    return index - 1


def parse_xlsx(data):
    """Rows from the first worksheet of an .xlsx file (header in the first non-empty row). Standard library only."""
    import zipfile
    from xml.etree import ElementTree

    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ModelError("invalid_xlsx", "The Excel file could not be opened") from None
    with z:
        names = z.namelist()
        if any(z.getinfo(n).file_size > MAX_XLSX_XML_BYTES for n in names):
            raise ModelError("file_too_large", "The Excel file is too large to read")
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).iter(
                f"{_S}si"
            ):
                shared.append("".join(t.text or "" for t in si.iter(f"{_S}t")))
        sheets = sorted(
            n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)
        )
        if not sheets:
            raise ModelError("invalid_xlsx", "The Excel file has no worksheets")
        sheet = ElementTree.fromstring(z.read(sheets[0]))
    table = []
    for r in sheet.iter(f"{_S}row"):
        cells = {}
        for c in r.iter(f"{_S}c"):
            kind, ref = c.get("t"), c.get("r") or ""
            v = c.find(f"{_S}v")
            if kind == "s" and v is not None:
                value = shared[int(v.text)]
            elif kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(f"{_S}t"))
            elif kind == "b" and v is not None:
                value = "True" if v.text == "1" else "False"
            else:
                value = v.text if v is not None else ""
            if ref:
                cells[_col_index(ref)] = str(value).strip()
        if cells:
            table.append([cells.get(i, "") for i in range(max(cells) + 1)])
    table = [row for row in table if any(row)]
    if len(table) < 2:
        raise ModelError(
            "empty_portfolio", "The first worksheet has no data rows under a header row"
        )
    width = max(len(r) for r in table)
    lines = [
        ",".join(
            '"' + cell.replace('"', '""') + '"'
            for cell in row + [""] * (width - len(row))
        )
        for row in table
    ]
    return parse_csv_text("\n".join(lines))


CONTRACT = {"loc_id", "lat", "lon", "housing_class", "tiv_kes"}


def classify_upload(data, filename=""):
    """'table' for CSV/Excel property schedules, 'document' for anything to be read by AI (PDF, Word, prose)."""
    if data[:4] == b"PK\x03\x04":
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
            if "xl/workbook.xml" in names:
                return "xlsx"
            if "word/document.xml" in names:
                return "document"
        except zipfile.BadZipFile:
            pass
        raise ModelError(
            "unsupported_file",
            "This file type is not supported; use CSV, Excel (.xlsx), PDF, Word (.docx) or text",
        )
    if data[:5] == b"%PDF-" or data[:4] == b"\xd0\xcf\x11\xe0":
        return "document"
    try:
        rows = parse_csv_text(data)
    except ModelError:
        return "document"
    return "table" if len(CONTRACT & set(rows[0])) >= 3 else "document"
