"""Cash-flow math. Yield is an annual effective ACT/365F IRR, before taxes/fees."""
from datetime import date
import math
from typing import Literal

from pydantic import Field, model_validator

from .models import Model


class CashFlow(Model):
    date: date
    coupon: float = Field(ge=0)
    principal: float = Field(default=0, ge=0)


class BondInput(Model):
    instrument: str
    settlement: date
    maturity: date | None = None
    nominal: float = Field(gt=0, description="Outstanding nominal on settlement date")
    clean_price_percent: float = Field(gt=0)
    accrued_interest: float = Field(ge=0)
    currency: Literal["RUB"] = "RUB"
    coupon_type: Literal["fixed", "floating", "variable", "zero"] = "fixed"
    subordinated: bool = False
    perpetual: bool = False
    has_offer_or_call: bool = False
    cashflows_verified: bool = False
    mode: Literal["contractual", "scenario"] = "contractual"
    scenario_name: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    source: str = Field(min_length=1)
    quote_as_of: str = Field(min_length=1)
    flows: list[CashFlow] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_flows(self):
        dates = [f.date for f in self.flows]
        if dates != sorted(dates) or len(set(dates)) != len(dates):
            raise ValueError("aggregate flows by date and sort them")
        if any(d <= self.settlement for d in dates):
            raise ValueError("only flows after settlement are allowed")
        if self.mode == "scenario" and (not self.scenario_name or not self.assumptions):
            raise ValueError("scenario requires a name and explicit assumptions")
        if not any(f.coupon + f.principal > 0 for f in self.flows):
            raise ValueError("positive future cash flows required")
        return self


def bond_analytics(b: BondInput) -> dict:
    dirty = b.nominal * b.clean_price_percent / 100 + b.accrued_interest
    warnings = []
    if not b.cashflows_verified:
        warnings.append("График выплат не подтверждён первичным документом.")
    complex_terms = b.coupon_type in {"floating", "variable"} or b.has_offer_or_call or b.perpetual or b.subordinated
    if complex_terms:
        warnings.append("Будущие выплаты зависят от условий выпуска; используйте явно заданный сценарий.")
    if b.mode == "contractual":
        if not b.cashflows_verified or complex_terms:
            return {"status": "unsupported", "dirty_price": dirty, "warnings": warnings,
                    "reason": "Достоверная доходность к погашению не определена; нужен проверенный график или сценарий."}
        if b.maturity is None or b.flows[-1].date != b.maturity:
            raise ValueError("final cash flow must match maturity")
        if not math.isclose(sum(f.principal for f in b.flows), b.nominal, rel_tol=1e-8, abs_tol=0.01):
            raise ValueError("principal repayments must equal outstanding nominal")
    times = [(f.date - b.settlement).days / 365.0 for f in b.flows]
    amounts = [f.coupon + f.principal for f in b.flows]
    # Solve in log(1 + yield), retaining well-defined negative yields above -100%.
    def pv(log_rate):
        return sum(a * math.exp(min(700, -log_rate * t)) for a, t in zip(amounts, times))
    lo, hi = -20.0, 20.0
    if pv(lo) < dirty or pv(hi) > dirty:
        raise ValueError("yield outside supported numeric range")
    for _ in range(180):
        mid = (lo + hi) / 2
        if pv(mid) > dirty:
            lo = mid
        else:
            hi = mid
    log_rate = (lo + hi) / 2
    rate = math.expm1(log_rate)
    present = [a * math.exp(-log_rate * t) for a, t in zip(amounts, times)]
    duration = sum(t * p for t, p in zip(times, present)) / dirty
    convexity = sum(p * t * (t + 1) for t, p in zip(times, present)) / dirty / (1 + rate) ** 2
    return {"status": "ok", "instrument": b.instrument, "mode": b.mode,
            "yield_label": "scenario_irr" if b.mode == "scenario" else "yield_to_maturity",
            "annual_effective_yield_percent": rate * 100, "dirty_price": dirty,
            "macaulay_duration_years": duration, "modified_duration": duration / (1 + rate),
            "convexity": convexity, "settlement": b.settlement.isoformat(),
            "quote_as_of": b.quote_as_of, "source": b.source,
            "convention": "ACT/365F; effective annual; before tax and fees; supplied payment dates",
            "assumptions": b.assumptions, "warnings": warnings}


def compare_bonds(bonds: list[BondInput]) -> dict:
    if len(bonds) < 2:
        raise ValueError("at least two issues are required")
    if len({b.settlement for b in bonds}) != 1:
        raise ValueError("comparison requires the same settlement date")
    results = [bond_analytics(b) for b in bonds]
    return {"issues": results, "note": "Доходность не является рейтингом надёжности. Сопоставьте дюрацию, ликвидность и кредитный риск; сценарные IRR не равны договорным YTM."}


class EquityInput(Model):
    price: float = Field(gt=0)
    shares: float = Field(gt=0)
    net_income_to_common: float | None = None
    ebitda: float | None = None
    net_debt: float | None = None
    minority_interest: float = Field(default=0, ge=0)
    preferred_equity: float = Field(default=0, ge=0)
    book_equity_to_common: float | None = None
    dividend_per_share: float | None = Field(default=None, ge=0)
    sector: Literal["nonfinancial", "bank", "insurance", "other_financial"] = "nonfinancial"
    currency: str = "RUB"
    earnings_period: str
    quote_as_of: str
    source: str = Field(min_length=1)


def equity_analytics(e: EquityInput) -> dict:
    cap = e.price * e.shares
    ev = None if e.net_debt is None else cap + e.net_debt + e.minority_interest + e.preferred_equity
    def positive_ratio(n, d):
        return n / d if n is not None and d is not None and d > 0 else None
    return {"market_cap": cap, "enterprise_value": ev if e.sector == "nonfinancial" else None,
            "pe": positive_ratio(cap, e.net_income_to_common),
            "pb": positive_ratio(cap, e.book_equity_to_common),
            "ev_ebitda": positive_ratio(ev, e.ebitda) if e.sector == "nonfinancial" else None,
            "dividend_yield_percent": None if e.dividend_per_share is None else e.dividend_per_share / e.price * 100,
            "currency": e.currency, "earnings_period": e.earnings_period, "quote_as_of": e.quote_as_of,
            "source": e.source, "note": "Денежные значения в единицах валюты, один периметр и период. null = неприменимо или нет данных; дивиденды не гарантированы."}


class ValuationScenario(Model):
    name: str
    eps: float = Field(gt=0)
    pe: float = Field(gt=0)
    dividend_per_share: float = Field(default=0, ge=0)
    horizon_years: float = Field(gt=0)
    assumptions: list[str] = Field(min_length=1)


def equity_scenarios(price: float, scenarios: list[ValuationScenario]) -> list[dict]:
    if not math.isfinite(price) or price <= 0:
        raise ValueError("positive finite price required")
    return [{"name": s.name, "target_price": s.eps * s.pe,
             "price_change_percent": (s.eps * s.pe / price - 1) * 100,
             "total_return_percent": ((s.eps * s.pe + s.dividend_per_share) / price - 1) * 100,
             "horizon_years": s.horizon_years, "assumptions": s.assumptions,
             "note": "Сценарий, не прогноз; дивиденд указан суммарно за горизонт."} for s in scenarios]
