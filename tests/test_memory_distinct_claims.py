import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from companion_core.core import CompanionCore
from companion_core.memory import MemoryEngine
from companion_core.models import SourceType
from companion_core.textmath import cosine_text

class DistinctClaimsTests(unittest.TestCase):
    def test_similar_numeric_and_negated_claims_are_not_merged(self):
        m = MemoryEngine()
        entries = ['明日の集合場所は駅前の時計台で、集合時間は午前9時です。',
                   '明日の集合場所は駅前の時計台で、集合時間は午前8時です。',
                   '私は甘いものが好きです', '私は甘いものが好きではないです']
        self.assertGreater(cosine_text(entries[0], entries[1]), .92)
        for text in entries + entries[:1]:
            m.add(text, SourceType.USER_STATEMENT)
        self.assertEqual([x.text for x in m.items], entries)
        self.assertEqual(m.items[0].mentions, 2)
        self.assertEqual(m.items[1].mentions, 1)

    def test_replay_keeps_both_statements_without_inventing_correction(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'events.jsonl'
            core = CompanionCore(path)
            for value in ('明日の集合場所は駅前の時計台で、集合時間は午前9時です。',
                          '明日の集合場所は駅前の時計台で、集合時間は午前8時です。'):
                core.handle(value)
            before = [(m.text, m.mentions) for m in core.memory.items]
            self.assertEqual(len(before), 2)
            core.replay()
            self.assertEqual([(m.text, m.mentions) for m in core.memory.items], before)
            reopened = CompanionCore(path)
            self.assertEqual([(m.text, m.mentions) for m in reopened.memory.items], before)
            self.assertFalse(any(e.kind == 'correction' for e in reopened.events.events))
