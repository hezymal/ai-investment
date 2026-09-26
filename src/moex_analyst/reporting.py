import json

from .metrics import all_calculations, calculate_metrics
from .models import Analysis


def cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_report(a: Analysis, chart_files: list[str] | None = None) -> str:
    lines = [f"# {a.entity.name}", "", f"**Дата анализа:** {a.as_of} · **Статус:** {a.status}",
             f"**Инструмент:** {a.instrument or 'эмитент'} · **Методика:** {a.methodology_version}", "",
             "## Запрос", "", a.query, "", "## Краткий вывод", "", a.summary, "",
             "## Исходные показатели", "",
             "| Показатель | Период | Периметр | Значение | Единицы | Источник |",
             "|---|---|---|---:|---|---|"]
    for m in a.metrics:
        v = "нет данных" if m.value is None else f"{m.value:g}"
        lines.append(f"| {cell(m.name)} | {m.period_start} — {m.period_end} ({m.period_kind}) | {cell(m.entity_id)} / {m.standard} / {m.scope} | {v} | ×{m.scale:g} {m.currency or ''} {m.unit} | {cell(', '.join(m.source_ids))}; {cell(m.locator)} |")
    lines += ["", "## Расчёты", "", "| Показатель | Период / периметр | Результат | Формула / ограничение |", "|---|---|---:|---|"]
    for r in calculate_metrics(a):
        v = "не определён" if r["value"] is None else f"{r['value']:,.3f} {r['unit']} {r['currency'] or ''}"
        lines.append(f"| {r['name']} | {r['period_end']} / {cell(r['entity_id'])} / {r['standard']} / {r['scope']} | {v} | {cell(r['formula'])}; {cell(r['reason'] or '')} |")
    instrument = all_calculations(a)
    for name in ["bond", "equity"]:
        if instrument[name] is not None:
            lines += ["", f"## Расчёт инструмента: {name}", "", "```json", json.dumps(instrument[name], ensure_ascii=False, indent=2), "```"]
    lines += ["", "## Факты и интерпретации", ""]
    lines += [f"- **{f.kind}:** {f.text} (источники: {', '.join(f.source_ids) or 'предположение'})" for f in a.findings] or ["Не указаны."]
    for title, items in [("Аргументы в пользу", a.strengths), ("Риски", a.risks), ("Недостающие сведения", a.gaps), ("Допущения", a.assumptions)]:
        lines += ["", f"## {title}", ""] + ([f"- {s}" for s in items] or ["Не указаны."])
    lines += ["", "## Итог", "", a.conclusion, "", "## Графики", ""]
    lines += [f"![Финансовая динамика](charts/{f})" for f in chart_files or []] or ["Нет графиков."]
    lines += ["", "## Источники", ""]
    for s in a.sources:
        lines.append(f"- **{s.id} — {s.title}**: {s.location}; получено {s.retrieved_at.isoformat()}; публикация {s.published_on or 'не установлена'}; период {s.period or 'не указан'}.")
    return "\n".join(lines) + "\n"
