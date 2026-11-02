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
        for question in ['雨でも6000円で足りる？','雨の日も予算6000円以内？','雨天の費用の総額は？']:
            answer,audit=verify_reply(question,'足りる',state)
            self.assertEqual(audit['remaining'],-1800)
            self.assertIn('1800円不足',answer)

    def test_multi_field_recall_is_complete_and_has_no_blanket_unknown(self):
        state=self.state()
        question='呼び名、同行者の名前と続柄、苦手なもの、最初に買った食べ物を確認したい。何だった？'
        answer,audit=verify_reply(question,'ナギさんだけ覚えているよ。',state)
        for value in ('ナギ','ミオ','姉','人混み','パン'):self.assertIn(value,answer)
        self.assertNotIn('不明',answer)
        self.assertEqual(audit['kind'],'user_only_fact_recall')
        del state['conversation']['facts']['first_food']
        answer,_=verify_reply(question,'パンだったはず。',state)
        self.assertIn('食べ物は不明',answer)
        answer,audit=verify_reply('交通2400円、昼食2400円、入場3000円。6000円で足りる？','足りる',state)
        self.assertEqual(audit['remaining'],-1800)
        answer,audit=verify_reply('晴れの海なら予算6000円で足りる？','不明',state)
        self.assertEqual(audit['remaining'],1200)

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

    def test_plan_summary_cannot_promote_model_proposals(self):
        state=self.state()
        answer,audit=verify_reply('ここまでの予定を一文でまとめて。','午前中に昼食持参で海へ行く。',state)
        self.assertEqual(audit['kind'],'user_only_plan_summary')
        self.assertNotIn('午前中',answer)
        self.assertNotIn('持参',answer)
        self.assertIn('姉のミオ',answer)

    def test_constraint_based_option_stays_unadopted_and_uses_real_remainder(self):
        state=self.state()
        before=json.loads(json.dumps(state['conversation']['facts']))
        answer,audit=verify_reply('予定を一緒に考えたい。','別の場所へ行こう。',state)
        self.assertEqual(audit['kind'],'constraint_based_proposal')
        self.assertFalse(audit['adopted'])
        self.assertIn('海',answer);self.assertIn('1200円',answer);self.assertIn('候補',answer)
        self.assertNotIn('？',answer)
        self.assertEqual(before,state['conversation']['facts'])

    def test_only_changed_fields_are_reported(self):
        state=self.state()
        update_working_state(state,'ミオは姉じゃなく妹。日曜じゃなく月曜に変更。変更点だけ。')
        answer,audit=verify_reply('変更点だけ。','予算6000円も海も同じ。',state)
        self.assertEqual(audit['kind'],'explicit_changes')
        self.assertIn('妹',answer);self.assertIn('月曜',answer)
        self.assertNotIn('6000',answer);self.assertNotIn('海',answer)

    def test_plan_summary_preserves_requested_remaining_budget(self):
        state=self.state()
        answer,_=verify_reply('確定した予定を誰と・いつ・どこ・予算・残金だけ一文でまとめて。','',state)
        self.assertIn('残金は1200円',answer)
        self.assertNotIn('人混み',answer)
        retry,_=verify_reply('予定の確定事項と残金の両方を、一文でもう一度答えて。','',state)
        self.assertIn('ナギ',retry);self.assertIn('姉のミオ',retry);self.assertIn('1200円',retry)
