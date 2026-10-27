"""Explicit human review and trusted exports. No review is inferred from conversation."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from companion_core.preferences import PreferenceStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True, type=Path)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    add = sub.add_parser('import-candidates')
    add.add_argument('input', type=Path)
    review = sub.add_parser('approve')
    review.add_argument('id')
    review.add_argument('--reviewer', required=True, help='Human operator identity; explicit approval attestation')
    export = sub.add_parser('export')
    export.add_argument('--split', choices=['train', 'dev'], default='train')
    export.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    store = PreferenceStore(args.store)
    if args.action == 'import-candidates':
        for line in args.input.read_text(encoding='utf-8').splitlines():
            if line.strip():
                store.append(json.loads(line))
    elif args.action == 'approve':
        store.approve(args.id, reviewer=args.reviewer)
    elif args.action == 'export':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in store.trusted(args.split)), encoding='utf-8')
    print(json.dumps(store.counts(), ensure_ascii=False))


if __name__ == '__main__':
    main()
