"""Re-run ALL observed external samples as regression, never as unseen holdouts.

Historical freezes/results remain unchanged. Source text and labels come only
from pinned upstream corpora; no model, training or generated ground truth.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.topic_holdout import run as evaluator
from companion_core.topic import TopicTracker


def run(archive, bsd_dir, output):
    dialogues, _ = evaluator.prior.read_archive(archive)
    texts = {(name, turn['turn_id']): turn['utterance']
             for name, dialogue in dialogues.items() for turn in dialogue['turns']}
    bsd = {}
    for split in ('test', 'dev', 'train'):
        raw = (bsd_dir / f'{split}.json').read_text(encoding='utf-8')
        bsd[split] = (raw, {(d['id'], t['no']): t['ja_sentence']
                            for d in json.loads(raw) for t in d['conversation']})
    report = {'evaluation_status': 'previously_observed_regression_only',
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'source_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((ROOT / 'src').rglob('*.py'))},
              'training_examples': 0, 'model_generated_labels': 0, 'samples': {}}
    for directory, split in [('topic_corpus', 'test'), ('topic_holdout', 'test'),
                             ('topic_holdout_v2', 'dev'), ('topic_holdout_v3', 'train')]:
        manifest = json.loads((ROOT / 'experiments' / directory / 'manifest.json').read_text(encoding='utf-8'))
        if 'bsd_source' in manifest:
            expected = manifest['bsd_source']['test_json_normalized_sha256']
            if evaluator.prior.sha(bsd[split][0].encode()) != expected:
                raise ValueError(f'BSD {split} hash mismatch')
        rows = []
        for source in manifest['rows']:
            dataset = source.get('dataset', 'jmultiwoz')
            key = (source['dialogue'], source['turn_id'])
            text = texts[key] if dataset == 'jmultiwoz' else bsd[split][1][key]
            if evaluator.prior.sha(text.encode()) != source['text_sha256']:
                raise ValueError(f'Frozen text hash mismatch: {key}')
            rows.append(source | {'dataset': dataset, 'text': text})
        result = {}
        for dataset in sorted({r['dataset'] for r in rows}):
            subset = [r for r in rows if r['dataset'] == dataset]
            metrics, _ = evaluator.probe(subset, TopicTracker)
            result[dataset] = metrics
        report['samples'][directory] = result
        print(directory, json.dumps(result, ensure_ascii=False), flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if all(r['replay_passed'] == r['dialogues'] and r['invariants_passed'] == r['utterances']
                    for sample in report['samples'].values() for r in sample.values()) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--bsd-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('external_regression.json'))
    args = parser.parse_args()
    raise SystemExit(run(args.archive, args.bsd_dir, args.output))
