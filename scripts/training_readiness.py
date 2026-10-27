"""Training scaffold: report trusted data and hardware; never starts optimization."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from companion_core.preferences import PreferenceStore


def readiness(store):
    rows = store.trusted('train')
    pairs = sum(bool(r['chosen'] and r['rejected']) for r in rows)
    singles = len(rows) - pairs
    method = 'DPO_or_SimPO' if pairs > singles else 'KTO' if singles else 'insufficient_approved_data'
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.free', '--format=csv,noheader'],
                                capture_output=True, text=True, timeout=10, check=True)
        gpu = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        gpu = 'unavailable'
    return {'schema_version': 1, 'counts': store.counts(), 'trusted_train': len(rows),
            'trusted_dev': len(store.trusted('dev')), 'pairs': pairs, 'singles': singles,
            'method_candidate': method, 'gpu_name_total_free_MiB': gpu,
            'training_started': False, 'hardware_fit': 'not_established',
            'blockers': ['human-reviewed diverse train/dev data and untouched session holdout required',
                         'pin HF base revision/tokenizer and compatible trainer versions',
                         'profile actual QLoRA activation/optimizer memory; GGUF cannot train',
                         'store versioned adapter manifest and verify unload rollback'],
            'config': json.loads((ROOT / 'training/preferences/adapter-config.json').read_text(encoding='utf-8'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = readiness(PreferenceStore(args.store))
    raw = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw, encoding='utf-8')
    print(raw)


if __name__ == '__main__':
    main()
