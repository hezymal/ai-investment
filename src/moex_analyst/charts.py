"""Non-interactive, exportable plots; missing data stays missing."""
import os
from collections import defaultdict
from pathlib import Path

from .models import Analysis

LABELS = {"revenue": "Выручка", "net_income": "Чистая прибыль", "operating_cash_flow": "Операционный денежный поток",
          "total_debt": "Долг", "cash": "Денежные средства", "ebitda": "EBITDA", "capex": "Капитальные затраты"}


def pyplot(output: Path):
    os.environ.setdefault("MPLCONFIGDIR", str(output.resolve().parent / ".matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def financial_charts(a: Analysis, output: Path) -> list[str]:
    output.mkdir(parents=True, exist_ok=True)
    plt = pyplot(output)
    groups = defaultdict(dict)
    periods = defaultdict(set)
    for m in a.metrics:
        if m.name not in LABELS or m.unit != "currency":
            continue
        context = (m.entity_id, m.standard, m.scope, m.currency, m.period_kind)
        periods[context].add((m.period_start, m.period_end))
        groups[(*context, m.name)][(m.period_start, m.period_end)] = m
    files = []
    for i, (key, series) in enumerate(sorted(groups.items())):
        context, name = key[:-1], key[-1]
        calendar = sorted(periods[context])
        # Insert absent annual points, even if every metric for that year is missing.
        if context[-1] == "FY" and len(calendar) > 1 and all(s.month == 1 and s.day == 1 and e.month == 12 and e.day == 31 for s, e in calendar):
            from datetime import date
            calendar = [(date(y, 1, 1), date(y, 12, 31)) for y in range(calendar[0][0].year, calendar[-1][0].year + 1)]
        values = [float("nan") if p not in series or series[p].value is None else series[p].value * series[p].scale / 1e6 for p in calendar]
        fig, ax = plt.subplots(figsize=(10, 5.8), layout="constrained")
        fig.patch.set_facecolor("#f7f9fc")
        ax.plot(range(len(calendar)), values, marker="o", color="#176B87", linewidth=2.4)
        labels = [str(p[1].year) if context[-1] == "FY" else p[1].isoformat() for p in calendar]
        ax.set_xticks(range(len(calendar)), labels, rotation=30 if len(calendar) > 6 else 0)
        ax.set_title(f"{LABELS[name]} | {a.entity.name}\n{context[0]} · {context[1]} · {context[2]} · {context[-1]}", loc="left", fontsize=12)
        ax.set_ylabel(f"млн {context[3]}")
        ax.grid(axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        source_ids = sorted({s for m in series.values() for s in m.source_ids})
        fig.supxlabel(f"Источники: {', '.join(source_ids)}. Срез: {a.as_of}. Пропуски не заполнены.", fontsize=9)
        filename = f"metric-{i:02d}-{name}.png"
        fig.savefig(output / filename, dpi=150)
        plt.close(fig)
        files.append(filename)
    return files


def market_chart(candles: list[dict], instrument: str, source: str, output: Path) -> str:
    output.mkdir(parents=True, exist_ok=True)
    plt = pyplot(output)
    if not candles:
        raise ValueError("no candles to plot")
    rows = sorted(candles, key=lambda r: r["begin"])
    from datetime import datetime
    dates = [datetime.fromisoformat(r["begin"]) for r in rows]
    fig, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 7), layout="constrained")
    axes[0].plot(dates, [r.get("close") if r.get("close") is not None else float("nan") for r in rows], color="#176B87")
    axes[0].set_title(instrument, loc="left")
    axes[0].set_ylabel("Цена в единицах источника")
    axes[1].bar(dates, [r.get("volume") if r.get("volume") is not None else float("nan") for r in rows], color="#64A6A0")
    axes[1].set_ylabel("Объём, единицы ISS")
    fig.supxlabel(f"Источник: {source}", fontsize=8)
    path = output / "market.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return str(path.resolve())
