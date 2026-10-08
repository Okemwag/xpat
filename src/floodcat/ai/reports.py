"""Flood-report sources and ingestion for the drainage-deficit factor.

Sources:
- ReliefWeb (public humanitarian reports; https://apidoc.reliefweb.int). Needs an approved app name in
  RELIEFWEB_APPNAME; requests carry only the search terms and dates, never organisation data.
- Uploads: PDF, Word or text files (one report each), or a CSV of articles with a `text` column (plus optional
  `title`, `url`, `date`). Read with the same hardened reader as submission documents; contact details are removed.
"""

import csv
import io
import os
import re
from datetime import date
from ..core.errors import ModelError

RELIEFWEB = "https://api.reliefweb.int/v2/reports"
MAX_REPORTS = 200


def _clean_html(text):
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _iso_day(value):
    value = str(value or "")[:10]
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


# Uploads -------------------------------------------------------------------------------------------------------
def from_upload(data, filename):
    """[{title, text, url, published, source_kind}] from one uploaded file."""
    from .documents import read_document
    from .privacy import redact

    name = filename.rsplit("/", 1)[-1]
    if name.lower().endswith(".csv"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows or "text" not in {k.strip().lower() for k in rows[0] if k}:
            raise ModelError("invalid_report", f"{name}: a CSV of articles needs a `text` column")
        out = []
        for i, row in enumerate(rows[:MAX_REPORTS], 1):
            row = {str(k).strip().lower(): v for k, v in row.items() if k}
            body = str(row.get("text") or "").strip()
            if not body:
                continue
            out.append({"title": (row.get("title") or f"{name} row {i}").strip(), "text": redact(body)[0],
                        "url": (row.get("url") or "").strip(), "published": _iso_day(row.get("date")),
                        "source_kind": "upload"})
        if not out:
            raise ModelError("invalid_report", f"{name}: no rows with text")
        return out
    doc = read_document(data, name)
    return [{"title": name.rsplit(".", 1)[0], "text": doc["text"], "url": "", "published": "", "source_kind": "upload"}]


# ReliefWeb -----------------------------------------------------------------------------------------------------
def reliefweb_available():
    return bool(os.getenv("RELIEFWEB_APPNAME", "").strip())


def reliefweb_search(query, date_from=None, date_to=None, limit=20, appname=None, transport=None):
    """Kenya reports matching `query` (title and body), newest first, as [{title, text, url, published, source}]."""
    import httpx

    appname = appname or os.getenv("RELIEFWEB_APPNAME", "").strip()
    if not appname:
        raise ModelError("reliefweb_unavailable", "Set RELIEFWEB_APPNAME (request one at apidoc.reliefweb.int) to search ReliefWeb")
    conditions = [{"field": "country.iso3", "value": "KEN"}]
    if date_from or date_to:
        conditions.append({"field": "date.original", "value": {
            **({"from": f"{date_from}T00:00:00+00:00"} if date_from else {}),
            **({"to": f"{date_to}T23:59:59+00:00"} if date_to else {})}})
    body = {
        "query": {"value": str(query or "flood").strip(), "fields": ["title", "body"], "operator": "AND"},
        "filter": {"operator": "AND", "conditions": conditions},
        "fields": {"include": ["title", "body", "url_alias", "url", "date.original", "source.shortname"]},
        "sort": ["date.original:desc"],
        "limit": max(1, min(int(limit), MAX_REPORTS)),
    }
    try:
        with httpx.Client(timeout=60, transport=transport) as client:
            r = client.post(RELIEFWEB, params={"appname": appname}, json=body)
    except httpx.HTTPError:
        raise ModelError("reliefweb_failed", "ReliefWeb could not be reached; nothing was changed") from None
    if r.status_code == 403:
        raise ModelError("reliefweb_unavailable", "ReliefWeb refused the app name; check RELIEFWEB_APPNAME")
    if r.status_code >= 400:
        raise ModelError("reliefweb_failed", f"ReliefWeb request failed ({r.status_code}); nothing was changed")
    out = []
    for item in r.json().get("data", []):
        f = item.get("fields", {})
        text = _clean_html(f.get("body"))
        if not text:
            continue
        sources = ", ".join(s.get("shortname", "") for s in f.get("source", []) if s.get("shortname"))
        out.append({"title": (f.get("title") or "ReliefWeb report").strip() + (f" — {sources}" if sources else ""),
                    "text": text, "url": f.get("url_alias") or f.get("url") or "",
                    "published": _iso_day((f.get("date") or {}).get("original")), "source_kind": "reliefweb"})
    return out


# Ingestion -----------------------------------------------------------------------------------------------------
def ingest(report, embedder, scorer, places, settings, mode="local", llm=None, gazetteer=None):
    """Process one report into the record `platform.data.add_report` stores."""
    from .drainage import MODES, assess_llm, assess_local, process_text

    if mode not in MODES:
        raise ModelError("invalid_mode", f"Unknown mode {mode}")
    done = process_text(report["text"], embedder, scorer, settings)
    if mode == "local":
        assessments, model = assess_local(done["chunks"], places, settings["place_lookback_chunks"]), None
    else:
        if llm is None:
            raise ModelError("ai_unavailable", f"{mode} mode needs a language model")
        assessments, model = assess_llm(done["chunks"], report["title"], llm, places, settings, gazetteer)
    return {**report, **done, "assessments": assessments, "mode": mode, "model": model,
            "embedding_model": embedder.name}
