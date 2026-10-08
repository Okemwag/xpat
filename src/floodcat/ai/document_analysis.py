"""What a submission document says beyond its property list: five capabilities, checked by fixed rules.

The same single AI call that extracts the properties (ai/submission.py) also returns, each with a verbatim quote:
  placement terms (sums insured, premium, shares, deductions, period …), the document's sections tagged as
  flood-relevant or not, and any flood history. Everything below is deterministic:

1. Locate multiple data points across the text — every term is kept only with a quote found word-for-word in the
   document and, for numbers, the number inside its quote; missing key terms are listed.
2. Distinguish relevant from irrelevant information — sections grouped by topic, flood-relevant or not, with the reason
   (e.g. a bush-fire clause is noise for a flood model; a debris-removal extension adds to the loss).
3. Cross-reference building specifications with risk indicators — construction, occupancy, location and value set
   against the vulnerability curve, the hazard map, the named flood areas and the document's own flood statements.
4. Summarise complex flood history — dated events as a timeline with counts, causes, depths and stated losses; when
   the document has none, it says so and lists what to ask for.
5. Calculate implied risk metrics — premium rate, per mille, premium after deductions, consistency of shares, sums and
   premiums, and once the model has run, modelled loss against premium and sum insured.
"""

import re
from decimal import Decimal, InvalidOperation

TERM_LABELS = {
    "sum_insured_100": "Sum insured (100%)",
    "premium_100": "Premium (100%)",
    "placed_share_pct": "Share placed with reinsurers (%)",
    "placed_sum_insured": "Sum insured for the placed share",
    "placed_premium": "Premium for the placed share",
    "deductions_pct": "Deductions: commission and brokerage (%)",
    "accepted_share_pct": "Share accepted by one reinsurer (%)",
    "accepted_sum_insured": "Accepted sum insured",
    "accepted_premium": "Accepted premium",
    "period_start": "Cover starts",
    "period_end": "Cover ends",
    "class_of_business": "Class of business",
    "currency": "Currency",
    "cedant": "Cedant / reinsured",
    "original_insured": "Original insured",
    "broker": "Broker",
    "accepting_reinsurer": "Accepting reinsurer",
    "flood_deductible": "Flood deductible",
    "flood_limit": "Flood limit",
    "other_peril_deductible": "Deductible for another peril",
    "debris_removal_pct": "Debris removal extension (% of sum insured)",
    "event_definition_hours": "Event definition (hours)",
    "valuation_basis": "Basis of valuation",
    "other": "Other term",
}
NUMERIC = {"sum_insured_100", "premium_100", "placed_share_pct", "placed_sum_insured", "placed_premium", "deductions_pct",
           "accepted_share_pct", "accepted_sum_insured", "accepted_premium", "debris_removal_pct", "event_definition_hours"}
KEY_TERMS = ("sum_insured_100", "premium_100", "placed_share_pct", "flood_deductible", "period_start", "period_end")
TOPICS = ("placement_terms", "valuation", "deductible_limit", "event_definition", "location", "construction_occupancy",
          "flood_history", "flood_cover_extension", "other_peril", "administrative")
TOPIC_LABELS = {
    "placement_terms": "Placement terms", "valuation": "Valuation", "deductible_limit": "Deductibles and limits",
    "event_definition": "Event definition", "location": "Location", "construction_occupancy": "Construction and occupancy",
    "flood_history": "Flood history", "flood_cover_extension": "Cover extension affecting a flood loss",
    "other_peril": "Another peril", "administrative": "Administration",
}

SYSTEM_ADDENDUM = """
Also return, for the document as a whole:
- placement_terms: each commercial term the document states, as {term, value_number, value_text, quote}. term is one of:
  sum_insured_100, premium_100, placed_share_pct (the share placed with reinsurers, e.g. "Our Fac/RE Share"),
  placed_sum_insured, placed_premium, deductions_pct (commission/brokerage/total deductions), accepted_share_pct (one
  reinsurer's accepted share), accepted_sum_insured, accepted_premium, period_start, period_end, class_of_business,
  currency, cedant, original_insured, broker, accepting_reinsurer (company names only, never people), flood_deductible,
  flood_limit, other_peril_deductible (e.g. an earthquake excess), debris_removal_pct, event_definition_hours,
  valuation_basis, other. value_number: the number as stated (percent as a number, e.g. 7.5); value_text: the wording.
- sections: each clause or block of the document as {heading, topic, flood_relevant, reason}. topic is one of
  placement_terms, valuation, deductible_limit, event_definition, location, construction_occupancy, flood_history,
  flood_cover_extension, other_peril, administrative. heading: copied exactly from the document. flood_relevant: true
  only if it can change a flood loss, the location, the building, the terms or the flood history. reason: one short phrase.
- flood_history: each past flood event or flood claim the document reports, as {date_text, year, place, description,
  depth_m, loss_kes, cause, quote}; cause is drainage, river, surface_runoff, other or unknown. Empty if none.
For each property also give occupancy_text (what the building is used for, as written) and occupancy_quote."""

_Q = {"type": "string"}
_N = {"type": ["number", "null"]}
SCHEMA_ADDITIONS = {
    "placement_terms": {"type": "array", "items": {"type": "object", "required": ["term", "value_number", "value_text", "quote"],
                        "properties": {"term": {"type": "string", "enum": list(TERM_LABELS)}, "value_number": _N,
                                       "value_text": _Q, "quote": _Q}}},
    "sections": {"type": "array", "items": {"type": "object", "required": ["heading", "topic", "flood_relevant", "reason"],
                 "properties": {"heading": _Q, "topic": {"type": "string", "enum": list(TOPICS)},
                                "flood_relevant": {"type": "boolean"}, "reason": _Q}}},
    "flood_history": {"type": "array", "items": {"type": "object",
                      "required": ["date_text", "year", "place", "description", "depth_m", "loss_kes", "cause", "quote"],
                      "properties": {"date_text": _Q, "year": {"type": ["integer", "null"]}, "place": _Q, "description": _Q,
                                     "depth_m": _N, "loss_kes": _N,
                                     "cause": {"type": "string", "enum": ["drainage", "river", "surface_runoff", "other", "unknown"]},
                                     "quote": _Q}}},
}
PROPERTY_ADDITIONS = {"occupancy_text": _Q, "occupancy_quote": _Q}


def _squash(text):
    return " ".join(str(text or "").split()).lower()


def _found(quote, text):
    q = _squash(quote)
    return bool(q) and q in _squash(text)


def _number_in(value, quote):
    """True when `value` appears as a number in the quote (thousands separators ignored)."""
    try:
        target = Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError, TypeError):
        return False
    for n in re.findall(r"\d+(?:\.\d+)?", re.sub(r"(?<=\d),(?=\d)", "", str(quote or ""))):
        if Decimal(n).normalize() == target:
            return True
    return False


def _d(x):
    return Decimal(str(x))


# 1 · Data points -------------------------------------------------------------------------------------------------
def data_points(response, text):
    terms, dropped = [], []
    for t in response.get("placement_terms") or []:
        if not isinstance(t, dict) or t.get("term") not in TERM_LABELS:
            continue
        quote, num = t.get("quote") or "", t.get("value_number")
        ok = _found(quote, text) and (t["term"] not in NUMERIC or num is None or _number_in(num, quote))
        entry = {"term": t["term"], "label": TERM_LABELS[t["term"]], "value_number": num,
                 "value_text": str(t.get("value_text") or "").strip()[:300], "quote": quote[:400], "verified": ok}
        (terms if ok else dropped).append(entry)
    found = {t["term"] for t in terms}
    return {
        "terms": terms,
        "unverified": dropped,
        "missing": [TERM_LABELS[k] for k in KEY_TERMS if k not in found],
        "count": len(terms),
    }


def term_value(points, key):
    return next((t["value_number"] for t in points["terms"] if t["term"] == key and t["value_number"] is not None), None)


# 2 · Relevance ---------------------------------------------------------------------------------------------------
def relevance(response, text):
    relevant, irrelevant = [], []
    for s in response.get("sections") or []:
        if not isinstance(s, dict) or s.get("topic") not in TOPICS:
            continue
        item = {"heading": str(s.get("heading") or "").strip()[:200], "topic": TOPIC_LABELS[s["topic"]],
                "reason": str(s.get("reason") or "").strip()[:200], "found": _found(s.get("heading"), text)}
        (relevant if s.get("flood_relevant") else irrelevant).append(item)
    total = len(relevant) + len(irrelevant)
    return {"relevant": relevant, "irrelevant": irrelevant, "share_relevant": len(relevant) / total if total else None}


# 3 · Cross-reference --------------------------------------------------------------------------------------------
RESIDENTIAL = re.compile(r"\b(resid|home|house|apartment|flat|dwelling)", re.I)


def cross_reference(properties, response, config):
    raw = response.get("properties") or []
    out = []
    for i, p in enumerate(properties):
        src = raw[i] if i < len(raw) and isinstance(raw[i], dict) else {}
        cls = p["row"].get("housing_class") or ""
        adj = config.class_adjustments.get(cls) if cls else None
        occ = str(src.get("occupancy_text") or "").strip()
        primary = (p.get("hazard") or [None])[0]
        scores = (primary or {}).get("scores") or {}
        tag = (primary or {}).get("nearest_hotspot") or {}
        rows = []
        rows.append({
            "indicator": "Construction → damage curve",
            "document": p["fields"].get("construction", {}).get("value") or "—",
            "model": (f"{cls}: reads the JRC curve at depth ÷ {adj['jrc_depth_scale']:g}, damage capped at {adj['damage_cap']:.0%}"
                      if adj else "not classified — choose a class before running"),
            "flag": None if adj else "missing",
        })
        rows.append({
            "indicator": "Occupancy → curve type",
            "document": occ or "not stated",
            "model": "JRC Africa curve is for residential buildings",
            "flag": None if not occ or RESIDENTIAL.search(occ) else
            "non-residential use: machinery, stock and fit-out are not in the residential curve — treat the loss as indicative",
        })
        if scores:
            flagged = [t for t, v in scores.items() if v and v > 0]
            rows.append({
                "indicator": "Location → hazard map",
                "document": f"{primary['source']} ({primary['lat']:.4f}, {primary['lon']:.4f})",
                "model": ", ".join(f"{t} {v:.2f}" for t, v in scores.items()),
                "flag": None if flagged else "score 0 in every tier: not flagged by the map (blind to drainage), not proven safe",
            })
        if tag:
            rows.append({
                "indicator": "Location → named flood areas",
                "document": "—",
                "model": f"nearest: {tag.get('nearest_hotspot')} at {tag.get('hotspot_distance_m', 0) / 1000:.1f} km",
                "flag": next((c["message"] for c in p["checks"] if c["code"] == "near_named_area_low_score"),
                             "within the grouping radius of a government-named flood area" if tag.get("within_hotspot_radius") else None),
            })
        claims = p.get("flood_claims") or []
        if claims:
            rows.append({
                "indicator": "Document's flood statements → model",
                "document": "; ".join(c["claim"] for c in claims[:3]),
                "model": "compared in the checks above",
                "flag": next((c["message"] for c in p["checks"] if c["code"] == "proxy_blind"), None),
            })
        tiv, gfa = p["row"].get("tiv_kes"), p["row"].get("gross_floor_area_m2")
        if tiv and gfa:
            rows.append({"indicator": "Value ÷ floor area", "document": f"KES {tiv:,.0f} ÷ {gfa:,.0f} m²",
                         "model": f"KES {tiv / gfa:,.0f} per m²",
                         "flag": next((c["message"] for c in p["checks"] if c["code"] in ("high_value", "low_value")), None)})
        out.append({"property": p["name"], "rows": rows})
    return out


# 4 · Flood history ----------------------------------------------------------------------------------------------
def flood_history(response, text, properties):
    events = []
    for e in response.get("flood_history") or []:
        if not isinstance(e, dict):
            continue
        events.append({k: e.get(k) for k in ("date_text", "year", "place", "description", "depth_m", "loss_kes", "cause")}
                      | {"quote": e.get("quote") or "", "verified": _found(e.get("quote"), text)})
    events = [e for e in events if e["verified"]]
    events.sort(key=lambda e: (e["year"] is None, e["year"] or 0))
    years_stated = next((p["fields"].get("loss_history_years", {}).get("value") for p in properties
                         if p["fields"].get("loss_history_years")), None)
    if not events:
        return {"events": [], "summary": "The document gives no flood history: no dated flood events or flood claims.",
                "ask_for": ["Flood claims for the last 5–10 years (date, cause, depth, amount paid)",
                            "Any flood defences, drainage works or raised floor levels on site",
                            "Whether the site or its access roads flooded in the March–May 2024 or March 2026 rains"]}
    years = [e["year"] for e in events if e["year"]]
    losses = [_d(e["loss_kes"]) for e in events if e["loss_kes"]]
    causes = {}
    for e in events:
        causes[e["cause"]] = causes.get(e["cause"], 0) + 1
    depths = [e["depth_m"] for e in events if e["depth_m"]]
    parts = [f"{len(events)} flood event{'s' if len(events) != 1 else ''}"
             + (f" between {min(years)} and {max(years)}" if len(years) > 1 else f" in {years[0]}" if years else "")]
    if losses:
        parts.append(f"stated losses total KES {sum(losses):,.0f}")
    parts.append("causes: " + ", ".join(f"{k} ×{v}" for k, v in sorted(causes.items(), key=lambda x: -x[1])))
    if depths:
        parts.append(f"deepest {max(depths):g} m")
    if years and len(years) > 1:
        span = max(years) - min(years) + 1
        parts.append(f"about one flood every {span / len(events):.1f} years over the period described")
    return {"events": events, "summary": "; ".join(parts) + ".", "ask_for": [] if losses else
            ["The amount paid for each flood event"], "years_of_history_stated": years_stated}


# 5 · Implied metrics --------------------------------------------------------------------------------------------
def implied_metrics(points, report=None, basis="insured"):
    """Rates and consistency checks from the document; modelled loss against premium when a report is given."""
    si, prem = term_value(points, "sum_insured_100"), term_value(points, "premium_100")
    share, accepted = term_value(points, "placed_share_pct"), term_value(points, "accepted_share_pct")
    deductions = term_value(points, "deductions_pct")
    metrics, checks = [], []

    def add(name, value, how):
        metrics.append({"metric": name, "value": value, "how": how})

    if si and prem:
        add("Premium rate", f"{_d(prem) / _d(si) * 100:.3f}%", "premium ÷ sum insured (100%)")
        add("Rate per mille", f"{_d(prem) / _d(si) * 1000:.2f} ‰", "premium ÷ sum insured × 1,000")
        add("Payback (years)", f"{_d(si) / _d(prem):,.0f}", "sum insured ÷ premium: years of premium to pay one total loss")
    if prem and deductions is not None:
        add("Premium after deductions", f"KES {_d(prem) * (1 - _d(deductions) / 100):,.2f}",
            f"premium × (1 − {deductions:g}%)")
    for pct_key, base_key, target_key, what in (
        ("placed_share_pct", "sum_insured_100", "placed_sum_insured", "placed sum insured"),
        ("placed_share_pct", "premium_100", "placed_premium", "placed premium"),
        ("accepted_share_pct", "sum_insured_100", "accepted_sum_insured", "accepted sum insured"),
        ("accepted_share_pct", "premium_100", "accepted_premium", "accepted premium"),
    ):
        pct, base, stated = term_value(points, pct_key), term_value(points, base_key), term_value(points, target_key)
        if pct is not None and base and stated is not None:
            expected = _d(base) * _d(pct) / 100
            ok = abs(expected - _d(stated)) <= max(Decimal(1), expected * Decimal("0.0005"))
            checks.append({"check": f"{pct:g}% × KES {base:,.2f} = {what}", "expected": f"KES {expected:,.2f}",
                           "stated": f"KES {stated:,.2f}", "ok": ok})
    debris = term_value(points, "debris_removal_pct")
    if debris and si:
        add("Debris removal could add", f"up to KES {_d(si) * _d(debris) / 100:,.0f}",
            f"{debris:g}% of the sum insured on top of the damage after a loss (not in the modelled damage)")
    if share and accepted:
        add("Accepted share of the placed share", f"{_d(accepted) / _d(share) * 100:.2f}%",
            f"{accepted:g}% ÷ {share:g}% (if the accepted share is of the 100% risk)")
    if report and si:
        run = report["runs"]["baseline"]
        src = run["insured"] if basis == "insured" and "insured" in run else run
        name = "gross loss" if src is not run else "ground-up loss"
        aal = _d(src["aal"]["aal_kes"])
        add(f"Modelled annual loss ({name})", f"KES {aal:,.0f}", "average annual loss from the model")
        add("Modelled loss cost", f"{aal / _d(si) * 1000:.2f} ‰", "modelled annual loss ÷ sum insured × 1,000")
        if prem:
            add("Modelled loss ratio", f"{aal / _d(prem):.0%}", "modelled annual loss ÷ premium (flood only; the premium covers all perils)")
        for p in src["ep_curve"]:
            if p["return_period_years"] in (100.0, 250.0):
                add(f"1-in-{p['return_period_years']:g} {name} ÷ sum insured", f"{_d(p['loss_kes']) / _d(si):.1%}",
                    "probable maximum loss as a share of the sum insured")
        if accepted:
            add("Accepting reinsurer's modelled annual loss", f"KES {aal * _d(accepted) / 100:,.0f}",
                f"{accepted:g}% of the modelled annual loss")
    return {"metrics": metrics, "checks": checks}


def analyse(text, response, properties, config):
    points = data_points(response, text)
    return {
        "data_points": points,
        "relevance": relevance(response, text),
        "cross_reference": cross_reference(properties, response, config),
        "flood_history": flood_history(response, text, properties),
        "implied": implied_metrics(points),
    }
