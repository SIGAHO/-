"""Verify evidence integrity and the admission gate, not the engines' formulas."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import runner


class OracleTests(unittest.TestCase):
    def test_relative_direction_and_inclusive_range(self):
        data = {"states": [{"irritation": 0.0}, {"irritation": 0.04}]}
        self.assertTrue(runner.evaluate(data, {"path": "states.1.irritation", "op": "gt", "other": "states.0.irritation"})["passed"])
        self.assertTrue(runner.evaluate(data, {"path": "states.1.irritation", "op": "range", "value": [0, 0.04]})["passed"])
        self.assertFalse(runner.evaluate(data, {"path": "states.1.irritation", "op": "lt", "value": 0})["passed"])

    def test_missing_path_and_unknown_operator_are_errors(self):
        with self.assertRaises(KeyError):
            runner.evaluate({}, {"path": "missing", "op": "eq", "value": 1})
        with self.assertRaises(ValueError):
            runner.evaluate({"x": 1}, {"path": "x", "op": "typo", "value": 1})


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "experiments" / "state"
        self.directory.mkdir(parents=True)
        self.cases = [{"id": str(i), "reason": "A required invariant", "checks": [{"path": "value", "op": "eq", "value": True}], "critical": i == 0} for i in range(10)]

    def run_cases(self, cases=None, observation=None, write=True):
        path = self.directory / "cases.jsonl"
        path.write_text("\n".join(json.dumps(c) for c in (self.cases if cases is None else cases)), encoding="utf-8")
        def default_observe(suite, case):
            return {"value": True}
        with patch.object(runner, "ROOT", self.root), patch.object(runner, "provenance", return_value={}), patch.object(runner.subprocess, "check_output", return_value="fixture-sha\n"), patch.object(runner, "observe", side_effect=observation or default_observe):
            return runner.run_suite("state", write=write)

    def test_all_pass_persists_evidence_and_allows_adoption(self):
        report = self.run_cases()
        self.assertEqual(report["decision"], "PASS")
        self.assertTrue(report["adoption_allowed"])
        self.assertEqual(json.loads((self.directory / "results.json").read_text(encoding="utf-8")), report)
        self.assertTrue((self.directory / "DECISION.md").read_text(encoding="utf-8").startswith("# PASS"))

    def test_single_critical_failure_blocks_adoption_and_keeps_other_cases(self):
        report = self.run_cases(observation=lambda s, c: {"value": c["id"] != "0"})
        self.assertEqual(report["passed"], 9)
        self.assertEqual(report["decision"], "REVISE")
        self.assertFalse(report["adoption_allowed"])
        self.assertFalse(report["execution_errors"])
        self.assertEqual(report["cases"][0]["checks"][0]["actual"], False)

    def test_total_failure_rejects(self):
        report = self.run_cases(observation=lambda s, c: {"value": False})
        self.assertEqual(report["decision"], "REJECT")
        self.assertFalse(report["adoption_allowed"])

    def test_execution_error_does_not_abort_following_cases(self):
        def observation(suite, case):
            if case["id"] == "0":
                raise RuntimeError("engine unavailable")
            return {"value": True}
        report = self.run_cases(observation=observation)
        self.assertTrue(report["execution_errors"])
        self.assertFalse(report["adoption_allowed"])
        self.assertEqual(len(report["cases"]), 10)
        self.assertEqual(report["passed"], 9)
        self.assertIn("RuntimeError", report["cases"][0]["error"])

    def test_no_write_preserves_evidence(self):
        self.run_cases()
        before = {p.name: p.read_bytes() for p in self.directory.iterdir() if p.name != "cases.jsonl"}
        self.run_cases(observation=lambda s, c: {"value": False}, write=False)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir() if p.name != "cases.jsonl"})

    def test_missing_oracle_duplicate_ids_and_too_few_cases_rejected(self):
        invalid = [self.cases[:9], self.cases + [self.cases[0]], copy.deepcopy(self.cases)]
        invalid[-1][0]["checks"] = []
        for cases in invalid:
            with self.subTest(cases=len(cases)), self.assertRaises(ValueError):
                self.run_cases(cases)


class RealExperimentTests(unittest.TestCase):
    def test_real_suites_reproducible_isolated_and_do_not_modify_core(self):
        src = runner.ROOT / "src"
        before = {p: p.read_bytes() for p in src.rglob("*.py")}
        evidence = {p: p.read_bytes() for p in (runner.ROOT / "experiments").rglob("results.json")}
        for suite in runner.SUITES:
            with self.subTest(suite=suite):
                first = runner.run_suite(suite, write=False)
                second = runner.run_suite(suite, write=False)
                self.assertEqual(first, second)
                self.assertGreaterEqual(first["total"], 10)
                self.assertFalse(first["execution_errors"])
        self.assertEqual(before, {p: p.read_bytes() for p in src.rglob("*.py")})
        self.assertEqual(evidence, {p: p.read_bytes() for p in evidence})

    def test_all_and_individual_entrypoints_enforce_exit_status(self):
        for script, suites in [("experiments/run_all.py", runner.SUITES), ("experiments/emotion/run.py", ["emotion"])]:
            expected = 1 if any(not runner.run_suite(s, write=False)["adoption_allowed"] for s in suites) else 0
            result = subprocess.run([sys.executable, script, "--no-write"], cwd=runner.ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stderr)
            for suite in suites:
                self.assertIn(suite + ":", result.stdout)


if __name__ == "__main__":
    unittest.main()
