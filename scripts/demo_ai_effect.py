"""Measure what the AI stages change in the model's output, for the submission report (problem statement §9 Step 5).

A. Free-text exposure ingestion (Gemini or Ollama): one held-out SYNTHETIC description from
   evaluation/ingestion_cases.json becomes validated property rows, which are then modelled. Without the AI there are
   no rows and no loss, so the whole result is the AI's contribution; the rows are shown for checking.
B. Flood reports -> drainage evidence (local embeddings, no text generation): three short DEMONSTRATION reports
   (SYNTHETIC, written for this script) about places that are NOT among the 24 named hotspots are read by the local
   pipeline; each place's drainage-deficit factor becomes an evidence item. Approval is SIMULATED here (reviewer
   "DEMONSTRATION (simulated)"); in the product a named reviewer must approve. The starter portfolio is then run with
   and without the evidence and the difference reported. Because the places are away from the hotspots and the reports
   are invented, the hotspot hit rate is not used as evidence of skill.

Writes outputs/ai_effect.json and outputs/ai_effect.md. Part A needs GEMINI_API_KEY (or OLLAMA_MODEL); run with --skip-llm
to refresh part B only (part A is then kept from the previous run).

Usage: uv run --extra geo --extra ai --extra embed python scripts/demo_ai_effect.py [--skip-llm]
"""

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from floodcat.core.constants import TIERS  # noqa: E402
from floodcat.services.runtime import Runtime  # noqa: E402

OUT = ROOT / "outputs"
CASE_ID = "three-groups"
REPORTS = [
    ("Demonstration report A (SYNTHETIC)",
     "Residents of Kaloleni said blocked drains along the estate roads overflowed after the overnight downpour, leaving "
     "water standing in ground-floor homes for two days. In Kabiria, culverts choked with garbage could not carry the "
     "runoff and the main access road flooded."),
    ("Demonstration report B (SYNTHETIC)",
     "Traders in Kaloleni blamed the county for drains that have not been cleared in years. Every heavy shower now floods "
     "the market lane because the water has nowhere to go."),
    ("Demonstration report C (SYNTHETIC)",
     "In Githogoro and Marurui, rainwater had nowhere to drain and ponded between the houses after the storm, residents said. "
     "Further downstream the river rose but stayed within its banks."),
]


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key and not key.startswith("#") and value.strip():
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def kes(v):
    v = Decimal(str(v))
    if abs(v) >= 10**9:
        return f"KES {v / 10**9:,.2f} bn"
    return f"KES {v / 10**6:,.1f} m" if abs(v) >= 10**6 else f"KES {v / 10**3:,.0f} k"


def figures(report, run="baseline"):
    r = report["runs"][run]
    return {
        "properties": report["modelled_count"],
        "tiv_kes": report["modelled_tiv_kes"],
        "loss_kes": {p["tier"]: p["loss_kes"] for p in r["ep_curve"]},
        "aal_kes": r["aal"]["aal_kes"],
        "insured_aal_kes": r["insured"]["aal"]["aal_kes"] if "insured" in r else None,
    }


def part_a(rt):
    from floodcat.ai.ingestion import ingest
    from floodcat.ai.llm import make_client

    case = next(c for c in json.loads((ROOT / "evaluation" / "ingestion_cases.json").read_text())["cases"] if c["id"] == CASE_ID)
    llm = make_client()
    result = ingest(case["text"], llm, rt.gazetteer(), rt.class_defaults, batch_id="DEMO")
    report = rt.run(result["rows"], declare_synthetic=True, source_label="AI-ingested demonstration")
    return {
        "description": case["text"],
        "model": result["model"],
        "prompt_version": result["prompt_version"],
        "groups": [{k: g.get(k) for k in ("location_name", "housing_class", "count", "tiv_kes_each", "source_quote",
                                         "quote_verified", "flags")} for g in result["groups"]],
        "loss_by_class_1_in_250": {c["id"]: c["loss_kes"] for c in report["runs"]["baseline"]["breakdowns"]["common"]["construction"]},
        "rows": len(result["rows"]),
        "expected": case["expected"],
        "result": figures(report),
        "without_ai": "No rows can be produced from the text without the AI stage, so there is no loss to compare.",
    }


def part_b(rt):
    from floodcat.ai import drainage
    from floodcat.ai.reports import ingest

    settings = rt.config.drainage_reports
    docs = []
    for i, (title, text) in enumerate(REPORTS):
        d = ingest({"title": title, "text": text, "url": "", "published": "", "source_kind": "upload"},
                   rt.embedder, rt.scorer(settings), rt.places, settings)
        docs.append({**d, "id": f"demo-{i}", "independent": True})
    places = drainage.place_factors(docs, settings)
    evidence = [replace(drainage.to_evidence(p), approved=True, reviewer="DEMONSTRATION (simulated)") for p in places]
    rows = rt.sample_rows()
    before = rt.run(rows)
    after = rt.run(rows, ai_adjustment=True, evidence=evidence)
    ai = after["ai_contribution"]
    return {
        "reports": [{"title": t, "text": x} for t, x in REPORTS],
        "passages": [{"report": d["title"], "text": c["text"], "drainage_similarity": c["drainage_similarity"],
                      "contrast_similarity": c["contrast_similarity"], "strength": c["strength"]}
                     for d in docs for c in d["chunks"]],
        "places": [{"place": p["place"], "factor": p["factor"], "reports": p["report_count"]} for p in places],
        "evidence_used": ai["applied_evidence_count"],
        "changed_properties": ai["changed_properties"],
        "before": figures(before),
        "after": figures(after, "enhanced"),
        "loss_delta_kes": ai.get("loss_delta_kes"),
        "aal_delta_kes": ai.get("aal_delta_kes"),
        "embedding_model": rt.embedder.name,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-llm", action="store_true")
    args = ap.parse_args()
    load_env()
    rt = Runtime()
    previous = json.loads((OUT / "ai_effect.json").read_text()) if (OUT / "ai_effect.json").exists() else {}
    a = previous.get("free_text_ingestion") if args.skip_llm else part_a(rt)
    b = part_b(rt)
    result = {"generated": date.today().isoformat(), "free_text_ingestion": a, "flood_reports": b}
    (OUT / "ai_effect.json").write_text(json.dumps(result, indent=2, default=str) + "\n")

    lines = [
        "# What the AI stages change — measured",
        "",
        f"Generated {result['generated']} by `scripts/demo_ai_effect.py`. Every input below is SYNTHETIC.",
        "",
    ]
    if a:
        lines += [
            "## A. Free-text exposure ingestion",
            "",
            f"Held-out description (`{CASE_ID}`): “{a['description']}”",
            "",
            f"Model {a['model']} ({a['prompt_version']}) produced {a['rows']} property rows:",
            "",
            "| Place | Class | Buildings | Value each | Quote found in the text |",
            "|---|---|---:|---:|---|",
        ]
        lines += [f"| {g['location_name']} | {g['housing_class']} | {g['count']} | "
                  f"{kes(g['tiv_kes_each']) if g.get('tiv_kes_each') not in (None, '—') else '—'} | {'yes' if g.get('quote_verified') else 'no'} |"
                  for g in a["groups"]]
        r = a["result"]
        lines += ["", f"Modelled: {r['properties']} properties, {kes(r['tiv_kes'])} insured; 1-in-100 loss {kes(r['loss_kes']['occasional'])}; "
                  f"1-in-250 loss {kes(r['loss_kes']['common'])}; AAL {kes(r['aal_kes'])}. {a['without_ai']}", "",
                  "1-in-250 loss by class: " + "; ".join(f"{k} {kes(v)}" for k, v in a["loss_by_class_1_in_250"].items()), ""]
    lines += [
        "## B. Flood reports → drainage evidence → hazard → loss",
        "",
        f"Three demonstration reports read locally ({b['embedding_model']}); approval simulated. Places found:",
        "",
        "| Place | Drainage-deficit factor | Reports |",
        "|---|---:|---:|",
    ] + [f"| {p['place']} | {p['factor']:.2f} | {p['reports']} |" for p in b["places"]] + [
        "",
        f"Starter portfolio, with vs without this evidence: {b['changed_properties']} properties had their hazard raised; "
        f"average annual loss {kes(b['before']['aal_kes'])} → {kes(b['after']['aal_kes'])} ({'+' if Decimal(b['aal_delta_kes']) >= 0 else ''}{kes(b['aal_delta_kes'])}).",
        "",
        "| Return period | Without evidence | With evidence |",
        "|---|---:|---:|",
    ] + [f"| 1-in-{rt.config.return_periods[t]:g} | {kes(b['before']['loss_kes'][t])} | {kes(b['after']['loss_kes'][t])} |" for t in TIERS] + [
        "",
        "A higher loss is not evidence of a better model. In the product nothing changes until a named reviewer approves.",
    ]
    (OUT / "ai_effect.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
