"""File-backed store used when no PostgreSQL URL is configured. Same interface as Repository.

Writes are atomic (temp file + rename) and serialised with a process lock, which is enough
for a single Streamlit/uvicorn process. Not for multi-process deployments.
"""
import json
import re
import threading
from dataclasses import replace
from pathlib import Path
from ..core.errors import ModelError

_LOCK = threading.RLock()
_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,100}$')

def _safe_id(identifier):
    if not isinstance(identifier, str) or not _ID.match(identifier):
        raise ModelError('not_found', 'Unknown identifier')
    return identifier

class LocalStore:
    def __init__(self, root='runtime/store'):
        self.root = Path(root)
        for sub in ('runs',):
            (self.root/sub).mkdir(parents=True, exist_ok=True)

    def _read(self, name, default):
        path = self.root/name
        if not path.exists(): return default
        try: return json.loads(path.read_text())
        except json.JSONDecodeError: raise ModelError('store_corrupt', f'{name} is unreadable; restore it or delete it to reset') from None

    def _write(self, name, value):
        path = self.root/name
        tmp = path.with_suffix(path.suffix+'.tmp')
        tmp.write_text(json.dumps(value, indent=1, allow_nan=False, default=str))
        tmp.replace(path)

    # Analyses
    def save_analysis(self, result, owner=None, label=None):
        with _LOCK:
            identifier = _safe_id(result['analysis_id'])
            self._write(f'runs/{identifier}.json', result)
            index = self._read('runs.json', [])
            baseline = result['runs']['baseline']
            index.insert(0, {'analysis_id': identifier, 'created_at': result['created_at'], 'owner': owner,
                             'label': label or 'Portfolio run', 'modelled_count': result['modelled_count'],
                             'modelled_tiv_kes': result['modelled_tiv_kes'], 'aal_kes': baseline['aal']['aal_kes'],
                             'ai_enabled': result['ai_contribution']['enabled']})
            self._write('runs.json', index[:500])

    def get_analysis(self, identifier):
        path = self.root/'runs'/f'{_safe_id(identifier)}.json'
        if not path.exists(): raise ModelError('not_found', 'Analysis not found')
        return json.loads(path.read_text())

    def list_analyses(self, owner=None, limit=50):
        return [r for r in self._read('runs.json', []) if owner is None or r.get('owner') == owner][:limit]

    def delete_analysis(self, identifier, owner):
        with _LOCK:
            index = self._read('runs.json', [])
            entry = next((r for r in index if r['analysis_id'] == identifier), None)
            if entry is None or entry.get('owner') != owner: raise ModelError('not_found', 'Analysis not found')
            self._write('runs.json', [r for r in index if r['analysis_id'] != identifier])
            (self.root/'runs'/f'{_safe_id(identifier)}.json').unlink(missing_ok=True)

    # Evidence
    def _evidence(self):
        from ..ai.evidence import Evidence
        return [Evidence(**e) for e in self._read('evidence.json', [])]

    def add_evidence(self, evidence):
        with _LOCK:
            items = self._read('evidence.json', [])
            if any(e['evidence_id'] == evidence.evidence_id for e in items):
                raise ModelError('duplicate_evidence', 'This passage is already in the evidence library')
            items.append(evidence.to_dict()); self._write('evidence.json', items)

    def list_evidence(self):
        return self._evidence()

    def update_evidence(self, identifier, **changes):
        with _LOCK:
            items = self._evidence()
            item = next((e for e in items if e.evidence_id == identifier), None)
            if item is None: raise ModelError('not_found', 'Evidence not found')
            updated = replace(item, **changes)
            self._write('evidence.json', [updated.to_dict() if e.evidence_id == identifier else e.to_dict() for e in items])
            return updated

    def approve_evidence(self, identifier, reviewer):
        return self.update_evidence(identifier, approved=True, reviewer=reviewer)

    def delete_evidence(self, identifier):
        with _LOCK:
            items = self._read('evidence.json', [])
            if not any(e['evidence_id'] == identifier for e in items): raise ModelError('not_found', 'Evidence not found')
            self._write('evidence.json', [e for e in items if e['evidence_id'] != identifier])

    # Users (see services.accounts for hashing and rules)
    def get_users(self):
        return self._read('users.json', {})

    def put_user(self, username, record):
        with _LOCK:
            users = self.get_users(); users[username] = record; self._write('users.json', users)
