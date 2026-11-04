import unittest
import breaktail_v02 as tail
from breaktail_self import build_self_context, ground_self_reply


class ReplyIntegrityTests(unittest.TestCase):
    def test_self_description_answers_from_existing_reply_policy(self):
        answer=ground_self_reply('Breaktail、自分ではどんな性格だと思う？','初対面みたいだね。',build_self_context())
        self.assertEqual(answer['reason'],'declared_reply_policy_style')
        self.assertIn('タイプ',answer['reply'])

    def test_self_description_does_not_replace_user_or_scene_personality(self):
        draft='その役では無口な性格だよ。'
        self.assertEqual(ground_self_reply('俺はどんな性格だと思う？',draft,build_self_context())['reply'],draft)
        self.assertEqual(ground_self_reply('君はどんな性格？',draft,build_self_context(),{'name':'劇中'})['reply'],draft)

    def test_followup_removes_whole_sentence(self):
        reply, changes = tail.phase7_postprocess_reply([], '予定を考えたい',
            '昼食を持って行くのもいいんじゃない？それとも他に何か良いアイデアあるかい？')
        self.assertEqual(reply, '昼食を持って行くのもいいんじゃない？')
        self.assertIn('removed_generic_followup', changes)

    def test_substring_in_substantive_answer_is_not_deleted(self):
        draft = '故障した場合は他に何か原因がある。'
        self.assertEqual(tail.phase7_postprocess_reply([], '原因は？', draft)[0], draft)

    def test_two_capability_answers_survive(self):
        answer = ground_self_reply('PCのメモ帳を開いたり、10分後に勝手に話しかけたりできる？',
            'メモ帳は開けない。後で話しかける機能もない。', build_self_context())['reply']
        self.assertIn('メモ帳', answer)
        self.assertIn('通知', answer)
        self.assertIn('ない', answer)

    def test_unrelated_answer_survives_desktop_grounding(self):
        answer = ground_self_reply('メモ帳を開ける？そして2+2は？',
            'メモ帳を開けるよ。2+2は4。', build_self_context())['reply']
        self.assertIn('2+2は4', answer)
        self.assertNotIn('開けるよ', answer)

    def test_two_capabilities_do_not_retain_model_self_commentary(self):
        answer=ground_self_reply('メモ帳を開いたり、あとで勝手に話しかけたりできる？その二つだけ。',
            '無理だよ、そんなのは。能力ないし、気にしないでね。',build_self_context())['reply']
        self.assertEqual(answer.count('。'),2)
        self.assertIn('メモ帳',answer);self.assertIn('通知',answer)
        self.assertNotIn('気にしないで',answer)

    def test_code_regions_unchanged(self):
        draft = '例。\n```python\nprint("それとも他に何かある？")\n```'
        self.assertIn('print("それとも他に何かある？")', tail.phase7_postprocess_reply([], 'コード', draft)[0])

    def test_desktop_code_request_is_not_a_capability_question(self):
        draft = '例。\n```python\nimport subprocess\nsubprocess.Popen(["notepad.exe"])\n```'
        answer = ground_self_reply('メモ帳を開けるコードを書いて',draft,build_self_context())['reply']
        self.assertEqual(answer,draft)
