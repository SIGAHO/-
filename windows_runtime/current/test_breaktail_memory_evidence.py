import json
import tempfile
import unittest
from test_model_isolation import ModelIsolatedCase
from pathlib import Path
from unittest.mock import patch

import breaktail_memory_evidence as ev
import breaktail_raw_conversation as raw
import breaktail_v02 as tail


def memory(ids=None):
    return {'schema_version': 2, 'id': 75, 'content': 'ユーザーは星空観察が好き',
            'status': 'unverified_interpretation', 'source_turn_ids': ['a2'] if ids is None else ids,
            'memory_type': 'preference', 'recorded_at': '2026-10-10T12:00:00+09:00',
            'event_start': None, 'event_end': None, 'time_precision': 'unknown',
            'time_text': None, 'confidence': 0.7}


class EvidenceTests(ModelIsolatedCase):
    def setUp(self):
        # Evidence tests exercise Phase4, with deterministic Phase5 admission.
        from test_breaktail_memory_gate import accepting_model
        model = patch.object(tail, 'call_ollama', side_effect=accepting_model)
        model.start()
        self.addCleanup(model.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.raw = self.path / 'raw.jsonl'
        self.mem = self.path / 'memory.jsonl'
        self.rows = [dict(conversation_id=c, turn_id=f'{c}{n}',
                          timestamp=f'2026-10-10T12:0{n}:00+09:00',
                          user_text=f'{c}{n} 星空観察', assistant_text=f'応答{c}{n}', status='complete')
                     for n in range(5) for c in ('a', 'b')]
        self.raw.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in self.rows), encoding='utf-8')
        self.mem.write_text(json.dumps(memory(), ensure_ascii=False), encoding='utf-8')
        for obj, name, value in [(raw, 'RAW_CONVERSATION_FILE', self.raw),
                                 (tail, 'MEMORY_FILE', self.mem),
                                 (tail, 'FULL_TRACE_FILE', self.path / 'trace.jsonl'),
                                 (tail, 'TURN_LOG_FILE', self.path / 'turns.jsonl')]:
            p = patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_source(self):
        r = ev.resolve_memory_sources(memory())
        self.assertEqual(r['sources'], [self.rows[4]])
        self.assertEqual(r['unresolved'], [])

    def test_neighbors_and_boundary(self):
        result = ev.build_memory_evidence([memory()])
        self.assertEqual(set(result['raw_ids']), {'a1', 'a2', 'a3'})
        self.assertTrue(all(r['conversation_id'] == 'a' for r in result['injected_raw']))
        edge = ev.build_memory_evidence([memory(['a0'])])
        self.assertEqual(set(edge['raw_ids']), {'a0', 'a1'})

    def test_multiple_sources_union_and_multiple_memories(self):
        result = ev.build_memory_evidence([memory(['a1', 'a2', 'b2']), dict(memory(['a2']), id=76)])
        self.assertEqual(len(result['raw_ids']), len(set(result['raw_ids'])))
        self.assertEqual(set(result['raw_ids']), {'a0', 'a1', 'a2', 'a3', 'b1', 'b2', 'b3'})
        self.assertEqual(result['prompt'].count('"turn_id": "a2"'), 1)

    def test_absent(self):
        self.assertEqual(ev.resolve_memory_sources(memory(['absent']))['unresolved'][0]['reason'], 'source_not_found')

    def test_broken_ids(self):
        for ids in ('a2', [None], [{}], [''], ['../../file'], ['a'*129]):
            with self.subTest(ids=ids), patch.object(raw, 'get_turn') as lookup:
                result = ev.resolve_memory_sources(memory(ids))
                self.assertTrue(result['unresolved'])
                lookup.assert_not_called()

    def test_legacy_and_unlinked(self):
        for m in ({'id': 1, 'content': '星空観察', 'source_turn_ids': ['a2']}, memory([])):
            with patch.object(raw, 'get_turn') as lookup:
                result = ev.build_memory_evidence([m])
                self.assertFalse(result['raw_ids'])
                self.assertTrue(result['memories'][0]['unresolved'])
                lookup.assert_not_called()

    def test_missing_store_and_corrupt_raw(self):
        self.raw.unlink()
        self.assertFalse(ev.build_memory_evidence([memory()])['raw_ids'])
        self.raw.write_text('{broken', encoding='utf-8')
        r = ev.build_memory_evidence([memory()])
        self.assertIn('raw_lookup_error', r['memories'][0]['unresolved'][0]['reason'])

    def test_invalid_record_and_defensive_context_boundary(self):
        with patch.object(raw, 'get_turn', return_value={'turn_id': 'a2'}):
            self.assertEqual(ev.resolve_memory_sources(memory())['unresolved'][0]['reason'], 'invalid_raw_record')
        with patch.object(raw, 'get_context', return_value=[self.rows[1]]):
            r = ev.build_memory_evidence([memory()])
            self.assertEqual(r['raw_ids'], ['a2'])
            self.assertEqual(r['memories'][0]['unresolved'][0]['reason'], 'invalid_context_record')

    def test_hit_prompt_and_trace(self):
        trace = tail.new_trace(channel='test')
        messages = tail.build_reply_messages([], '星空観察について話そう', None, trace=trace)
        prompt = messages[0]['content']
        for label in ('[Saved memory candidate]', '[Source raw conversation]', '[Nearby raw context]'):
            self.assertIn(label, prompt)
        events = [json.loads(x) for x in tail.FULL_TRACE_FILE.read_text(encoding='utf-8').splitlines()]
        e = next(e for e in events if e['event'] == 'memory_evidence')
        self.assertIn(e['prompt'], prompt)
        self.assertEqual(e['memories'][0]['memory_id'], 75)
        self.assertEqual(e['memories'][0]['source_turn_ids'], ['a2'])
        self.assertEqual(len(e['injected_raw']), 3)

    def test_miss_no_lookup(self):
        with patch.object(raw, 'get_turn') as lookup, patch.object(raw, 'get_context') as context:
            tail.build_reply_messages([], 'xyzzy', None)
            lookup.assert_not_called()
            context.assert_not_called()

    def test_limits(self):
        result = ev.build_memory_evidence([memory(['a1', 'a2', 'b2'])] * 8,
                    {'max_memories': 1, 'max_sources': 1, 'max_raw_turns': 1, 'max_chars': 1200})
        self.assertLessEqual(len(result['prompt']), 1200)
        self.assertEqual(len(result['memories']), 1)
        self.assertEqual(len(result['raw_ids']), 1)
        self.assertIn('source_limit', str(result))
        for name, (_, ceiling) in ev.LIMITS.items():
            self.assertEqual(ev.evidence_limits({name: 999999})[name], ceiling)
        self.assertEqual(ev.evidence_limits({'before': 'bad'})['before'], 1)
        huge = dict(self.rows[4], user_text='x' * 20000)
        with patch.object(raw, 'get_turn', return_value=huge), patch.object(raw, 'get_context', return_value=[huge]):
            r = ev.build_memory_evidence([memory()])
            self.assertFalse(r['raw_ids'])
            self.assertLessEqual(len(r['prompt']), 6000)
            self.assertIn('max_chars', str(r['omitted']))

    def test_read_only(self):
        before = (self.raw.read_bytes(), self.mem.read_bytes())
        tail.build_reply_messages([], '星空観察', None)
        self.assertEqual(before, (self.raw.read_bytes(), self.mem.read_bytes()))

    def test_compatibility(self):
        self.assertEqual(tail.retrieve_relevant_memories('星空観察'), [memory()['content']])
        self.assertEqual(tail.retrieve_relevant_memories('星空観察', limit=0), [])

    def test_lookup_failure_reply_continues(self):
        response = {'message': {'content': '以前の記録の原文は取得できません。'}, 'done_reason': 'stop'}
        with patch.object(raw, 'get_turn', side_effect=OSError('test')), patch.object(tail, 'call_ollama', return_value=response):
            reply, complete = tail.generate_reply([], '星空観察')
        self.assertTrue(complete)
        self.assertTrue(reply)

    def test_prompt_source_mapping_and_exact_manifest(self):
        result = ev.build_memory_evidence([memory(['a1', 'a2']), dict(memory(['b2']), id=76)],
                                          {'max_raw_turns': 1})
        self.assertIn('"source_turn_ids": ["a1", "a2"]', result['prompt'])
        self.assertEqual(result['memories'][0]['injected_raw_ids'], ['a1'])
        self.assertEqual(result['memories'][1]['injected_raw_ids'], [])

    def test_summary_omission_has_no_orphan_raw(self):
        result = ev.build_memory_evidence([memory()], {'max_chars': len(ev.HEADER) + 1})
        self.assertFalse(result['raw_ids'])
        self.assertFalse(result['memories'][0]['summary_injected'])
        self.assertIn('summary_max_chars', str(result['omitted']))

    def test_context_failure_retains_source(self):
        with patch.object(raw, 'get_context', side_effect=OSError('test')):
            r = ev.build_memory_evidence([memory()])
        self.assertEqual(r['raw_ids'], ['a2'])
        self.assertIn('context_lookup_error', str(r['memories'][0]['unresolved']))


if __name__ == '__main__':
    unittest.main()
