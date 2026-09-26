from datetime import date
import json
from pathlib import Path
import unittest

from pydantic import ValidationError

from moex_analyst.finance import BondInput, CashFlow, EquityInput, bond_analytics, compare_bonds, equity_analytics, equity_scenarios, ValuationScenario

ROOT = Path(__file__).resolve().parents[1]


def bond(**updates):
    data = json.loads((ROOT / "examples/demo-bond.json").read_text())
    data.update(updates)
    return BondInput.model_validate(data)


class BondTests(unittest.TestCase):
    def test_one_year_par(self):
        r = bond_analytics(bond())
        self.assertAlmostEqual(r["annual_effective_yield_percent"], 10, places=8)
        self.assertAlmostEqual(r["macaulay_duration_years"], 1)
        self.assertAlmostEqual(r["modified_duration"], 1 / 1.1)

    def test_accrued_interest_increases_price_and_reduces_yield(self):
        r = bond_analytics(bond(accrued_interest=25))
        self.assertEqual(r["dirty_price"], 1025)
        self.assertAlmostEqual(r["annual_effective_yield_percent"], (1100 / 1025 - 1) * 100)

    def test_negative_yield(self):
        r = bond_analytics(bond(clean_price_percent=120))
        self.assertAlmostEqual(r["annual_effective_yield_percent"], (1100 / 1200 - 1) * 100)

    def test_amortization_with_known_zero_yield(self):
        b = bond(flows=[{"date": "2026-07-01", "coupon": 0, "principal": 500},
                        {"date": "2027-01-01", "coupon": 0, "principal": 500}])
        self.assertAlmostEqual(bond_analytics(b)["annual_effective_yield_percent"], 0, places=8)

    def test_cannot_silently_double_redeem(self):
        b = bond(flows=[{"date": "2026-07-01", "coupon": 50, "principal": 500},
                        {"date": "2027-01-01", "coupon": 25, "principal": 1000}])
        with self.assertRaises(ValueError):
            bond_analytics(b)

    def test_unverified_and_complex_cashflows_not_ytm(self):
        for updates in [{"cashflows_verified": False}, {"coupon_type": "floating"}, {"subordinated": True}, {"has_offer_or_call": True}, {"perpetual": True}]:
            with self.subTest(updates=updates):
                r = bond_analytics(bond(**updates))
                self.assertEqual(r["status"], "unsupported")
                self.assertNotIn("annual_effective_yield_percent", r)

    def test_explicit_floating_scenario(self):
        r = bond_analytics(bond(coupon_type="floating", mode="scenario", scenario_name="Stable rate",
                               assumptions=["Reference rate remains unchanged; full redemption"]))
        self.assertEqual(r["yield_label"], "scenario_irr")

    def test_invalid_cashflows_and_nan(self):
        for updates in [{"nominal": float("nan")}, {"flows": [{"date": "2026-01-01", "coupon": 5, "principal": 1000}]},
                        {"mode": "scenario"}, {"flows": [{"date": "2027-01-01", "coupon": -1, "principal": 1000}]}]:
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                bond(**updates)

    def test_comparison_requires_common_settlement(self):
        with self.assertRaises(ValueError):
            compare_bonds([bond(), bond(settlement="2026-01-02")])


class EquityTests(unittest.TestCase):
    def sample(self, **updates):
        data = json.loads((ROOT / "examples/demo-equity.json").read_text())
        data.update(updates)
        return EquityInput.model_validate(data)

    def test_multiples(self):
        r = equity_analytics(self.sample())
        self.assertEqual(r["pe"], 10)
        self.assertEqual(r["pb"], 2)
        self.assertEqual(r["ev_ebitda"], 5.25)
        self.assertEqual(r["dividend_yield_percent"], 5)

    def test_loss_and_financial_sectors(self):
        self.assertIsNone(equity_analytics(self.sample(net_income_to_common=-1))["pe"])
        self.assertIsNone(equity_analytics(self.sample(sector="bank"))["ev_ebitda"])

    def test_scenario(self):
        r = equity_scenarios(100, [ValuationScenario(name="base", eps=12, pe=10, dividend_per_share=5,
                                                    horizon_years=1, assumptions=["hypothetical earnings"])])[0]
        self.assertEqual(r["target_price"], 120)
        self.assertAlmostEqual(r["total_return_percent"], 25)
