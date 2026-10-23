"""Inference smoke only. Outputs are observations, never training data or labels."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from companion_core.chat import ChatSession
from companion_core.encoding import configure_stdio
from companion_core.model_adapter import OllamaAdapter, ModelError


def main():
    configure_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'work/model-smoke.json')
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    adapter = OllamaAdapter('qwen2.5:14b', timeout=args.timeout)
    turns = []
    with tempfile.TemporaryDirectory() as directory:
        session = ChatSession(adapter, Path(directory)/'events.jsonl')
        # Synthetic setup is only a stale-topic probe, no desired model utterance.
        session.core.handle('LUMEN ARCという曲を聴いた')
        for text in ('調子どう？', 'その情報どこから？', 'Breaktailの記憶に入ってる？', 'は？', '今何時？', '8時まであと何分？'):
            try:
                reply = session.turn(text)
                intent = session.core.router.route(text)
                turns.append({'input': text, 'reply': reply, 'intent': intent,
                              'meta': session.last_response_meta, 'provenance': session.core.provenance.last})
                print(json.dumps({'input': text, 'reply': reply, 'intent': intent}, ensure_ascii=False), flush=True)
            except ModelError as exc:
                turns.append({'input': text, 'error': str(exc)})
                print(str(exc), flush=True)
    checks = {
        'six_turns_no_errors': len(turns) == 6 and not any('error' in t for t in turns),
        'casual_no_old_song': bool(turns) and 'LUMEN ARC' not in turns[0].get('reply', ''),
        'internal_not_external_unverified': all(not t.get('meta', {}).get('unverified', False) for t in turns),
        'memory_source_qualified': len(turns)>2 and 'ユーザー申告' in turns[2].get('reply', ''),
        'ambiguous_cpu': len(turns)>3 and turns[3].get('meta', {}).get('cpu', False),
        'clock_and_remaining_cpu': len(turns)==6 and all(t.get('meta', {}).get('cpu', False) for t in turns[4:]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'model': adapter.model, 'at': datetime.now().astimezone().isoformat(),
                          'scope': 'observed_smoke_not_quality_proof', 'checks': checks, 'turns': turns}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return int(not all(checks.values()))

if __name__ == '__main__':
    raise SystemExit(main())
