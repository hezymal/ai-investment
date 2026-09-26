"""Manual/scheduler-invoked checks. New-document events remain pending until analysed."""
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager

from .documents import Documents
from .history import History
from .models import now


class Watchlist:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.db = root / "watchlist.sqlite3"
        self.root = root
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS watch (
                    issuer TEXT PRIMARY KEY, known TEXT, checked_at TEXT);
                CREATE TABLE IF NOT EXISTS event (
                    id INTEGER PRIMARY KEY, issuer TEXT NOT NULL, url TEXT NOT NULL,
                    title TEXT NOT NULL, detected_at TEXT NOT NULL, analysis_id TEXT,
                    UNIQUE(issuer, url));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, issuer: str, documents: Documents) -> dict:
        if len([e for e in documents.issuers() if e["id"] == issuer]) != 1:
            raise ValueError("issuer must be in the document registry")
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO watch(issuer) VALUES (?)", (issuer,))
        return {"issuer": issuer, "status": "watching", "note": "Первая успешная проверка установит исходный список документов."}

    def list(self) -> dict:
        with self.connect() as db:
            watched = [dict(r) for r in db.execute("SELECT issuer, checked_at FROM watch ORDER BY issuer")]
            pending = [dict(r) for r in db.execute("SELECT * FROM event WHERE analysis_id IS NULL ORDER BY id")]
        return {"issuers": watched, "pending": pending}

    def check(self, documents: Documents) -> dict:
        errors, initialized = [], []
        for entry in self.list()["issuers"]:
            issuer = entry["issuer"]
            result = documents.discover(issuer, refresh=True)
            if not result["complete"]:
                errors.append({"issuer": issuer, "errors": result["errors"], "note": "Неполный ответ: исходный список сохранён."})
                continue
            current = {d["url"]: d["title"] for d in result["documents"]}
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                stored = db.execute("SELECT known FROM watch WHERE issuer=?", (issuer,)).fetchone()[0]
                known = set(json.loads(stored)) if stored is not None else None
                if known is None:
                    initialized.append(issuer)
                else:
                    for url in sorted(set(current) - known):
                        db.execute("INSERT OR IGNORE INTO event(issuer,url,title,detected_at) VALUES(?,?,?,?)",
                                   (issuer, url, current[url], now().isoformat()))
                combined = sorted(set(current) | (known or set()))
                db.execute("UPDATE watch SET known=?,checked_at=? WHERE issuer=?", (json.dumps(combined), now().isoformat(), issuer))
        return {**self.list(), "initialized": initialized, "errors": errors,
                "note": "Проверяются новые ссылки, не изменение PDF по прежнему URL. Pending сохраняются до привязки нового анализа. Фоновый планировщик не установлен."}

    def acknowledge(self, event_id: int, analysis_id: str) -> dict:
        analysis = History(self.root).read(analysis_id)
        with self.connect() as db:
            event = db.execute("SELECT * FROM event WHERE id=?", (event_id,)).fetchone()
            if event is None:
                raise ValueError("event not found")
            if event["issuer"] != analysis.entity.id:
                raise ValueError("analysis must belong to the watched issuer")
            if event["url"] not in {s.location for s in analysis.sources}:
                raise ValueError("analysis must reference the newly discovered document")
            db.execute("UPDATE event SET analysis_id=? WHERE id=?", (analysis_id, event_id))
        return {"event_id": event_id, "analysis_id": analysis_id}
