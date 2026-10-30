"""Bounded real-model dialogue driver. Profiles are isolated; no training/approval writes."""
import argparse
import hashlib
import os
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from companion_core.chat import ChatSession
from companion_core.model_adapter import ModelAdapter, ModelError
from companion_core.retrieval import RetrievalEngine


class RecordedAdapter(ModelAdapter):
    def __init__(self, directory, temperature, budget_name='live-budget.jsonl', max_attempts=100):
        self.path = directory / 'requests.jsonl'
        self.temperature = temperature
        self.budget_name = budget_name
        self.max_attempts = max_attempts

    def generate(self, messages):
        ledger = ROOT / 'reports' / self.budget_name
        rows = [json.loads(x) for x in ledger.read_text(encoding='utf-8').splitlines()] if ledger.exists() else []
        if len(rows) >= self.max_attempts or rows and time.time() - rows[0]['time'] > 7200:
            raise ModelError('inference / 2 hour experiment budget exhausted')
        with ledger.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'time': time.time(), 'profile': str(self.path.parent.name)}) + '\n')
        payload = {'model': 'qwen2.5:14b', 'messages': messages, 'stream': False,
                   'options': {'temperature': self.temperature, 'seed': 20261030,
                               'num_ctx': 8192, 'num_predict': 256}}
        row = {'payload': payload, 'time': time.time()}
        try:
            request = Request('http://127.0.0.1:11434/api/chat',
                              data=json.dumps(payload, ensure_ascii=False).encode(),
                              headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=60) as response:
                row['raw_response'] = json.load(response)
            data = row['raw_response']
            if not data.get('done') or not data['message']['content'].strip() or data.get('done_reason') == 'length':
                raise ModelError('empty, incomplete or truncated response')
            return data['message']['content'].strip()
        except Exception as exc:
            row['error'] = str(exc)
            raise ModelError(str(exc)) from exc
        finally:
            row['seconds'] = time.time() - row['time']
            with self.path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--profile', required=True)
    p.add_argument('--mode', choices=['legacy', 'compact', 'reaction', 'direct', 'anchored', 'character', 'character-repair'], default='legacy')
    p.add_argument('--temperature', type=float, default=.6)
    p.add_argument('--experiment', help='New isolated inference budget name (letters, digits, hyphen)')
    p.add_argument('text', nargs='+')
    args = p.parse_args()
    if not args.profile.replace('-', '').isalnum():
        p.error('profile must be an isolated simple name')
    if args.experiment and not args.experiment.replace('-', '').isalnum():
        p.error('experiment must be a simple name')
    directory = ROOT / 'reports/live-profiles' / args.profile
    directory.mkdir(parents=True, exist_ok=True)
    config = {'mode': args.mode, 'temperature': args.temperature, 'training_eligible': False,
              'human_approved': False, 'web': 'disabled', 'profile': args.profile}
    config_path = directory / 'config.json'
    if config_path.exists() and json.loads(config_path.read_text(encoding='utf-8')) != config:
        raise ValueError('Use a new profile for a new condition')
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    budget_name = ('live-experiment-' + args.experiment + '.jsonl' if args.experiment else
                   'live-character-followup-budget.jsonl' if args.mode == 'character' else 'live-budget.jsonl')
    adapter = RecordedAdapter(directory, args.temperature, budget_name, 60 if args.experiment else
                              20 if args.mode == 'character' else 100)
    session = ChatSession(adapter, directory / 'events.jsonl', retrieval=RetrievalEngine(), prompt_mode=args.mode)
    try:
        for index, text in enumerate(args.text):
            row = {'user': text, 'time': time.time(), 'new_process_replay': index == 0,
                   'process_id': os.getpid(),
                   'prompt_source_sha256': hashlib.sha256((ROOT / 'src/companion_core/prompt.py').read_bytes()).hexdigest()}
            try:
                row['assistant'] = session.turn(text)
                row['trace'] = session.alignment_trace
                row['meta'] = session.last_response_meta
            except Exception as exc:
                row['error'] = str(exc)
                raise
            finally:
                with (directory / 'dialogue.jsonl').open('a', encoding='utf-8') as f:
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
                print(json.dumps({k: row[k] for k in ('user', 'assistant', 'error') if k in row} |
                                 {'cpu': row.get('meta', {}).get('cpu', False)}, ensure_ascii=False), flush=True)
    finally:
        session.close()


if __name__ == '__main__':
    main()
