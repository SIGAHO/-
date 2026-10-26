"""Live retrieval + qwen inference observations only; not labels, training or grading."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from companion_core.chat import ChatSession
from companion_core.encoding import configure_stdio
from companion_core.model_adapter import OllamaAdapter
from companion_core.retrieval import RetrievalEngine


def main():
    configure_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'work/web-smoke.json')
    args = parser.parse_args()
    observations = []
    # Independent public names, not taken from user conversation or turned into labels.
    for query in ('「夜に駆ける」について教えて', '「葬送のフリーレン」について教えて', '「藤井風」について教えて'):
        with tempfile.TemporaryDirectory() as tmp:
            chat = ChatSession(OllamaAdapter('qwen2.5:14b', timeout=180), Path(tmp)/'events.jsonl',
                               retrieval=RetrievalEngine(enabled=True))
            row = {'query': query}
            try:
                row['reply'] = chat.turn(query)
                row['meta'] = chat.last_response_meta
                row['sources'] = chat.core.provenance.last
                row['where_from'] = chat.turn('その情報どこから？')
                row['cache_entries'] = len(chat.retrieval.cache)
            except Exception as exc:
                row['error'] = type(exc).__name__+': '+str(exc)
            observations.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'model': 'qwen2.5:14b', 'purpose': 'inference_observations_only',
        'training_examples': 0, 'model_labels': 0, 'observations': observations}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return int(any('error' in r or r.get('meta', {}).get('unverified', True) for r in observations))


if __name__ == '__main__':
    raise SystemExit(main())
