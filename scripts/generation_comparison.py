"""Bounded paired inference experiment; never creates training or approval data."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
from itertools import count
from unittest.mock import patch
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter
from companion_core.retrieval import RetrievalEngine
from companion_core.alignment import ConversationState, ResponseSpec, PolicyVerifier


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def short_instruction(spec):
    act = {'acknowledge': '今の発言を短く受け止める', 'apologize': '直前の自分のずれを短く認める',
           'continue': '直前の話に短く応じる', 'answer': '聞かれたことに答える',
           'celebrate': '喜びに応じる', 'advise': '求められた助言をする',
           'explain': '依頼を説明する', 'joke': '冗談に応じる'}[spec.act]
    forbidden = [name for name, allowed in [('質問', spec.question_allowed), ('助言', spec.advice_allowed),
                 ('励まし', spec.encouragement_allowed), ('称賛', spec.praise_allowed),
                 ('前向きな言い換え', spec.positive_reframe_allowed)] if not allowed]
    return '会話行為：' + act + '。' + '・'.join(forbidden) + 'を足さない。自然な日本語で' + ('1〜2文。' if spec.length == 'short' else '具体的に。')


def variant_b(messages, spec):
    result = copy.deepcopy(messages)
    prefix, raw = result[0]['content'].split('\nCPU_CONTEXT\n', 1)
    prefix = prefix.split('\n役割分離:', 1)[0]
    cpu = json.loads(raw)
    del cpu['response_spec']
    result[0]['content'] = prefix + '\n' + short_instruction(spec) + '\nCPU_CONTEXT\n' + json.dumps(cpu, ensure_ascii=False)
    return result


class FrozenHistorySession(ChatSession):
    """Prepare real CPU contexts while replaying untrusted historical AI text only."""
    def generate_reply(self, context, messages):
        self.captured = copy.deepcopy(messages)
        return self.frozen_reply


def prepare():
    source = json.loads((ROOT / 'reports/alignment-smoke.json').read_text(encoding='utf-8'))
    cases = []
    (ROOT / 'work').mkdir(exist_ok=True)
    # Synthetic fixture identifiers must be stable, not randomly resemble the
    # personal rank removed from the source dialogue (e.g. UUID containing 454).
    # This affects preparation only; real model inference is never mocked.
    fixture_ids = count(1)
    with tempfile.TemporaryDirectory(dir=ROOT / 'work') as directory, patch(
            'uuid.uuid4', side_effect=lambda: uuid.UUID(int=next(fixture_ids))):
        session = FrozenHistorySession(FakeModelAdapter(), Path(directory) / 'events.jsonl', retrieval=RetrievalEngine())
        try:
            for i, row in enumerate(source['turns']):
                text = row['user'].replace('454', '400')
                session.frozen_reply = row['assistant'].replace('454', '400')
                session.turn(text)
                a = session.captured
                cases.append({'id': i + 1, 'user': text, 'A': a, 'B': variant_b(a, session.planned_spec),
                              'spec': session.planned_spec, 'state': session.planned_state})
        finally:
            session.close()
    return cases, source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Permit at most 24 real inference requests')
    parser.add_argument('--output', default='reports/generation-comparison.json')
    parser.add_argument('--inputs', help='Replay exact stored prompts/state from an earlier comparison JSON')
    args = parser.parse_args()
    if args.inputs:
        source = json.loads(Path(args.inputs).read_text(encoding='utf-8'))
        cases = [{**row, 'spec': ResponseSpec(**row['spec']), 'state': ConversationState(**row['state'])}
                 for row in source['inputs']]
        if len(cases) != 12 or any(c['A'][1:] != c['B'][1:] for c in cases):
            raise ValueError('Exactly twelve paired frozen histories required')
    else:
        cases, source = prepare()
    report = {'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'started_utc': datetime.now(timezone.utc).isoformat(), 'model': 'qwen2.5:14b',
              'design': 'paired frozen-history single-candidate ablation; NOT end-to-end regeneration quality',
              'history_source': 'alignment-smoke.json AI text, untrusted context only; rank abstracted to 400',
              'source_sha256': digest(source), 'human_naturalness': 'not_evaluated_pending_independent_human',
              'C': {'status': 'not_comparable', 'independently_approved_examples_available': 0},
              'training_records_exported': 0, 'approval_operations': 0,
              'limits': {'max_inferences': 24, 'wall_seconds': 900, 'request_timeout_seconds': 60,
                         'num_predict': 256, 'num_ctx': 8192, 'temperature': 0.6, 'seed': 20261030,
                         'parallel_requests': 1, 'retries': 0, 'offline': 'stop immediately; no fake substitution',
                         'gpu': 'existing local Ollama scheduling; no exclusive GPU claim or service restart'},
              'inputs': [], 'results': [], 'status': 'prepared_only', 'attempts': 0}
    output = ROOT / args.output
    if output.exists():
        raise ValueError('Preserve previous evidence: choose a new --output path')
    output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for case in cases:
        report['inputs'].append({k: v for k, v in case.items() if k not in {'spec', 'state'}} |
                                {'spec': case['spec'].to_dict(), 'state': case['state'].to_dict(),
                                 'history_sha256': digest(case['A'][1:])})
    save()
    if not args.run:
        return 0
    start = time.monotonic()
    try:
        with urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
            models = json.load(response)['models']
        report['model_identity'] = next(m for m in models if m['name'] == report['model'])
    except Exception as exc:
        report.update(status='not_run_model_unavailable', error=str(exc))
        save()
        return 2
    for case in cases:
        # Alternate order to reduce warmup/time bias; exact same role history per pair.
        for condition in (('A', 'B') if case['id'] % 2 else ('B', 'A')):
            remaining = 900 - (time.monotonic() - start)
            if remaining <= 0:
                report['status'] = 'budget_exhausted'
                save()
                return 2
            row = {'id': case['id'], 'condition': condition, 'human_review': None}
            body = {'model': report['model'], 'messages': case[condition], 'stream': False,
                    'options': {k: report['limits'][k] for k in ('num_predict', 'num_ctx', 'temperature', 'seed')}}
            request = Request('http://127.0.0.1:11434/api/chat', data=json.dumps(body, ensure_ascii=False).encode(),
                              headers={'Content-Type': 'application/json'})
            before = time.monotonic()
            report['attempts'] += 1
            try:
                with urlopen(request, timeout=min(60, remaining)) as response:
                    data = json.load(response)
                row['raw_response'] = data
                text = data['message']['content']
                row['stopped'] = not text.strip() or data.get('done') is not True
                row['truncated'] = data.get('done_reason') == 'length'
                row['cpu_verifier'] = PolicyVerifier().verify(text, case['spec'], case['state'], case['user'])
                row['semantic_categories'] = {name: 'requires_independent_human_review' for name in
                    ('excessive_praise', 'rejected_encouragement_repeat', 'old_topic_revival', 'recent_reference_loss', 'japanese_naturalness')}
            except Exception as exc:
                row.update(error=str(exc), stopped=True)
                report['status'] = 'stopped_transport_error'
            row['elapsed_seconds'] = time.monotonic() - before
            report['results'].append(row)
            report['wall_seconds'] = time.monotonic() - start
            save()
            print(json.dumps({k: row[k] for k in ('id', 'condition', 'elapsed_seconds', 'stopped')}, ensure_ascii=False), flush=True)
            if 'error' in row:
                return 2
    report['status'] = 'completed'
    save()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
