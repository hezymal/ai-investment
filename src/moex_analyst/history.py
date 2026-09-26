"""One immutable directory per analysis; no shared cloud database."""
import json
import os
from pathlib import Path
import re
import uuid

from .charts import financial_charts
from .models import Analysis, metric_key, now
from .metrics import all_calculations
from .reporting import render_report


def local_root(workspace: str | Path = ".") -> Path:
    return Path(workspace).resolve() / ".local"


class History:
    def __init__(self, root: Path):
        self.root = root / "history"

    def save(self, a: Analysis, charts: bool = True) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        record_id = now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex
        temporary = self.root / (".pending-" + record_id)
        temporary.mkdir()
        chart_files = financial_charts(a, temporary / "charts") if charts else []
        (temporary / "analysis.json").write_text(a.model_dump_json(indent=2), encoding="utf-8")
        (temporary / "calculations.json").write_text(json.dumps(all_calculations(a), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        (temporary / "report.md").write_text(render_report(a, chart_files), encoding="utf-8")
        (temporary / "metadata.json").write_text(json.dumps({"id": record_id, "saved_at": now().isoformat()}), encoding="utf-8")
        target = self.root / record_id
        os.rename(temporary, target)
        return {"id": record_id, "report": str((target / "report.md").resolve()), "directory": str(target.resolve())}

    def path(self, record_id: str) -> Path:
        if not re.fullmatch(r"\d{8}T\d{6}-[a-f0-9]{32}", record_id):
            raise ValueError("invalid analysis id")
        return self.root / record_id

    def read(self, record_id: str) -> Analysis:
        return Analysis.model_validate_json((self.path(record_id) / "analysis.json").read_text(encoding="utf-8"))

    def list(self, query: str = "", limit: int = 50) -> dict:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        records, errors = [], []
        if self.root.exists():
            for p in sorted(self.root.iterdir(), reverse=True):
                if not p.is_dir() or p.name.startswith("."):
                    continue
                try:
                    a = self.read(p.name)
                    text = f"{a.entity.name} {a.entity.id} {a.entity.inn or ''} {a.instrument or ''} {a.query}".casefold()
                    if query.casefold() in text:
                        records.append({"id": p.name, "entity": a.entity.name, "entity_id": a.entity.id,
                                        "instrument": a.instrument, "as_of": a.as_of.isoformat(), "status": a.status,
                                        "report": str((p / 'report.md').resolve())})
                except (ValueError, OSError) as exc:
                    errors.append({"id": p.name, "error": str(exc)})
        return {"analyses": records[:limit], "errors": errors}

    def compare(self, older_id: str, newer_id: str) -> dict:
        older, newer = self.read(older_id), self.read(newer_id)
        if (older.entity.id, older.instrument, older.asset_type) != (newer.entity.id, newer.instrument, newer.asset_type):
            raise ValueError("compare requires the same entity and instrument")
        old = {metric_key(m): m for m in older.metrics}
        new = {metric_key(m): m for m in newer.metrics}
        changes = []
        for key in sorted(set(old) | set(new), key=str):
            om, nm = old.get(key), new.get(key)
            ov = om.value * om.scale if om and om.value is not None else None
            nv = nm.value * nm.scale if nm and nm.value is not None else None
            if om is not None and nm is not None and ov == nv:
                continue
            delta = None if ov is None or nv is None else nv - ov
            changes.append({"metric": key[0], "entity_id": key[1], "standard": key[2], "scope": key[3],
                            "period_start": key[5], "period_end": key[6], "old": ov, "new": nv, "delta": delta,
                            "change_percent": delta / ov * 100 if delta is not None and ov > 0 else None,
                            "kind": "added" if om is None else "removed" if nm is None else "revised"})
        return {"older": older_id, "newer": newer_id, "metric_changes": changes,
                "new_risks": [r for r in newer.risks if r not in older.risks],
                "resolved_gaps": [g for g in older.gaps if g not in newer.gaps],
                "old_conclusion": older.conclusion, "new_conclusion": newer.conclusion,
                "note": "Разные отчётные периоды показаны отдельно; пересмотр цифр за один период не равен росту бизнеса."}
