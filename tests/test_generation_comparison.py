"""Experiment integrity checks; no model calls or quality/teacher labels."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('comparison', ROOT / 'scripts/generation_comparison.py')
comparison = importlib.util.module_from_spec(loader)
loader.loader.exec_module(comparison)


class ComparisonIntegrityTests(unittest.TestCase):
    def test_paired_conditions_keep_identical_history_and_nonpolicy_context(self):
        cases, _ = comparison.prepare()
        self.assertEqual(len(cases), 12)
        for case in cases:
            before = copy.deepcopy(case['A'])
            actual = comparison.variant_b(case['A'], case['spec'])
            self.assertEqual(case['A'], before)
            self.assertEqual(actual[1:], before[1:])
            a = comparison.json.loads(before[0]['content'].split('\nCPU_CONTEXT\n')[1])
            b = comparison.json.loads(actual[0]['content'].split('\nCPU_CONTEXT\n')[1])
            self.assertEqual(a.pop('response_spec'), case['spec'].to_dict())
            self.assertEqual(a, b)
            self.assertNotIn('454', str(actual))

    def test_short_directive_preserves_explicit_advice_permission(self):
        from companion_core.alignment import ResponseSpec
        instruction = comparison.short_instruction(ResponseSpec(act='advise', advice_allowed=True))
        self.assertIn('求められた助言', instruction)
        self.assertNotIn('質問・助言', instruction)
        self.assertIn('励まし', instruction)


if __name__ == '__main__':
    unittest.main()
