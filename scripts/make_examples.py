"""Rebuild public synthetic examples. Never reads market data or user history."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(name, value):
    target = ROOT / "examples" / name
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    metrics = []
    data = {
        2023: {"revenue": 1000, "net_income": 90, "ebitda": 220, "ebit": 170, "operating_cash_flow": 160, "capex": 90, "interest_expense": 40, "total_debt": 600, "cash": 100},
        2024: {"revenue": 1150, "net_income": 105, "ebitda": 245, "ebit": 190, "operating_cash_flow": None, "capex": 120, "interest_expense": 50, "total_debt": 650, "cash": 130},
        2025: {"revenue": 1300, "net_income": 110, "ebitda": 270, "ebit": 210, "operating_cash_flow": 200, "capex": 140, "interest_expense": 65, "total_debt": 700, "cash": 150},
    }
    for year, values in data.items():
        for name, value in values.items():
            instant = name in {"total_debt", "cash"}
            metrics.append({"name": name, "value": value, "period_start": f"{year}-12-31" if instant else f"{year}-01-01",
                            "period_end": f"{year}-12-31", "period_kind": "instant" if instant else "FY",
                            "standard": "IFRS", "entity_id": "synthetic-factory", "scope": "consolidated",
                            "unit": "currency", "currency": "RUB", "scale": 1000000,
                            "source_ids": ["synthetic"], "locator": f"Synthetic example: {year}/{name}",
                            "note": "Вымышленные учебные данные"})
    write("demo-analysis.json", {
        "schema_version": 1, "query": "Учебный пример: проанализируй вымышленную компанию",
        "entity": {"id": "synthetic-factory", "name": "Учебный завод (вымышленная компания)", "sector": "nonfinancial", "role": "group"},
        "asset_type": "issuer", "as_of": "2026-09-26", "status": "partial",
        "sources": [{"id": "synthetic", "title": "Синтетический набор для демонстрации", "location": "synthetic://moex-analyst/demo",
                     "retrieved_at": "2026-09-26T00:00:00Z", "period": "2023–2025"}],
        "metrics": metrics, "summary": "Демонстрация формата, расчётов и графиков. Эти числа не относятся к реальной компании.",
        "findings": [{"text": "В учебном наборе выручка растёт, но процентные расходы также увеличиваются.", "kind": "interpretation", "source_ids": ["synthetic"]}],
        "strengths": ["Положительный операционный денежный поток в представленных 2023 и 2025 годах."],
        "risks": ["Процентные расходы растут быстрее выручки в синтетическом наборе."],
        "gaps": ["Операционный денежный поток за 2024 год намеренно отсутствует для демонстрации разрыва."],
        "assumptions": ["Все сведения вымышлены; данный пример не является анализом ценной бумаги."],
        "conclusion": "Формат проверен на учебных данных. Для реального решения нужны документы эмитента и условия конкретного инструмента."
    })
    write("demo-bond.json", {"instrument": "SYNTHETIC-BOND", "settlement": "2026-01-01", "maturity": "2027-01-01",
                            "nominal": 1000, "clean_price_percent": 100, "accrued_interest": 0,
                            "cashflows_verified": True, "source": "synthetic://one-year-control-case",
                            "quote_as_of": "2026-01-01T00:00:00Z", "flows": [{"date": "2027-01-01", "coupon": 100, "principal": 1000}]})
    write("demo-equity.json", {"price": 100, "shares": 1000000, "net_income_to_common": 10000000,
                              "ebitda": 20000000, "net_debt": 5000000, "book_equity_to_common": 50000000,
                              "dividend_per_share": 5, "earnings_period": "FY 2025", "quote_as_of": "2026-01-01",
                              "source": "synthetic://equity-control-case"})
    print("Wrote 3 synthetic examples")


if __name__ == "__main__":
    main()
