"""Score the local drainage-passage classifier on evaluation/drainage_passages.json (dev and held-out test splits).

The thresholds in configs/default.json (drainage_reports) were set on the dev split; the test split is reported as is
and never used to tune them. Passages are hand-written (SYNTHETIC), so this measures whether the scoring separates the
kinds of sentences we expect, not accuracy on real reports. Runs offline once the embedding model is downloaded.
Writes outputs/drainage_eval.json and outputs/drainage_eval.md.

Usage: uv run --extra embed python scripts/evaluate_drainage.py
"""

import json
from datetime import date
from pathlib import Path
from floodcat.ai.drainage import Scorer, evaluate
from floodcat.ai.embeddings import LocalEmbedder
from floodcat.core.config import load_config

ROOT = Path(__file__).resolve().parents[1]


def pct(x):
    return "—" if x is None else f"{x:.0%}"


def main():
    settings = load_config().drainage_reports
    passages = json.loads((ROOT / "evaluation" / "drainage_passages.json").read_text())["passages"]
    embedder = LocalEmbedder(settings["embedding_model"])
    scorer = Scorer(embedder, settings)
    results = {s: evaluate(passages, scorer, embedder, s) for s in ("dev", "test")}
    out = {"generated": date.today().isoformat(), "model": embedder.name,
           "thresholds": {k: settings[k] for k in ("min_similarity", "min_margin", "full_margin")}, "splits": results}
    (ROOT / "outputs" / "drainage_eval.json").write_text(json.dumps(out, indent=2) + "\n")
    lines = [
        "# Drainage-passage classifier — evaluation",
        "",
        f"Generated {out['generated']} by `scripts/evaluate_drainage.py`. Model `{embedder.name}` (local). Thresholds "
        f"(set on dev only): drainage similarity ≥ {settings['min_similarity']}, margin over the best contrast ≥ "
        f"{settings['min_margin']}.",
        "",
        "Passages are hand-written in the style of news and humanitarian reports (SYNTHETIC). This checks that the scoring "
        "separates drainage failure from river overflow and from flood news without a cause; it is not accuracy on real reports.",
        "",
        "| Split | Passages | Drainage passages | Precision | Recall | River passages wrongly flagged |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for s, r in results.items():
        lines.append(f"| {s}{' (held out)' if s == 'test' else ''} | {r['passages']} | {r['drainage_passages']} | "
                     f"{pct(r['precision'])} | {pct(r['recall'])} | {r['river_flagged']} |")
    lines += ["", "## Held-out errors", ""]
    for e in results["test"]["errors"]:
        kind = "missed drainage" if e["label"] == "drainage" else f"flagged {e['label']}"
        lines.append(f"- {kind} (similarity {e['drainage_similarity']:.2f}, margin {e['margin']:+.3f}): {e['text']}")
    (ROOT / "outputs" / "drainage_eval.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
