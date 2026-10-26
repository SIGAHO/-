"""Six-turn inference observation only; no model judging or training data."""
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from companion_core.chat import ChatSession
from companion_core.encoding import configure_stdio
from companion_core.model_adapter import OllamaAdapter, ModelError


def main():
    configure_stdio()
    observations = []
    with tempfile.TemporaryDirectory() as directory:
        session = ChatSession(OllamaAdapter('qwen2.5:14b', timeout=180), Path(directory) / 'events.jsonl')
        try:
            for text in ('今日はマラソン大会や！', '参加するの！', 'ランナーとして', 'ああ', 'は？', '？？'):
                try:
                    reply = session.turn(text)
                    item = {'user': text, 'assistant': reply, 'meta': session.last_response_meta}
                except ModelError as exc:
                    item = {'user': text, 'error': str(exc)}
                observations.append(item)
                print(json.dumps(item, ensure_ascii=False), flush=True)
        finally:
            session.close()
    output = ROOT / 'reports' / 'recent-context-smoke.json'
    output.write_text(json.dumps({'model': 'qwen2.5:14b', 'at': datetime.now().astimezone().isoformat(),
                                 'scope': 'observed_only_not_quality_proof', 'turns': observations},
                                ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return int(any('error' in item for item in observations))


if __name__ == '__main__':
    raise SystemExit(main())
