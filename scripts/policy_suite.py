"""Behavior metrics over development hypotheses; no exact reply matching or model judging."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_alignment import CASES, evaluate_case
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter


def evaluate():
    observations = []
    for case in CASES:
        state, spec, good, bad = evaluate_case(case)
        chat = ChatSession(FakeModelAdapter([case['good'], case['good']]))
        aborted = False
        try:
            for role, text in case['history']:
                if role == 'user':
                    chat.core.handle(text)
                else:
                    chat.core.record_assistant_output(text)
            aborted = not bool(chat.turn(case['user']))
        except Exception:
            aborted = True
        finally:
            chat.close()
        observations.append({'id': case['id'], 'reference_expected': case.get('reference', False),
                             'conversation_aborted': aborted,
                             'reference_resolved': bool(state.reference_target), 'state': state.to_dict(),
                             'spec': spec.to_dict(), 'verifier': good,
                             'negative_control_detected': case['bad_issue'] in bad['issues']})
    def rate(issue, rows=observations):
        return sum(issue in r['verifier']['issues'] for r in rows) / len(rows) if rows else None
    refs = [r for r in observations if r['reference_expected']]
    rejected = [r for r in observations if r['state']['reaction_to_previous'] == 'rejected']
    metrics = {
        'recent_reference_resolution': sum(r['reference_resolved'] for r in refs) / len(refs),
        'unsolicited_advice_rate': rate('forbidden_advise'),
        'forced_question_rate': rate('forbidden_ask'), 'praise_overuse_rate': rate('forbidden_praise'),
        'positive_reframe_after_rejection_rate': rate('forbidden_reframe', rejected),
        'rejected_strategy_repeat_rate': rate('rejected_strategy_repeat', rejected),
        'unrelated_old_topic_resurrection_rate': rate('old_topic_resurrection'),
        'language_contamination_rate': rate('language_mixing'),
        'response_spec_adherence': sum(r['verifier']['adherent'] for r in observations) / len(observations),
        'conversation_abort_rate': sum(r['conversation_aborted'] for r in observations) / len(observations),
        'negative_control_detection': sum(r['negative_control_detected'] for r in observations) / len(observations)}
    return {'schema_version': 1, 'scope': 'multiturn_development_hypotheses_with_positive_and_negative_controls',
            'limitations': 'Scripted candidate metrics, not Qwen conversational quality; abort rate also tested through ChatSession integration.',
            'total': len(observations), 'metrics': metrics, 'cases': observations}


if __name__ == '__main__':
    report = evaluate()
    (ROOT / 'reports/policy-suite.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}, ensure_ascii=False, indent=2))
