"""Derive ratios only within comparable accounting perimeters."""
from .models import Analysis


def all_calculations(a: Analysis) -> dict:
    from .finance import BondInput, EquityInput, bond_analytics, equity_analytics
    return {"financial": calculate_metrics(a),
            "bond": bond_analytics(BondInput.model_validate(a.bond)) if a.bond else None,
            "equity": equity_analytics(EquityInput.model_validate(a.equity)) if a.equity else None}


def calculate_metrics(a: Analysis) -> list[dict]:
    results = []
    entities = {e.id: e for e in [a.entity, *a.related_entities]}
    groups = {}
    for m in a.metrics:
        if m.period_kind == "instant" or m.unit != "currency":
            continue
        key = (m.entity_id, m.standard, m.scope, m.currency, m.period_start, m.period_end, m.period_kind)
        groups.setdefault(key, {})[m.name] = m
    for key, flow in groups.items():
        entity, standard, scope, currency, start, end, period_kind = key
        stocks = {m.name: m for m in a.metrics if m.period_kind == "instant" and
                  (m.entity_id, m.standard, m.scope, m.currency, m.period_end, m.unit) ==
                  (entity, standard, scope, currency, end, "currency")}
        metrics = {**stocks, **flow}

        def add(name, names, formula, calc, unit="ratio", positive_denominator=None):
            inputs = [metrics.get(n) for n in names]
            missing = [n for n, m in zip(names, inputs) if m is None or m.value is None]
            values = {n: m.value * m.scale for n, m in zip(names, inputs) if m and m.value is not None}
            reason = "Нет данных: " + ", ".join(missing) if missing else None
            if not reason and positive_denominator and values[positive_denominator] <= 0:
                reason = "Знаменатель неположительный; коэффициент неприменим."
            value = None if reason else calc(values)
            results.append({"name": name, "value": value, "unit": unit, "currency": currency if unit == "currency" else None,
                            "entity_id": entity, "standard": standard, "scope": scope,
                            "period_start": start.isoformat(), "period_end": end.isoformat(),
                            "period_kind": period_kind, "formula": formula, "reason": reason,
                            "source_ids": sorted({s for m in inputs if m for s in m.source_ids})})

        if entities[entity].sector == "nonfinancial":
            add("net_margin", ["net_income", "revenue"], "net_income / revenue * 100",
                lambda v: v["net_income"] / v["revenue"] * 100, "percent", "revenue")
            add("free_cash_flow", ["operating_cash_flow", "capex"], "operating_cash_flow - capex (positive outflow)",
                lambda v: v["operating_cash_flow"] - v["capex"], "currency")
            add("net_debt", ["total_debt", "cash"], "total_debt - cash",
                lambda v: v["total_debt"] - v["cash"], "currency")
            if period_kind in {"FY", "TTM"}:
                add("net_debt_to_ebitda", ["total_debt", "cash", "ebitda"], "(total_debt - cash) / EBITDA",
                    lambda v: (v["total_debt"] - v["cash"]) / v["ebitda"], positive_denominator="ebitda")
            add("interest_coverage", ["ebit", "interest_expense"], "EBIT / interest_expense (positive expense)",
                lambda v: v["ebit"] / v["interest_expense"], positive_denominator="interest_expense")
    return results
