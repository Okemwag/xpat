import json
import sqlite3
from pathlib import Path
from ..core.errors import ModelError

class Repository:
    """SQLite local prototype persistence; JSON snapshots, parameterized SQL."""
    def __init__(self,path):
        self.path=str(path);Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS evidence (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    def connect(self): return sqlite3.connect(self.path,timeout=30)
    def save_analysis(self,result):
        with self.connect() as db:
            db.execute('INSERT INTO analyses VALUES (?,?)',(result['analysis_id'],json.dumps(result,allow_nan=False)))
    def get_analysis(self,identifier):
        with self.connect() as db:
            row=db.execute('SELECT payload FROM analyses WHERE id=?',(identifier,)).fetchone()
        if not row: raise ModelError('not_found','Analysis not found')
        return json.loads(row[0])
    def list_analyses(self,limit=50):
        with self.connect() as db:
            rows=db.execute('SELECT payload FROM analyses ORDER BY rowid DESC LIMIT ?',(min(200,max(1,limit)),)).fetchall()
        return [{'analysis_id':r['analysis_id'],'created_at':r['created_at'],'modelled_count':r['modelled_count']} for r in (json.loads(x[0]) for x in rows)]
    def add_evidence(self,evidence):
        try:
            with self.connect() as db: db.execute('INSERT INTO evidence VALUES (?,?)',(evidence.evidence_id,json.dumps(evidence.to_dict())))
        except sqlite3.IntegrityError: raise ModelError('duplicate_evidence','Evidence ID already exists') from None
    def list_evidence(self):
        from ..ai.evidence import Evidence
        with self.connect() as db: rows=db.execute('SELECT payload FROM evidence ORDER BY id').fetchall()
        return [Evidence(**json.loads(row[0])) for row in rows]
    def approve_evidence(self,identifier,reviewer):
        from dataclasses import replace
        with self.connect() as db:
            row=db.execute('SELECT payload FROM evidence WHERE id=?',(identifier,)).fetchone()
            if not row: raise ModelError('not_found','Evidence not found')
            from ..ai.evidence import Evidence
            item=replace(Evidence(**json.loads(row[0])),approved=True,reviewer=reviewer)
            db.execute('UPDATE evidence SET payload=? WHERE id=?',(json.dumps(item.to_dict()),identifier))
        return item
