"""Inference-only comparison. Prompts are probes, never training/answer labels.

Counts describe explicit user-requested style constraints, not a model judge.
Raw transcripts stay in ignored work/. Old prompt loaded verbatim from ac7fcca.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from companion_core.chat import ChatSession
from companion_core.core import CompanionCore
from companion_core.model_adapter import OllamaAdapter, ModelError
from companion_core.models import SourceType
from companion_core.style import StyleValidator


PROBES = [
    'よっしゃあ、動いたぞ！！',
    '君とちゃんと話せるのが楽しいんだよ',
    '今の時刻だけ教えて',
    '起きてるってば、寝坊扱いするなよ笑',
    '次の予定は20分後。あと何分ある？',
    'やば、支度まだだった！',
    '学校の英語発表の構成を一緒に考えたい',
    '発表は自分が尊敬する作品についてだよ。テーマが尊敬って意味じゃない',
    'うん、それ。まずは短い導入にしたい',
    '技術の話に戻るけど、会話履歴の保存処理を作ってる',
    '同期じゃなくて非同期にするつもり',
    '保存できた！今日はここまでにする',
]


class Recorder(OllamaAdapter):
    def __init__(self):
        super().__init__('qwen2.5:14b', timeout=240)
        self.raw = []

    def generate(self, messages):
        reply = super().generate(messages)
        self.raw.append(reply)
        return reply


def metrics(replies):
    validator = StyleValidator()
    return {'turns': len(replies),
            'banned_phrase_turns': sum(bool(validator.banned.search(r)) for r in replies),
            'polite_marker_count': sum(len(validator.polite.findall(r)) for r in replies),
            'question_ending_turns': sum(r.rstrip().endswith(('?', '？')) for r in replies),
            'mean_chars': round(sum(map(len, replies)) / max(1, len(replies)), 1)}


def main():
    namespace = {'__name__': 'companion_core.old_prompt', '__package__': 'companion_core'}
    old = subprocess.check_output(['git', 'show', 'ac7fcca:src/companion_core/prompt.py'], cwd=ROOT).decode('utf-8')
    exec(compile(old, '<ac7fcca prompt>', 'exec'), namespace)
    old_builder = namespace['PromptBuilder']()
    baseline, revised = [], []
    baseline_core = CompanionCore()
    baseline_adapter, revised_adapter = Recorder(), Recorder()
    session = ChatSession(revised_adapter)
    output = ROOT / 'work/style-smoke-transcript.json'
    report = {'model': 'qwen2.5:14b', 'baseline_commit': 'ac7fcca',
              'source_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((ROOT / 'src').rglob('*.py'))},
              'training_examples': 0, 'model_generated_labels': 0,
              'baseline': baseline, 'revised': revised}
    start = time.monotonic()
    for index, prompt in enumerate(PROBES):
        ctx = baseline_core.handle(prompt)
        reply = baseline_adapter.generate(old_builder.build(ctx, baseline_core.events.events))
        baseline_core.record_assistant_output(reply)
        baseline.append({'input': prompt, 'reply': reply})
        before = len(revised_adapter.raw)
        try:
            reply = session.turn(prompt)
            revised.append({'input': prompt, 'reply': reply, 'meta': dict(session.last_response_meta),
                            'raw': revised_adapter.raw[before:]})
        except ModelError as exc:
            revised.append({'input': prompt, 'error': str(exc), 'raw': revised_adapter.raw[before:]})
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'paired turn {index+1}/{len(PROBES)} complete', flush=True)
    for prompt in ['「INTERNET OVERDOSE」について説明できる？', 'その曲の歌手は誰？']:
        revised.append({'input': prompt, 'reply': session.turn(prompt), 'meta': dict(session.last_response_meta)})
    session.core.memory.add('LUMEN ARCは架空の楽曲。歌唱は仮の人物。', SourceType.VERIFIED_MEMORY)
    try:
        reply = session.turn('LUMEN ARC知ってる？')
        revised.append({'input': 'LUMEN ARC知ってる？', 'reply': reply, 'meta': dict(session.last_response_meta)})
    except ModelError as exc:
        revised.append({'input': 'LUMEN ARC知ってる？', 'error': str(exc)})
    summary = {'model': report['model'], 'baseline_commit': report['baseline_commit'],
               'source_sha256': report['source_sha256'], 'training_examples': 0, 'model_generated_labels': 0,
               'baseline': metrics([r['reply'] for r in baseline]),
               'revised_paired': metrics([r['reply'] for r in revised[:len(PROBES)] if 'reply' in r]),
               'revised_initial_raw': metrics([r['raw'][0] for r in revised[:len(PROBES)] if r.get('raw')]),
               'revised_errors': [r['error'] for r in revised if 'error' in r],
               'style_regenerations': sum(r.get('meta', {}).get('regenerated', False) for r in revised),
               'unverified_replies': sum(r.get('meta', {}).get('unverified', False) for r in revised),
               'trusted_memory_no_external': not session.core.handle('LUMEN ARC知ってる？')['knowledge']['external_required'],
               'revised_model_calls': len(revised_adapter.raw),
               'elapsed_seconds': round(time.monotonic() - start, 1)}
    report['summary'] = summary
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (Path(__file__).parent / 'smoke_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return bool(summary['revised_errors'])


if __name__ == '__main__':
    raise SystemExit(main())
