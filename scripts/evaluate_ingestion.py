"""Score AI free-text ingestion on the held-out cases in evaluation/ingestion_cases.json.

Usage: uv run --extra ai --extra geo python scripts/evaluate_ingestion.py
Needs GEMINI_API_KEY (environment or .env). Calls Gemini once per case and Nominatim for places.
Writes outputs/ingestion_eval.json and outputs/ingestion_eval.md.
"""
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path
from floodcat.ai.llm import make_client
from floodcat.ai.geocode import Gazetteer
from floodcat.ai.ingestion import PROMPT_VERSION, ingest
from floodcat.ai.ingestion_eval import score_case, summarise
from floodcat.core.errors import ModelError
from floodcat.services.runtime import Runtime

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT/'evaluation'/'ingestion_cases.json'
OUT = ROOT/'outputs'

def load_env():
    env = ROOT/'.env'
    if env.exists():
        for line in env.read_text().splitlines():
            key, sep, value = line.strip().partition('=')
            if sep and key and not key.startswith('#') and value.strip():
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))

def pct(part):
    return '—' if part['rate'] is None else f"{part['correct']}/{part['total']} ({part['rate']:.0%})"

def main():
    load_env()
    suite = json.loads(CASES.read_text())
    runtime = Runtime()
    llm = make_client()
    gazetteer = Gazetteer(runtime.store_dir/'geocode_cache.json', llm=llm)
    scores, details, models = [], [], Counter()
    for case in suite['cases']:
        try:
            result = ingest(case['text'], llm, gazetteer, runtime.class_defaults, batch_id='EVAL')
            models[result['model']] += 1
            score = score_case(case, result)
            details.append({'id': case['id'], 'model': result['model'], 'groups': result['groups'], 'score': score})
        except ModelError as exc:
            score = {'id': case['id'], 'fields': {k: [False]*len(case['expected']) for k in ('found',)} | {k: [] for k in ('housing_class', 'count', 'tiv_kes_each', 'located', 'quote_verified')},
                     'extra_groups': 0, 'expected_buildings': sum(e['count'] for e in case['expected']), 'predicted_buildings': 0, 'exact': False, 'error': str(exc)}
            details.append({'id': case['id'], 'error': str(exc), 'score': score})
        scores.append(score)
        print(f"{case['id']:20} {'OK ' if score['exact'] else 'MISS'} {score.get('error', '')}")
    summary = summarise(scores)
    record = {'generated': date.today().isoformat(), 'cases_file': CASES.name, 'cases_version': suite['version'],
              'prompt_version': PROMPT_VERSION, 'models': dict(models), 'summary': summary, 'details': details}
    OUT.mkdir(exist_ok=True)
    (OUT/'ingestion_eval.json').write_text(json.dumps(record, indent=1)+'\n')
    rows = '\n'.join(f"| {d['id']} | {'yes' if d['score']['exact'] else 'no'} | {d['score']['predicted_buildings']}/{d['score']['expected_buildings']} | "
                     f"{d.get('error') or ', '.join(k for k, v in d['score']['fields'].items() if not all(v)) or '—'} |" for d in details)
    md = f"""# AI ingestion accuracy

Generated {record['generated']} by `scripts/evaluate_ingestion.py` · prompt `{PROMPT_VERSION}` · cases `{suite['version']}` ·
models used: {', '.join(f'{m} ({n})' for m, n in models.items()) or 'none'}.

> {len(suite['cases'])} held-out, team-written SYNTHETIC descriptions (`evaluation/ingestion_cases.json`), never shown to the model
> as examples. A small check of extraction, not a statistical accuracy estimate.

| Measure | Result |
|---|---|
| Cases fully correct | {summary['cases_fully_correct']}/{summary['cases']} |
| Groups found | {pct(summary['groups_found'])} |
| Housing class (incl. correctly flagged as unknown) | {pct(summary['housing_class'])} |
| Building count | {pct(summary['count'])} |
| Value per building (within 2%) | {pct(summary['tiv_kes_each'])} |
| Place located | {pct(summary['located'])} |
| Quote found in the text | {pct(summary['quote_verified'])} |
| Spurious extra groups | {summary['extra_groups']} |
| Total buildings exact | {summary['building_count_exact']}/{summary['cases']} |

| Case | Fully correct | Buildings (got/expected) | Fields wrong |
|---|---|---|---|
{rows}

Every AI record is still shown for human review before it is modelled; these figures describe the first draft.
"""
    (OUT/'ingestion_eval.md').write_text(md)
    print(json.dumps(summary, indent=1))

if __name__ == '__main__':
    main()
