import unittest
from breaktail_ordering import parse_ordering,solve_ordering,verify_ordering


class OrderingTests(unittest.TestCase):
    def test_direction_is_computed_from_conditions(self):
        problem=parse_ordering('乙は甲より右、丙は乙より右。')
        self.assertEqual(solve_ordering(problem),[('甲','乙','丙')])
        problem=parse_ordering('乙は甲より左、丙は乙より左。')
        self.assertEqual(solve_ordering(problem),[('丙','乙','甲')])

    def test_false_followup_does_not_replace_conditions(self):
        text='緑の札は白の札より前、黒の札は白の札より後。'
        session={}
        verify_ordering(text,session,[])
        reply,audit=verify_ordering('白、緑、黒でもいい？元の条件で確かめて。',session,[{'role':'user','content':text}])
        self.assertEqual(audit['solutions'],[['緑の札','白の札','黒の札']])
        reply,audit=verify_ordering('黒、緑、白でも条件を満たす？理由を教えて。',session,[{'role':'user','content':text}])
        self.assertEqual(audit['solutions'],[['緑の札','白の札','黒の札']])
        self.assertIn('緑の札が白の札より先',reply)

    def test_cycles_ambiguity_limits_and_topic_scope(self):
        self.assertEqual(solve_ordering(parse_ordering('甲は乙より前。乙は甲より前。')),[])
        self.assertEqual(len(solve_ordering(parse_ordering('甲は乙より前。丙は丁より前。'))),6)
        session={}
        verify_ordering('甲は乙より前。乙は丙より前。',session,[])
        self.assertIsNone(verify_ordering('駅へ行く順番を決めよう。',session,[]))
        self.assertIsNone(parse_ordering('甲は乙より前。'))
