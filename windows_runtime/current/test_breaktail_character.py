import json
import unittest
from unittest.mock import patch
import breaktail_v02 as tail
from breaktail_character import select,selected,prompt,examples,turn_instruction,transient_smalltalk
from breaktail_reply_contract import build_contract,normalize_voice,violations


class CharacterTests(unittest.TestCase):
    def test_transient_turns_do_not_hide_facts_or_roleplay_changes(self):
        state=tail.new_working_state();select(state,'atashi')
        for text in ('元気かい？','どう見る？','ありがとう！'):
            self.assertTrue(transient_smalltalk(state,text))
        for text in ('元気だ。覚えておいて。','訂正。果肉なしが好き。','元気だけど今日は休み。','元気かい？ロールプレイを始めて。'):
            self.assertFalse(transient_smalltalk(state,text))
        self.assertFalse(transient_smalltalk(state,'元気かい？',{'active':True}))
        self.assertFalse(transient_smalltalk(tail.new_working_state(),'元気かい？'))

    def test_elliptical_question_uses_actual_last_assistant_question(self):
        state=tail.new_working_state();select(state,'atashi')
        history=[{'role':'user','content':'元気？'},{'role':'assistant','content':'元気だよ。お前は？'}]
        self.assertIn('問い返し',turn_instruction(state,'どう見る？',history))
        self.assertEqual(turn_instruction(state,'このコードどう見る？',history),'')
        self.assertEqual(turn_instruction(state,'どう見る？',[]),'')

    def test_short_persona_reply_avoids_redundant_review_but_advice_does_not(self):
        state=tail.new_working_state();select(state,'atashi')
        model=lambda *a,**k:{'message':{'content':'元気だよ。お前は？'},'done_reason':'stop'}
        with patch.object(tail,'call_ollama',side_effect=model) as calls,patch.object(tail,'log_turn'):
            reply,complete=tail.generate_reply([],'元気かい？',working_state=state)
        self.assertTrue(complete)
        self.assertEqual(calls.call_count,1)
        self.assertIn('元気',reply)
        with patch.object(tail,'call_ollama',return_value={'message':{'content':'パンを温め直すと美味しく食べられるよ。'},'done_reason':'stop'}),patch.object(tail,'review_pragmatics',return_value={'applied':True,'hits':[]}) as review,patch.object(tail,'log_turn'):
            tail.generate_reply([],'今日の話を聞いて。',working_state=state)
        self.assertTrue(review.called)

    def test_explicit_selection_is_session_local_and_reversible(self):
        state=tail.new_working_state()
        select(state,'atashi')
        restored=json.loads(json.dumps(state))
        self.assertTrue(selected(restored))
        self.assertFalse(selected(tail.new_working_state()))
        select(restored,'off')
        self.assertFalse(selected(restored))
        with self.assertRaises(ValueError):select(state,'invented')

    def test_persona_does_not_enable_roleplay_or_invent_capabilities(self):
        state=tail.new_working_state();select(state,'atashi')
        self.assertFalse(state['mode']['active'])
        self.assertIn('現実の交友を禁じ',prompt(state))
        self.assertEqual(len(examples(state)),12)
        state['mode']['active']=True
        self.assertFalse(selected(state))

    def test_persona_voice_and_user_override(self):
        state=tail.new_working_state();select(state,'atashi')
        contract=build_contract(state,'今日の話を聞いて。')
        self.assertEqual(contract['first_person'],'あたし')
        self.assertIn('あたしは',normalize_voice('私はそう思う。',contract))
        self.assertTrue(contract['no_advice'])
        self.assertFalse(build_contract(state,'他のAIとも話したよ。')['no_advice'])
        self.assertTrue(build_contract(state,'助言はいらない。')['no_advice'])
        self.assertNotIn('mixed_character_voice',violations('比べようぜ。',contract))
        state['conversation']['preferences']['first_person']='私'
        self.assertEqual(build_contract(state,'説明して。')['first_person'],'私')

    def test_prompt_uses_existing_style_as_examples_not_history(self):
        state=tail.new_working_state();select(state,'atashi')
        with patch.object(tail,'trace_event'):
            messages=tail.build_reply_messages([],'今日の話を聞いて。',None,working_state=state)
        self.assertIn('選択された会話人格',messages[0]['content'])
        self.assertIn('実際の過去の会話や記憶ではない',messages[0]['content'])
        self.assertEqual(messages[-1]['content'],'今日の話を聞いて。')
        self.assertEqual(state['conversation']['facts'],{})

    def test_explicit_name_is_not_given_new_honorifics(self):
        state=tail.new_working_state();select(state,'atashi')
        tail.update_working_state(state,'俺の呼び名はユキ。')
        contract=build_contract(state,'戻ったよ。')
        self.assertIn('unrequested_honorific_on_explicit_name',violations('ユキさん、おかえり。',contract))
        self.assertNotIn('unrequested_honorific_on_explicit_name',violations('ユキ、おかえり。',contract))

    def test_arrival_does_not_get_departure_greeting(self):
        state=tail.new_working_state();select(state,'atashi')
        contract=build_contract(state,'帰ったよ。')
        self.assertIn('greeting_direction_conflict',violations('帰ってらっしゃい。',contract))
        self.assertNotIn('greeting_direction_conflict',violations('おかえり。',contract))

    def test_sensory_anecdote_is_not_a_sensor_question(self):
        self.assertFalse(tail._needs_self_context('夕方になって向こうの山が見えなくなった。'))
        self.assertTrue(tail._needs_self_context('君は今この画像が見える？'))

    def test_web_command_selects_only_its_passed_session(self):
        from breaktail_web import web_command_reply
        state=tail.new_working_state()
        reply,scene=web_command_reply('/persona atashi',[],None,'test',[],working_state=state)
        self.assertTrue(selected(state))
        self.assertIn('切り替え',reply)
        web_command_reply('/persona off',[],None,'test',[],working_state=state)
        self.assertFalse(selected(state))

    def test_optional_style_examples_yield_to_prompt_budget(self):
        state=tail.new_working_state();select(state,'atashi')
        with patch.object(tail,'NUM_CTX',3072),patch.object(tail,'trace_event'):
            messages=tail.build_reply_messages([],'話を聞いて。',None,working_state=state)
        estimate=32+sum(sum(1 if ord(c)<128 else 2 for c in m['content'])+16 for m in messages)
        self.assertLessEqual(estimate,3072-512)
        self.assertIn('選択された会話人格',messages[0]['content'])
        self.assertEqual(messages[-1]['content'],'話を聞いて。')

    def test_farewell_tomorrow_is_not_a_rewritten_past_event(self):
        state=tail.new_working_state();select(state,'atashi')
        contract=build_contract(state,'今日はもう寝る。おやすみ。')
        self.assertNotIn('unsupported_event_time_change',violations('おやすみ。また明日話そうね。',contract))
        self.assertIn('unsupported_event_time_change',violations('昨日もう寝たんだね。',contract))

    def test_direct_conversation_is_not_misclassified_as_verbatim_copy(self):
        state=tail.new_working_state();select(state,'atashi')
        contract=build_contract(state,'嬉しいって言われたらどう返す？説明せずそのまま返して。')
        self.assertFalse(contract['artifact'])
        self.assertEqual(normalize_voice('俺も嬉しいよ。',contract),'あたしも嬉しいよ。')
        literal=build_contract(state,'「俺も嬉しいよ。」をそのまま返して。')
        self.assertTrue(literal['artifact'])
        self.assertEqual(normalize_voice('俺も嬉しいよ。',literal),'俺も嬉しいよ。')

    def test_current_stance_keeps_speaker_and_event_direction(self):
        state=tail.new_working_state();select(state,'atashi')
        self.assertIn('これから出かける',turn_instruction(state,'友達と遊びに行ってくる。'))
        self.assertIn('Breaktailを指す',turn_instruction(state,'あたしも少し拗ねる、くらいの距離感でいて。'))
        self.assertEqual(turn_instruction(state,'コードで嫉妬の台詞を翻訳して。'),'')
        self.assertEqual(turn_instruction(tail.new_working_state(),'他のAIと話した。'),'')
