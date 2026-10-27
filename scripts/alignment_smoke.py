"""Exactly twelve Qwen turns. Scripted user inputs are NOT real feedback data."""
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
    rows = []
    with tempfile.TemporaryDirectory(dir=ROOT / 'work') as directory:
        session = ChatSession(OllamaAdapter('qwen2.5:14b', timeout=180), Path(directory) / 'events.jsonl')
        try:
            for text in ('おはよう', '明日のイベントで一日潰れる', 'そういうことじゃない', '眠い',
                         '今日はマラソン大会や！', '参加するの！', 'ランナーとして', 'ああ',
                         '454位！商品なし！', 'よお！', '前にマラソン大会の話したよな？', '起きたよ'):
                try:
                    reply = session.turn(text)
                    row = {'user': text, 'assistant': reply, 'meta': session.last_response_meta,
                           'alignment': session.status()['conversation_alignment']}
                except ModelError as exc:
                    row = {'user': text, 'error': str(exc)}
                rows.append(row)
                print(json.dumps({'turn': len(rows), **row}, ensure_ascii=False), flush=True)
            counts = session.fio.preferences.counts()
        finally:
            session.close()
    report = {'model': 'qwen2.5:14b', 'at': datetime.now().astimezone().isoformat(),
              'scope': 'observed_inference_only_cpu_verifier_is_not_human_quality_judge',
              'scripted_feedback_candidates_discarded': counts,
              'training_records_exported': 0, 'turns': rows}
    (ROOT / 'reports/alignment-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return int(any('error' in r for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
