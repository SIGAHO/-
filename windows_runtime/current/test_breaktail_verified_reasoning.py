import json
import unittest
from breaktail_working_state import new_working_state, update_working_state
from breaktail_verification import arithmetic, parse_boxes, verify_reply
from breaktail_conversation_state import session_context


class VerificationTests(unittest.TestCase):
    def state(self):
        state = new_working_state()
        for i,text in enumerate(['帰り道にパン買ったんだけど、袋でぺちゃんこ。',
            '俺の呼び名はナギ、同行者は妹のミオ。土曜に海へ、予算は二人で6000円。ミオは人混みが苦手。',
            'ミオは妹じゃなくて姉。土曜じゃなく日曜に変更。',
            '電車が二人往復で2400円、昼食が一人1200円なら残りは？',
            '雨なら水族館、晴れなら海。ただし水族館の入場料は二人で3000円。']):
            update_working_state(state,text,i)
        return state

    def test_budget_and_false_correction(self):
        state = self.state()
        answer,audit = verify_reply('雨の日も予算に収まる？不足は？','1500円残る',state)
        self.assertEqual(audit['remaining'],-1800)
        self.assertIn('1800円不足',answer)
        answer,audit = verify_reply('6000−2400−2400は2200円だよ。訂正して','同意',state)
        self.assertEqual(audit['value'],1200)
        self.assertIn('2200円ではなく',answer)

    def test_no_invented_or_assistant_facts(self):
        state = self.state()
        update_working_state(state,'猫の話をしよう',9)
        state = json.loads(json.dumps(state))
        facts = state['conversation']['facts']
        self.assertEqual(facts['user_name']['value'],'ナギ')
        self.assertEqual(facts['companion']['value'],'ミオ')
        self.assertEqual(facts['relationship']['value'],'姉')
        self.assertEqual(facts['day']['value'],'日曜')
        self.assertEqual(facts['first_food']['value'],'パン')
        self.assertEqual(facts['companion_dislikes']['value'],'人混み')
        self.assertTrue(all(f['source']=='user' for f in facts.values()))
        self.assertNotIn('午前中',json.dumps(facts,ensure_ascii=False))

    def test_box_enumeration_and_followup(self):
        text = '箱A・B・Cの一つに鍵がある。『鍵はAにある』『鍵はBにない』『鍵はAにない』の三文のうち、正しいのはちょうど一つ。'
        state = new_working_state()
        reply,audit = verify_reply(text,'C',state)
        self.assertEqual(audit['counts'],{'A':2,'B':1,'C':2})
        self.assertEqual(audit['answers'],['B'])
        reply,audit = verify_reply('箱の推理の説明を直して','C',json.loads(json.dumps(state)))
        self.assertTrue(reply.startswith('鍵は箱B。'))

    def test_variant_is_computed_not_memorized(self):
        text = '箱D・E・Fの一つに鍵がある。『鍵はEにある』『鍵はDにない』『鍵はEにない』の三文のうち、正しいのはちょうど一つ。'
        self.assertEqual(verify_reply(text,'',new_working_state())[1]['answers'],['D'])

    def test_safe_arithmetic(self):
        self.assertEqual(arithmetic('10000−(1500×2)−2500'),4500)
        self.assertEqual(arithmetic('0.1＋0.2'),arithmetic('0.3'))
        for expression in ['__import__("os")','2**100','x+1','1/0']:
            with self.assertRaises((ValueError,ZeroDivisionError)):
                arithmetic(expression)

    def test_no_verification_without_evidence_or_on_other_topic(self):
        self.assertIsNone(verify_reply('予算の残りは？','不明',new_working_state())[1])
        self.assertEqual(verify_reply('猫の小話を作って','物語',self.state()),('物語',None))

    def test_preferences_survive_json_reload(self):
        state = new_working_state()
        update_working_state(state,'アドバイスより、短く雑談して。敬語なし。')
        state = json.loads(json.dumps(state))
        prompt = session_context(state,'寂しかった。今は解決策も質問もいらない。ひとことだけ。')
        self.assertIn('質問を追加しない',prompt)
        self.assertIn('敬語なし',prompt)
        self.assertIn('一文だけ',prompt)

    def test_non_food_purchase_is_not_labeled_food(self):
        state = new_working_state()
        update_working_state(state,'新しい車を買った。')
        self.assertNotIn('first_food',state['conversation']['facts'])
