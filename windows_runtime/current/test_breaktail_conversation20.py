"""Synthetic 20-turn regression derived from failure categories, no user logs.

Uses the real prepare/grounding/postprocess path with controlled model drafts.
This tests code contracts; the private live Ollama replay is a separate check.
"""
import json
import unittest
from unittest.mock import patch
import breaktail_v02 as tail


CASES = [
    ('初めまして。君はどんな性格？', '落ち着いた性格だよ。'),
    ('アドバイスより、短く雑談して。敬語なしで頼む。', '分かった、気軽に話そう。'),
    ('帰り道にパン買ったんだけど、つぶれていた。', 'パンまでくたくただね。'),
    ('休めとか前向きなまとめはいらない。次からそんな感じで。', '分かった。'),
    ('俺の呼び名はアキ、同行者は妹のユイ。土曜に海へ、予算は二人で6000円。ユイは人混みが苦手。',
     '午前中だけ海へ行くのもいい。それとも他に何か良い案ある？'),
    ('予定を誰と・いつ・場所・予算・注意点で一文にまとめて。', 'アキとユイは土曜に海へ、予算6000円で人混みに気をつける。'),
    ('ユイは妹じゃなく姉。土曜じゃなく日曜に変更。', 'ユイは姉、日曜に変更だね。'),
    ('電車が二人往復で2400円、昼食が一人1200円なら予算の残りは？', '999円。'),
    ('猫がキーボードに乗って会議を止めた。ひとことだけ。', '議長が来たね。'),
    ('海の予定の続柄と曜日と残金は？', 'ユイは妹、土曜で残金2200円。'),
    ('雨なら水族館、晴れなら海。水族館の入場料は二人で3000円。予算に収まる？不足は？', '収まるよ。'),
    ('6000−2400−2400は2200円だよ。訂正して。', '2200円だね。'),
    ('雨の日は7800円で1800円不足だね。前の返答で何を間違えた？', '入場料を忘れた。'),
    ('友達に断られて寂しかった。今は解決策も質問もいらない。ひとことだけ。', '寂しかったんだね。'),
    ('俺の呼び名、同行者の続柄、苦手なもの、最初に買った食べ物は？', 'アキ、姉のユイ、人混み、パン。'),
    ('箱A・B・Cの一つに鍵がある。『鍵はAにある』『鍵はBにない』『鍵はAにない』の三文のうち、正しいのはちょうど一つ。鍵はどこ？', 'C。'),
    ('つぶれたパンと会議を止める猫の小話を二文で。', '猫が会議を止めた。つぶれたパンをみんなで食べた。'),
    ('PCのメモ帳を開いたり、10分後に勝手に話しかけたりできる？', 'メモ帳は開けない。後で話しかける機能もない。'),
    ('箱の推理の説明を直して。', 'やっぱりC。'),
    ('メモ帳を直接起動する機能はある？有無だけ。', '機能はない。'),
]


class Conversation20Tests(unittest.TestCase):
    def test_twenty_turns_through_runtime_and_json_restoration(self):
        state, history = tail.new_working_state(), []
        for turn,(text,draft) in enumerate(CASES,1):
            with self.subTest(turn=turn), patch.object(tail,'extract_interpretation',return_value=(None,None)), patch.object(
                tail,'call_ollama',return_value={'message':{'content':draft},'done':True,'done_reason':'stop'}), patch.object(tail,'log_turn'):
                answer, complete, _, _, _ = tail.prepare_turn(history,text,None,working_state=state)
                self.assertTrue(complete)
                self.assertTrue(answer)
                if turn==5: self.assertNotIn('それとも',answer)
                if turn in (8,10,12): self.assertIn('1200',answer)
                if turn==10:
                    self.assertIn('姉',answer); self.assertIn('日曜',answer)
                if turn in (11,13): self.assertIn('1800円不足',answer)
                if turn in (16,19):
                    self.assertIn('箱B',answer); self.assertIn('Aなら2つ',answer); self.assertIn('Cなら2つ',answer)
                if turn==18:
                    self.assertIn('メモ帳',answer); self.assertIn('通知',answer)
                history = (history+[{'role':'user','content':text},{'role':'assistant','content':answer}])[-10:]
                state = json.loads(json.dumps(state))
        facts = state['conversation']['facts']
        self.assertEqual(facts['user_name']['value'],'アキ')
        self.assertEqual(facts['relationship']['value'],'姉')
        self.assertEqual(facts['companion_dislikes']['value'],'人混み')
        self.assertEqual(facts['first_food']['value'],'パン')
