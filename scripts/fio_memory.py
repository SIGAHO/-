"""Offline diagnostics/rebuild and inference-only memory smoke; no learning or labels."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from companion_core.chat import ChatSession
from companion_core.encoding import configure_stdio
from companion_core.experience import HeatConfig
from companion_core.fio_memory import FIOMemory
from companion_core.model_adapter import FakeModelAdapter, OllamaAdapter
from companion_core.ownership import LogLease
from companion_core.session_memory import SessionRecorder, SessionIndex


class ObservedAdapter:
    def __init__(self, adapter):
        self.adapter, self.requests = adapter, []

    def generate(self, messages):
        self.requests.append(messages)
        return self.adapter.generate(messages)


def probe(model=False, turns=100, timeout=180):
    observations, checks = [], {}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)/'events.jsonl'
        adapter = ObservedAdapter(OllamaAdapter('qwen2.5:14b', timeout=timeout) if model else FakeModelAdapter(['うん。']*(turns+10)))
        session = ChatSession(adapter, path)
        session.turn('INTERNET OVERDOSEという曲を聴いた。')
        original_session = session.fio.session_id
        session.close()
        session = ChatSession(adapter, path)
        for text in ('前に何話した？', '調子どう？', '前に曲の話したよな？', 'は？'):
            before = len(adapter.requests)
            previous = session.core.last_assistant
            started = time.monotonic()
            reply = session.turn(text)
            prompt = adapter.requests[before][0]['content'] if len(adapter.requests) > before else None
            context = json.loads(prompt.split('\nCPU_CONTEXT\n', 1)[1]) if prompt else None
            observations.append({'input': text, 'reply': reply, 'duration_seconds': round(time.monotonic()-started, 3),
                                 'context': context, 'provenance': session.core.provenance.last,
                                 'meta': session.last_response_meta, 'previous_assistant': previous})
            print(json.dumps({'input': text, 'reply': reply}, ensure_ascii=False), flush=True)
        checks['restart_recall_original_session'] = any(h['session_id'] == original_session for h in observations[0]['context']['session_recall'])
        greeting = observations[1]
        checks['greeting_no_recall'] = not greeting['context']['session_recall'] and not greeting['context']['salient_experiences']
        checks['greeting_no_old_song_in_context'] = 'INTERNET OVERDOSE' not in json.dumps(greeting['context'], ensure_ascii=False)
        checks['greeting_no_old_song_in_output'] = 'INTERNET OVERDOSE' not in greeting['reply']
        checks['explicit_correct_excerpt'] = any('INTERNET OVERDOSE' in e['user'] for h in observations[2]['context']['session_recall'] if h['session_id'] == original_session for e in h['exchanges'])
        checks['ambiguous_previous_priority'] = observations[3]['meta'].get('cpu') and observations[3]['provenance'].get('referent') == observations[3]['previous_assistant']
        if not model:
            # Exercise the complete ChatSession path, not just the sidecar API.
            for i in range(turns-5):
                session.turn('望遠鏡で星空を見た '+str(i))
                if i and i % 50 == 0:
                    session.close()
                    session = ChatSession(adapter, path)
            session.close()
            session = ChatSession(adapter, path)
            checks['durability_confirmed_count'] = len(session.fio.recorder.records) == turns
            checks['durability_replay_count'] = len(session.core.events.events) == 2*turns
            kinds = [r['kind'] for r in session.fio.experiences.all()]
            checks['durability_experience_count'] = kinds.count('turn') == turns
            checks['durability_response_policy_count'] = kinds.count('assistant_response') == turns
            checks['durability_reaction_chain_count'] = kinds.count('next_user_reaction') == turns - 1
            checks['durability_total_experience_count'] = len(kinds) == 3 * turns - 1
        config = HeatConfig(half_life_seconds=100)
        independent = FIOMemory(heat_config=config)
        independent.experiences.append(id='heat-probe', kind='correction', turn_id='probe', timestamp=0,
                                       source='user_statement', body={'user': '赤じゃなくて青'})
        heat = {'initial': independent.experiences.live_heat(independent.experiences.all()[0], 0),
                'after_half_life': independent.experiences.live_heat(independent.experiences.all()[0], 100)}
        independent.experiences.reinforce(['heat-probe'], now=100)
        heat['after_reinforce'] = independent.experiences.all()[0]['heat']
        checks['heat_decay_reinforce'] = heat == {'initial': 1, 'after_half_life': .5, 'after_reinforce': .75}
        independent.close()
        session.close()
    return {'at': datetime.now(timezone.utc).isoformat(), 'model': 'qwen2.5:14b' if model else 'scripted_plumbing',
            'scope': 'mechanical_memory_path_not_conversation_quality', 'training_examples': 0, 'model_labels': 0,
            'durability_turns': 0 if model else turns, 'checks': checks, 'heat': heat, 'turns': observations}


def main():
    configure_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument('--event-log', type=Path, default=ROOT/'data/events.jsonl')
    parser.add_argument('--rebuild-index', action='store_true')
    parser.add_argument('--query')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--model', action='store_true')
    parser.add_argument('--turns', type=int, default=500)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.smoke or args.model:
        if not 5 <= args.turns <= 500:
            parser.error('--turns must be in 5..500')
        result = probe(args.model, args.turns, args.timeout)
    else:
        # Require daemon/chat shutdown; diagnostics must not race a live writer.
        with LogLease(args.event_log):
            prefix = str(args.event_log)+'.fio'
            recorder = SessionRecorder(prefix+'.sessions.jsonl')
            if args.rebuild_index:
                # Recreate only the derived index. JSONL was fully validated first.
                index_path = Path(prefix+'.index.sqlite3')
                index_path.unlink(missing_ok=True)
                index = SessionIndex(index_path)
                index.rebuild(recorder.records)
            fio = FIOMemory(args.event_log)
            result = {'confirmed_turns': len(fio.recorder.records), 'sessions': len({r['session_id'] for r in fio.recorder.records}),
                      'experiences': len(fio.experiences.all()), 'index_rebuilt': args.rebuild_index,
                      'recall': fio.index.search(args.query, explicit=True) if args.query else []}
            fio.close()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'turns'}, ensure_ascii=False, indent=2))
    return int('checks' in result and not all(result['checks'].values()))


if __name__ == '__main__':
    raise SystemExit(main())
