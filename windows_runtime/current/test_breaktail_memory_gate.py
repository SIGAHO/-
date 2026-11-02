import copy
import json
import tempfile
import unittest
from test_model_isolation import ModelIsolatedCase
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import breaktail_memory_gate as gate
import breaktail_memory_evidence as ev
import breaktail_raw_conversation as raw
import breaktail_v02 as tail


def accepting_model(messages, *args, **kwargs):
    request = json.loads(messages[-1]['content'])
    return {'message': {'content': json.dumps({'decisions': [
        dict(index=e['index'], usage=e.get('usage', 'historical' if e['memory']['memory_type'] in ('episode', 'state') else 'current'),
             reason='対象と用途が一致', **{k: 'pass' for k in request['checks']})
        for e in request['candidates']]}, ensure_ascii=False)}, 'done_reason': 'stop'}


def memory(**fields):
    m = dict(schema_version=2, id=1, content='ユーザーは星空観察が好き',
             memory_type='preference', status='unverified_interpretation',
             source_turn_ids=['s1'], recorded_at='2026-10-09T12:00:00+09:00',
             event_start=None, event_end=None, time_precision='unknown', time_text=None, confidence=.7)
    return dict(m, **fields)


class GateTests(ModelIsolatedCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.rows = [dict(turn_id='s1', conversation_id='c1', timestamp='2026-10-09T12:00:00+09:00',
                          user_text='星空観察が好き', assistant_text='そうなんだ', status='complete')]
        self.store = self.root/'raw.jsonl'
        self.store.write_text(json.dumps(self.rows[0], ensure_ascii=False)+'\n', encoding='utf-8')
        self.mem = self.root/'memory.jsonl'
        self.mem.write_text(json.dumps(memory(), ensure_ascii=False)+'\n', encoding='utf-8')
        for obj, key, value in [(raw, 'RAW_CONVERSATION_FILE', self.store),
                                (tail, 'MEMORY_FILE', self.mem), (tail, 'FULL_TRACE_FILE', self.root/'trace.jsonl'),
                                (tail, 'TURN_LOG_FILE', self.root/'log.jsonl')]:
            p = patch.object(obj, key, value); p.start(); self.addCleanup(p.stop)
        self.events = []

    def run_gate(self, memories=None, model=accepting_model):
        def emit(trace, event, **fields): self.events.append(copy.deepcopy(dict(event=event, **fields)))
        return gate.gate_memories(memories or [memory()], '星空観察の好みを覚えてる？', '', None,
                                  model, emit, now=datetime.fromisoformat('2026-10-10T17:00:00+09:00'))

    def changed_model(self, stage, **changes):
        def call(*args, **kwargs):
            result = accepting_model(*args, **kwargs)
            data = json.loads(result['message']['content'])
            if kwargs['call_kind'] == 'memory_gate_combined':
                data['decisions'][0].update(changes)
            result['message']['content'] = json.dumps(data)
            return result
        return call

    def test_accept_trace_and_exact_cached_source(self):
        with patch.object(raw, 'get_turn', wraps=raw.get_turn) as lookup:
            accepted, cached = self.run_gate()
            result = ev.build_memory_evidence(accepted, resolved_sources=cached)
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(result['raw_ids'], ['s1'])
        self.assertEqual(self.events[-1]['used_ids'], [1])
        self.assertEqual(self.events[-1]['decisions'][0]['admission'], 'use')
        self.assertIn('gate_usage', result['prompt'])

    def test_every_relevance_rejection_and_unknown_avoids_reply_evidence(self):
        for check in gate.RELEVANCE:
            for outcome in ('fail', 'unknown'):
                with self.subTest(check=check, outcome=outcome), patch.object(raw, 'get_turn', wraps=raw.get_turn) as lookup:
                    accepted, _ = self.run_gate(model=self.changed_model('admission', **{check:outcome}))
                    self.assertEqual(accepted, [])
                    lookup.assert_called_once_with('s1')
                    self.assertIn(check+':'+outcome, self.events[-1]['decisions'][0]['reasons'])

    def test_source_conflict_and_unsupported_generalization(self):
        for check in gate.SOURCE_CHECKS:
            with self.subTest(check=check), patch.object(raw, 'get_context') as context:
                accepted, _ = self.run_gate(model=self.changed_model('source', **{check:'fail'}))
                self.assertEqual(accepted, [])
                context.assert_not_called()
                self.assertEqual(self.events[-1]['decisions'][0]['admission'], 'ignore')

    def test_legacy_and_invalid_v2_never_read_raw_or_model(self):
        for m in ({'id': 3, 'content':'星空観察'}, memory(source_turn_ids=[])):
            with patch.object(raw, 'get_turn') as lookup:
                model = unittest.mock.Mock()
                self.assertEqual(self.run_gate([m], model)[0], [])
                lookup.assert_not_called(); model.assert_not_called()

    def test_episode_cannot_be_current_attribute_even_if_model_passes(self):
        accepted, _ = self.run_gate([memory(memory_type='episode', content='今日はいい日だった')],
                                    self.changed_model('admission', usage='current'))
        self.assertFalse(accepted)
        self.assertIn('episode_generalization', self.events[-1]['decisions'][0]['reasons'])

    def test_old_state_cannot_be_current_even_if_model_passes(self):
        accepted, _ = self.run_gate([memory(memory_type='state', content='今眠い')],
                                    self.changed_model('admission', usage='current'))
        self.assertFalse(accepted)
        self.assertIn('temporary_state_not_current_evidence', self.events[-1]['decisions'][0]['reasons'])
        self.assertEqual(self.events[-1]['decisions'][0]['staleness']['current_validity'], 'not_established')

    def test_historical_episode_and_state_remain_dated(self):
        for kind in ('episode', 'state'):
            accepted, cached = self.run_gate([memory(memory_type=kind)])
            result = ev.build_memory_evidence(accepted, resolved_sources=cached)
            self.assertEqual(accepted[0]['gate_usage'], 'historical')
            self.assertIn('2026-10-09', result['prompt'])

    def test_plan_current_time_policy(self):
        for date in (None, '2026-10-09', '2026-10-11', 'bad'):
            self.assertFalse(self.run_gate([memory(memory_type='plan', event_start=date)])[0])

    def test_missing_corrupt_error_and_partial_sources(self):
        for content in ('', '{broken'):
            self.store.write_text(content, encoding='utf-8')
            self.assertFalse(self.run_gate()[0])
        with patch.object(raw, 'get_turn', side_effect=OSError('test')):
            self.assertFalse(self.run_gate()[0])
        self.store.write_text(json.dumps(self.rows[0]), encoding='utf-8')
        self.assertFalse(self.run_gate([memory(source_turn_ids=['s1','absent'])])[0])

    def test_incomplete_source_is_ignored(self):
        self.store.write_text(json.dumps(dict(self.rows[0], status='incomplete')), encoding='utf-8')
        self.assertFalse(self.run_gate()[0])

    def test_model_errors_malformed_duplicate_or_wrong_indices_fail_closed(self):
        for content in ('bad', '{"decisions":[]}', '{"decisions":{}}'):
            model = lambda *a, **k: {'message':{'content':content}}
            self.assertFalse(self.run_gate(model=model)[0])
        for changes in ({'index': True}, {'index': 9}, {'reason': ''}, {'topic': 'yes'}):
            self.assertFalse(self.run_gate(model=self.changed_model('admission', **changes))[0])
        with patch.object(gate, 'judge_batch', side_effect=TimeoutError()):
            self.assertFalse(self.run_gate()[0])

    def test_source_model_error_and_scope_change_fail_closed(self):
        def failure(*a, **k):
            if k['call_kind'].endswith('combined'): raise TimeoutError()
            return accepting_model(*a, **k)
        self.assertFalse(self.run_gate(model=failure)[0])
        self.assertFalse(self.run_gate(model=self.changed_model('combined', source_scope='unknown'))[0])

    def test_batch_mixed_candidates_index_mapping_and_duplicate_indices(self):
        def mixed(*a, **k):
            response = accepting_model(*a, **k)
            data = json.loads(response['message']['content'])
            if k['call_kind'].endswith('combined'):
                data['decisions'][0]['topic'] = 'fail'
                data['decisions'].reverse()
            response['message']['content'] = json.dumps(data)
            return response
        candidates = [memory(id=1), memory(id=2)]
        with patch.object(raw, 'get_turn', wraps=raw.get_turn) as lookup:
            accepted, _ = self.run_gate(candidates, mixed)
        self.assertEqual([m['id'] for m in accepted], [2])
        self.assertEqual(lookup.call_count, 2)
        def duplicate(*a, **k):
            response = accepting_model(*a, **k)
            data = json.loads(response['message']['content'])
            data['decisions'][1]['index'] = data['decisions'][0]['index']
            response['message']['content'] = json.dumps(data)
            return response
        with patch.object(raw, 'get_turn', wraps=raw.get_turn) as lookup:
            self.assertFalse(self.run_gate(candidates, duplicate)[0])
            self.assertEqual(lookup.call_count, 2)

    def test_current_turn_and_scene_are_separate_from_stale_history(self):
        requests = []
        def capture(*a, **k):
            requests.append(json.loads(a[0][-1]['content']))
            return accepting_model(*a, **k)
        with patch.object(tail, 'call_ollama', side_effect=capture):
            tail.build_reply_messages([{'role':'user','content':'星空観察の昔話'}],
                                      '今は猫の話', {'name':'猫役'}, trace=tail.new_trace())
        self.assertEqual(requests[0]['current_turn'], '今は猫の話')
        self.assertEqual(requests[0]['recent_user_context'], '星空観察の昔話')
        self.assertEqual(requests[0]['scene'], {'name':'猫役'})

    def test_budget_exceeded_never_truncates_into_approval(self):
        with patch.object(gate, 'resolve_memory_sources', return_value=dict(memory_id=1, source_turn_ids=['s1'],
                          sources=[dict(self.rows[0], user_text='x'*20000)], unresolved=[])):
            self.assertFalse(self.run_gate()[0])

    def test_read_only_and_input_not_mutated(self):
        before = (self.store.read_bytes(), self.mem.read_bytes())
        original = memory(); snapshot = copy.deepcopy(original)
        accepted, cached = self.run_gate([original])
        ev.build_memory_evidence(accepted, resolved_sources=cached)
        self.assertEqual(original, snapshot)
        self.assertEqual(before, (self.store.read_bytes(), self.mem.read_bytes()))

    def test_shared_pipeline_trace_and_fail_open_conversation_fail_closed_memory(self):
        trace = tail.new_trace(channel='test')
        with patch.object(tail, 'call_ollama', side_effect=accepting_model):
            messages = tail.build_reply_messages([], '星空観察の好み', None, trace=trace)
        self.assertIn('[Source raw conversation]', messages[0]['content'])
        events = [json.loads(s) for s in tail.FULL_TRACE_FILE.read_text(encoding='utf-8').splitlines()]
        self.assertTrue({'memory_gate', 'memory_evidence'} <= {e['event'] for e in events})
        with patch.object(tail, 'gate_memories', side_effect=RuntimeError('fault')), \
             patch.object(tail, 'call_ollama', return_value={'message':{'content':'会話は続けられる'}, 'done_reason':'stop'}), \
             patch.object(raw, 'get_turn') as lookup:
            reply, complete = tail.generate_reply([], '星空観察', trace=trace)
            self.assertTrue(reply and complete); lookup.assert_not_called()
        events = [json.loads(s) for s in tail.FULL_TRACE_FILE.read_text(encoding='utf-8').splitlines()]
        self.assertFalse([e for e in events if e['event']=='memory_evidence'][-1]['prompt'])


if __name__ == '__main__': unittest.main()
