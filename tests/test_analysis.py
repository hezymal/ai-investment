import copy
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from moex_analyst.history import History
from moex_analyst.metrics import calculate_metrics
from moex_analyst.models import Analysis

ROOT = Path(__file__).resolve().parents[1]


def sample():
    return json.loads((ROOT / "examples/demo-analysis.json").read_text(encoding="utf-8"))


class AnalysisTests(unittest.TestCase):
    def test_unknown_source_and_wrong_entity_rejected(self):
        for field in ["source_ids", "entity_id"]:
            data = sample()
            data["metrics"][0][field] = ["missing"] if field == "source_ids" else "missing"
            with self.subTest(field=field), self.assertRaises(ValidationError):
                Analysis.model_validate(data)

    def test_null_requires_partial(self):
        data = sample()
        data["status"] = "complete"
        data["gaps"] = []
        with self.assertRaises(ValidationError):
            Analysis.model_validate(data)

    def test_ratio_normalizes_scale(self):
        data = sample()
        for m in data["metrics"]:
            if m["name"] == "ebitda":
                m["value"] *= 1000
                m["scale"] = 1000
        calc = calculate_metrics(Analysis.model_validate(data))
        debt = next(r for r in calc if r["name"] == "net_debt_to_ebitda" and r["period_end"] == "2025-12-31")
        self.assertAlmostEqual(debt["value"], 550 / 270)

    def test_no_cross_standard_or_period_ratio(self):
        data = sample()
        for m in data["metrics"]:
            if m["name"] == "ebitda":
                m["standard"] = "management"
        calc = calculate_metrics(Analysis.model_validate(data))
        self.assertTrue(all(r["value"] is None for r in calc if r["name"] == "net_debt_to_ebitda"))

    def test_banks_do_not_get_industrial_ratios(self):
        data = sample()
        data["entity"]["sector"] = "bank"
        self.assertEqual(calculate_metrics(Analysis.model_validate(data)), [])

    def test_immutable_history_and_scope_aware_comparison(self):
        with tempfile.TemporaryDirectory() as d:
            h = History(Path(d))
            a = Analysis.model_validate(sample())
            first = h.save(a, False)
            initial = (Path(first["directory"]) / "analysis.json").read_bytes()
            data = sample()
            data["metrics"][0]["value"] += 100
            second = h.save(Analysis.model_validate(data), False)
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual((Path(first["directory"]) / "analysis.json").read_bytes(), initial)
            self.assertEqual(len(History(Path(d)).list()["analyses"]), 2)
            diff = h.compare(first["id"], second["id"])["metric_changes"]
            self.assertEqual(diff[0]["delta"], 100000000)
            self.assertEqual(diff[0]["kind"], "revised")
            self.assertIn("Синтетический", (Path(first["directory"]) / "report.md").read_text(encoding="utf-8"))
            with self.assertRaises(ValueError):
                h.read("../../outside")

    def test_same_number_different_scale_not_same_value(self):
        with tempfile.TemporaryDirectory() as d:
            h = History(Path(d))
            first = h.save(Analysis.model_validate(sample()), False)
            data = sample()
            data["metrics"][0]["scale"] /= 1000
            data["metrics"][0]["value"] *= 1000
            second = h.save(Analysis.model_validate(data), False)
            self.assertEqual(h.compare(first["id"], second["id"])["metric_changes"], [])

    def test_save_generates_charts(self):
        with tempfile.TemporaryDirectory() as d:
            saved = History(Path(d)).save(Analysis.model_validate(sample()))
            pngs = list((Path(saved["directory"]) / "charts").glob("*.png"))
            self.assertGreaterEqual(len(pngs), 5)
            self.assertTrue(all(p.read_bytes().startswith(b"\x89PNG") for p in pngs))
