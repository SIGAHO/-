"""Re-evaluate observed human partitions; never change historical reports or use text for learning."""
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT))
from experiments.topic_corpus import run as corpus
from experiments.topic_holdout import run as holdout
from experiments.runner import NOW, FIXTURE_DATE
from companion_core.core import CompanionCore


def main():
    dialogues, splits = corpus.read_archive(ROOT/'work/corpora/JMultiWOZ_1.0.zip')
    jm = {(name, turn['turn_id']): turn['utterance'] for name, d in dialogues.items() for turn in d['turns'] if turn['speaker']=='USER'}
    reports = []
    for suite, partition in [('topic_corpus', None), ('topic_holdout', 'test'), ('topic_holdout_v2', 'dev'), ('topic_holdout_v3', 'train')]:
        manifest = json.loads((ROOT/'experiments'/suite/'manifest.json').read_text(encoding='utf-8'))
        bsd = {}
        if partition:
            path = ROOT/'work/corpora'/f'{partition}.json'
            raw = path.read_text(encoding='utf-8')
            expected = manifest['bsd_source']['test_json_normalized_sha256']
            if hashlib.sha256(raw.encode()).hexdigest() != expected:
                raise ValueError('BSD pinned hash mismatch')
            bsd = {(d['id'], turn['no']): turn['ja_sentence'] for d in json.loads(raw) for turn in d['conversation']}
        rows = []
        for row in manifest['rows']:
            table = jm if row.get('dataset', 'jmultiwoz')=='jmultiwoz' else bsd
            text = table[(row['dialogue'], row['turn_id'])]
            if hashlib.sha256(text.encode()).hexdigest() != row['text_sha256']:
                raise ValueError('observed text hash mismatch')
            rows.append({**row, 'text': text})
        failures = Counter()
        observations = []
        replay = []
        policy_passed = 0
        for identity in dict.fromkeys((r.get('dataset', 'jmultiwoz'), r['dialogue']) for r in rows):
            subset = [r for r in rows if (r.get('dataset', 'jmultiwoz'), r['dialogue'])==identity]
            with patch('time.time', return_value=NOW), patch('companion_core.time_engine.TimeEngine.now', return_value=FIXTURE_DATE):
                observed, replay_ok = corpus.predict_texts([r['text'] for r in subset])
                # Supplement historical invariants with the new prompt-topic policy; do not waive historical failures.
                core = CompanionCore()
                for row in subset:
                    ctx = core.handle(row['text'])
                    if ctx['intent'] == 'ambiguous_followup':
                        policy_passed += int(ctx['prompt_context']['topic'] is None and not ctx['prompt_context']['memory'])
                    elif core.router.casual.fullmatch(row['text']):
                        policy_passed += int(ctx['prompt_context']['topic'] is None and not ctx['prompt_context']['memory'])
                    else:
                        policy_passed += 1
            replay.append(replay_ok)
            for row, pred in zip(subset, observed):
                observations.append({**row, 'predicted_cluster': pred['predicted_cluster']})
                failures.update(k for k, passed in pred['invariants'].items() if not passed)
        metrics = {}
        for dataset in dict.fromkeys(r.get('dataset', 'jmultiwoz') for r in observations):
            metrics[dataset] = corpus.score_transitions([r for r in observations if r.get('dataset', 'jmultiwoz')==dataset])
        report = {'suite': suite, 'utterances': len(rows), 'dialogues': len(replay), 'replay_passed': sum(replay),
                  'historical_invariant_failures': dict(failures), 'prompt_policy_passed': policy_passed, 'metrics': metrics}
        reports.append(report)
        print(json.dumps({k:v for k,v in report.items() if k!='metrics'}), flush=True)
    destination = ROOT/'reports/hardening-corpus.json'
    destination.write_text(json.dumps({'observed_data_only': True, 'training_examples': 0, 'model_labels': 0, 'suites': reports}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

if __name__=='__main__':
    main()
