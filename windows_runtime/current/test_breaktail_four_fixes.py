"""Phase7 final regression: 0/1 Gate, exact history IDs, reply evidence, subjects."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

import breaktail_v02 as tail
import breaktail_web as web
import breaktail_memory_gate as gate
import breaktail_memory_evidence as ev
import breaktail_raw_conversation as raw
import test_breaktail_memory_gate as fixtures
from test_breaktail_memory_gate import memory, accepting_model


class FourFixTests(unittest.TestCase):
    setUp = fixtures.GateTests.setUp
    run_gate = fixtures.GateTests.run_gate
    def test_history_only_skips_model_and_source_lookup(self):
        model=Mock()
        with patch.object(gate, 'resolve_memory_sources') as lookup:
            accepted,_=gate.gate_memories([memory()], '星空', '', None, model,
                lambda t,e,**k:self.events.append(k), current_history_turn_ids={'s1'})
        self.assertEqual(accepted,[])
        model.assert_not_called();lookup.assert_not_called()
        self.assertIn('redundant_with_history', self.events[-1]['decisions'][0]['reasons'])

    def test_mixed_sources_need_all_ids_in_history(self):
        second=dict(self.rows[0],turn_id='s2')
        self.store.write_text('\n'.join(json.dumps(r) for r in [self.rows[0],second]),encoding='utf-8')
        model=Mock(side_effect=accepting_model)
        accepted,cached=gate.gate_memories([memory(source_turn_ids=['s1','s2'])], '星空', '', None,
            model, lambda *a,**k:None, current_history_turn_ids={'s1'})
        self.assertEqual(len(accepted),1);self.assertEqual(model.call_count,1)
        request=json.loads(model.call_args.args[0][-1]['content'])
        self.assertEqual(set(request['checks']),set(gate.RELEVANCE+gate.SOURCE_CHECKS))
        self.assertNotIn('assistant_text', request['candidates'][0]['sources'][0])
        self.assertEqual(request['candidates'][0]['sources'][0]['user_text'], self.rows[0]['user_text'])
        evidence=ev.build_memory_evidence(accepted,resolved_sources=cached,current_history_turn_ids={'s1'})
        self.assertEqual(evidence['raw_ids'],['s2'])
        self.assertNotIn('assistant_text',evidence['prompt'])
        self.assertNotIn('そうなんだ',evidence['prompt'])
        self.assertEqual(cached[0]['sources'][0]['assistant_text'],'そうなんだ')

    def test_neighbor_history_omitted_and_gate_snapshot_untouched(self):
        self.store.write_text('\n'.join(json.dumps(r) for r in [self.rows[0],dict(self.rows[0],turn_id='neighbor')]),encoding='utf-8')
        accepted,cached=self.run_gate()
        before=copy.deepcopy(cached)
        evidence=ev.build_memory_evidence(accepted,resolved_sources=cached,current_history_turn_ids={'neighbor'})
        self.assertEqual(evidence['raw_ids'],['s1']);self.assertEqual(cached,before)
        self.assertNotIn('assistant_text',json.dumps(evidence['injected_raw']))

    def test_reply_history_ids_match_gate_and_not_sent_as_model_fields(self):
        history=[dict(role='user',content='星空観察が好き',turn_id='s1'),dict(role='assistant',content='そうなんだ',turn_id='s1')]
        with patch.object(tail,'call_ollama') as model:
            messages=tail.build_reply_messages(history,'星空の話',None,trace=tail.new_trace())
        model.assert_not_called()
        self.assertTrue(all(set(m)=={'role','content'} for m in messages))
        self.assertNotIn('[Source raw conversation]',messages[0]['content'])
        events=[json.loads(s) for s in tail.FULL_TRACE_FILE.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(next(e for e in events if e['event']=='memory_gate')['current_history_turn_ids'],['s1'])

    def test_dropped_history_is_eligible_for_old_memory(self):
        history=[dict(role='user',content='星空観察が好き',turn_id='s1')]
        history += [dict(role='user',content='短い話',turn_id='new'+str(i)) for i in range(32)]
        model=Mock(side_effect=accepting_model)
        with patch.object(tail,'call_ollama',model):
            messages=tail.build_reply_messages(history,'星空観察の好み',None,trace=tail.new_trace())
        self.assertEqual(model.call_count,1)
        self.assertIn('[Source raw conversation]',messages[0]['content'])

    def test_extraction_missing_unknown_other_rejected_explicit_zero_allowed(self):
        for classification in [None,'unknown','explicit_other','invalid','explicit_user','zero_subject_user']:
            data=dict(scene_change=None,memory='ユーザーは合理的な考え方をする',memory_evidence='俺は合理的')
            if classification is not None:data['subject_resolution']=classification
            result=dict(message=dict(content=json.dumps(data)),done_reason='stop')
            with self.subTest(classification=classification),patch.object(tail,'call_ollama',return_value=result):
                candidate,_=tail.extract_interpretation('俺は合理的',None,trace=tail.new_trace())
                self.assertEqual(bool(candidate),classification in ('explicit_user','zero_subject_user'))

    def test_evidence_budget_keeps_the_history_checked_by_gate(self):
        source=dict(self.rows[0],user_text='星空観察'*700)
        resolved=dict(memory_id=1,source_turn_ids=['s1'],sources=[source],unresolved=[])
        history=[dict(role='user',content='最近の話',turn_id='recent')]
        with patch.object(tail,'gate_memories',return_value=([memory(gate_usage='current')],[resolved])) as model_gate:
            messages=tail.build_reply_messages(history,'星空観察の好み',None,trace=tail.new_trace())
        model_gate.assert_called_once()
        self.assertEqual(model_gate.call_args.kwargs['current_history_turn_ids'],{'recent'})
        self.assertEqual(messages[1],{'role':'user','content':'最近の話'})
        self.assertNotIn('[Saved memory candidate]',messages[0]['content'])
        events=[json.loads(s) for s in tail.FULL_TRACE_FILE.read_text(encoding='utf-8').splitlines()]
        evidence=next(e for e in events if e['event']=='memory_evidence')
        self.assertEqual(evidence['raw_ids'],[])
        self.assertEqual(evidence['omitted'][0]['reason'],'reply_context_budget')

    def test_restore_preserves_only_available_turn_ids(self):
        state=copy.deepcopy(web.STATE)
        try:
            web.restore_snapshot(dict(messages=[dict(role='user',text='星空',turn_id='s1'),dict(role='assistant',text='うん')],scene=None,pending=None))
            self.assertEqual(web.STATE['history'][0]['turn_id'],'s1')
            self.assertNotIn('turn_id',web.STATE['history'][1])
        finally:
            web.STATE.clear();web.STATE.update(state)


