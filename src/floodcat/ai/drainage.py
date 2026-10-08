"""Drainage-deficit factor from flood reports: chunk → local embeddings → semantic scoring → places → per-place factor.

Pipeline (no text generation in the default `local` mode):
1. Reports are redacted (e-mails, phones) and cut into sentence windows (`embeddings.chunk_text`).
2. Each chunk is embedded locally and compared with fixed descriptions of drainage failure and of contrasts (a river
   overflowing, a forecast, unrelated news). A chunk is drainage evidence when its drainage similarity and its margin
   over the best contrast both clear thresholds set on the dev split of evaluation/drainage_passages.json (ASSUMPTION).
   Its strength runs 0.5 → 1 with the margin.
3. Places come from the offline OSM gazetteer (`places.PlaceIndex`) in `local` mode, or from a language model reading
   only the drainage chunks in `ollama` / `gemini` mode (far less text than the whole report, so much faster).
4. Per place, independent reports combine by noisy-OR, each counted once (near-duplicate reports collapse):
       factor = 1 − Π_reports (1 − strongest passage in that report naming the place)
   The factor is an AI-derived PROXY in 0–1, not a probability or a depth.
5. A person sends a place to review; it becomes an ordinary evidence item (mechanism drainage, confidence = factor) and
   changes hazard only after a named reviewer approves it, through the same uplift as other evidence.
"""

import hashlib
from datetime import date
from ..core.errors import ModelError
from .embeddings import chunk_text

MODES = ("local", "ollama", "gemini")
MODE_LABELS = {
    "local": "Local embeddings (offline, no text generation)",
    "ollama": "Local embeddings + Ollama (offline)",
    "gemini": "Local embeddings + Gemini (online)",
}
PROMPT_VERSION = "drainage-v1"


def scale(value, low, high):
    return min(1.0, max(0.0, (value - low) / (high - low)))


# Scoring -------------------------------------------------------------------------------------------------------
class Scorer:
    """Embeds the fixed drainage and contrast descriptions once; scores chunk vectors against them."""

    def __init__(self, embedder, settings):
        self.embedder, self.settings = embedder, settings
        self._q = self._c = None

    def _queries(self):
        if self._q is None:
            self._q = self.embedder.embed_queries(self.settings["drainage_queries"])
            self._c = self.embedder.embed_queries(self.settings["contrast_queries"])
        return self._q, self._c

    def score(self, vectors):
        """[(drainage_similarity, contrast_similarity, strength)] per row of `vectors`."""
        if len(vectors) == 0:
            return []
        q, c = self._queries()
        pos = (vectors @ q.T).max(axis=1)
        neg = (vectors @ c.T).max(axis=1)
        s = self.settings
        out = []
        for p, n in zip(pos.tolist(), neg.tolist()):
            hit = p >= s["min_similarity"] and p - n >= s["min_margin"]
            strength = 0.5 + 0.5 * scale(p - n, s["min_margin"], s["full_margin"]) if hit else 0.0
            out.append((round(p, 4), round(n, 4), round(strength, 4)))
        return out


def process_text(text, embedder, scorer, settings):
    """Redact, chunk, embed and score one report. Returns chunks with vectors (for storage) and the document vector."""
    import numpy as np
    from .privacy import redact

    text, _ = redact(str(text or ""))
    if not text.strip():
        raise ModelError("empty_report", "The report has no readable text")
    chunks = chunk_text(text, settings["chunk_max_words"], settings["chunk_overlap_sentences"])
    vectors = embedder.embed([c["text"] for c in chunks])
    for c, v, (p, n, st) in zip(chunks, vectors, scorer.score(vectors)):
        c.update(vector=v, drainage_similarity=p, contrast_similarity=n, strength=st)
    doc_vector = vectors.mean(axis=0)
    doc_vector = doc_vector / (np.linalg.norm(doc_vector) or 1)
    return {"text": text, "chunks": chunks, "vector": doc_vector.astype(np.float32),
            "content_hash": hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()}


# Place assessment per mode ---------------------------------------------------------------------------------------
def assess_local(chunks, places, lookback=1):
    """Every drainage chunk names its places; the place takes the chunk's strength (strongest chunk wins).

    Reports often name the place one sentence before the cause ("Parts of South C were under water. The drains were
    blocked…"), so when a drainage chunk names no place, up to `lookback` preceding chunks are searched — never a
    chunk that reads more like a contrast (river overflow) than drainage.
    """
    best = {}
    for i, c in enumerate(chunks):
        if c["strength"] <= 0:
            continue
        found, quote = places.find(c["text"]), c["text"]
        for j in range(i - 1, max(-1, i - 1 - lookback), -1):
            if found:
                break
            prev = chunks[j]
            if prev.get("contrast_similarity", 0) > prev.get("drainage_similarity", 0):
                break
            found, quote = places.find(prev["text"]), prev["text"] + " " + c["text"]
        for p in found:
            if p["name"] not in best or c["strength"] > best[p["name"]]["strength"]:
                best[p["name"]] = {"place": p["name"], "lat": p["lat"], "lon": p["lon"], "strength": c["strength"],
                                   "quote": quote, "chunk": i, "method": "gazetteer"}
    return sorted(best.values(), key=lambda a: -a["strength"])


def assess_llm(chunks, title, llm, places, settings, gazetteer=None):
    """A language model names place and cause in the drainage chunks only; quotes must be verbatim in those chunks.

    Places resolve through the offline gazetteer first, then the online geocoder if given. Only drainage and
    surface-runoff items count; strength = the model's confidence × the strength of the chunk holding the quote.
    """
    from .extraction import extract
    from .gemini import model_used

    picked = sorted((c for c in chunks if c["strength"] > 0), key=lambda c: -c["strength"])[: settings["llm_top_k"]]
    if not picked:
        return [], None
    text = "\n\n".join(c["text"] for c in picked)
    result = extract(text, title, llm, None)
    best = {}
    for cand in result["candidates"]:
        if cand["mechanism"] not in ("drainage", "surface_runoff"):
            continue
        found = places.find(cand["location_name"]) or places.find(cand["location_name"].title())
        if found:
            lat, lon, name, method = found[0]["lat"], found[0]["lon"], found[0]["name"], "gazetteer"
        elif gazetteer and (g := gazetteer.lookup(cand["location_name"])):
            lat, lon, name, method = g["lat"], g["lon"], cand["location_name"], g["method"]
        else:
            continue
        chunk = next((c for c in picked if " ".join(cand["quote"].split()) in " ".join(c["text"].split())), picked[0])
        strength = round(cand["confidence"] * chunk["strength"], 4)
        if strength > 0 and (name not in best or strength > best[name]["strength"]):
            best[name] = {"place": name, "lat": lat, "lon": lon, "strength": strength, "quote": cand["quote"],
                          "chunk": chunks.index(chunk), "method": method}
    return sorted(best.values(), key=lambda a: -a["strength"]), model_used(llm)


# Aggregation ---------------------------------------------------------------------------------------------------
def canonical_documents(documents, threshold):
    """Map each document id to the first earlier document it duplicates (same text, or vectors at/above threshold)."""
    import numpy as np

    canon, kept = {}, []
    for d in sorted(documents, key=lambda d: (d["published"] or "", d["id"])):
        match = next((k for k in kept if k["content_hash"] == d["content_hash"]
                      or float(np.dot(k["vector"], d["vector"])) >= threshold), None)
        canon[d["id"]] = match["id"] if match else d["id"]
        if not match:
            kept.append(d)
    return canon


def place_factors(documents, settings):
    """Per place: factor (noisy-OR over independent, de-duplicated reports), supporting reports and best passages.

    `documents`: [{id, title, url, published, independent, content_hash, vector, assessments}]
    """
    canon = canonical_documents(documents, settings["duplicate_similarity"])
    by_place = {}
    for d in documents:
        for a in d.get("assessments") or []:
            e = by_place.setdefault(a["place"], {"place": a["place"], "lat": a["lat"], "lon": a["lon"], "reports": {}})
            key = canon[d["id"]]
            prev = e["reports"].get(key)
            if prev is None or a["strength"] > prev["strength"]:
                e["reports"][key] = {"document_id": d["id"], "title": d["title"], "url": d.get("url"),
                                     "published": d.get("published"), "independent": d["independent"],
                                     "strength": a["strength"], "quote": a["quote"], "method": a["method"]}
    out = []
    for e in by_place.values():
        reports = sorted(e["reports"].values(), key=lambda r: -r["strength"])
        remaining = 1.0
        for r in reports:
            remaining *= 1 - r["strength"]
        out.append({"place": e["place"], "lat": e["lat"], "lon": e["lon"], "factor": round(1 - remaining, 4),
                    "report_count": len(reports), "all_independent": all(r["independent"] for r in reports),
                    "reports": reports})
    return sorted(out, key=lambda p: (-p["factor"], p["place"]))


def to_evidence(place, reviewer_note=None):
    """An evidence item (unapproved) carrying the place's factor as its confidence."""
    from .evidence import Evidence

    docs = sorted(r["document_id"] for r in place["reports"])
    digest = hashlib.sha256(f"{place['place']}|{'|'.join(docs)}".encode()).hexdigest()[:12]
    titles = [r["title"] for r in place["reports"]]
    source = "; ".join(titles[:3]) + (f" (+{len(titles) - 3} more)" if len(titles) > 3 else "")
    dates = [r["published"] for r in place["reports"] if r.get("published")]
    best = place["reports"][0]
    return Evidence(
        evidence_id=f"ddf-{digest}",
        source=f"Drainage reports ({place['report_count']}): {source}"[:500],
        quote=best["quote"][:2000],
        event_date=max(dates) if dates else "",
        location_name=place["place"],
        lat=place["lat"],
        lon=place["lon"],
        location_method="gazetteer" if best["method"] == "gazetteer" else best["method"],
        mechanism="drainage",
        confidence=min(1.0, place["factor"]),
        independent_of_hotspot_list=place["all_independent"],
    )


# Evaluation ----------------------------------------------------------------------------------------------------
def evaluate(passages, scorer, embedder, split):
    """Precision and recall of 'drainage evidence' on a labelled split."""
    rows = [p for p in passages if p["split"] == split]
    vectors = embedder.embed([p["text"] for p in rows])
    tp = fp = fn = 0
    errors = []
    for p, (pos, neg, st) in zip(rows, scorer.score(vectors)):
        hit, truth = st > 0, p["label"] == "drainage"
        tp += hit and truth
        fp += hit and not truth
        fn += truth and not hit
        if hit != truth:
            errors.append({"label": p["label"], "text": p["text"], "drainage_similarity": pos, "margin": round(pos - neg, 4)})
    return {"split": split, "passages": len(rows), "drainage_passages": sum(p["label"] == "drainage" for p in rows),
            "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "river_flagged": sum(1 for e in errors if e["label"] == "river"), "errors": errors,
            "generated": date.today().isoformat()}


def validate_settings(s):
    need = {"source", "embedding_model", "chunk_max_words", "chunk_overlap_sentences", "place_lookback_chunks", "drainage_queries",
            "contrast_queries", "min_similarity", "min_margin", "full_margin", "duplicate_similarity", "llm_top_k",
            "place_ambiguity_m", "ignore_place_names", "not_before_words"}
    if not isinstance(s, dict) or set(s) != need:
        raise ModelError("invalid_config", "drainage_reports needs " + ", ".join(sorted(need)))
    if not s["drainage_queries"] or not s["contrast_queries"]:
        raise ModelError("invalid_config", "drainage_reports needs drainage and contrast descriptions")
    if not 0 < float(s["min_margin"]) < float(s["full_margin"]):
        raise ModelError("invalid_config", "drainage_reports: 0 < min_margin < full_margin")
    for key in ("min_similarity", "duplicate_similarity"):
        if not 0 < float(s[key]) <= 1:
            raise ModelError("invalid_config", f"drainage_reports.{key} must be in (0, 1]")
    for key in ("chunk_max_words", "llm_top_k"):
        if isinstance(s[key], bool) or not isinstance(s[key], int) or s[key] < 1:
            raise ModelError("invalid_config", f"drainage_reports.{key} must be a positive integer")
    for key in ("chunk_overlap_sentences", "place_lookback_chunks"):
        if isinstance(s[key], bool) or not isinstance(s[key], int) or s[key] < 0:
            raise ModelError("invalid_config", f"drainage_reports.{key} must be 0 or more")
    return {**s, "drainage_queries": tuple(s["drainage_queries"]), "contrast_queries": tuple(s["contrast_queries"]),
            "ignore_place_names": tuple(s["ignore_place_names"]), "not_before_words": tuple(s["not_before_words"]),
            **{k: float(s[k]) for k in ("min_similarity", "min_margin", "full_margin", "duplicate_similarity", "place_ambiguity_m")}}
