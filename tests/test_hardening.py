"""Human-specified structural contracts, no teacher text or model judging."""
import copy
from dataclasses import asdict
from datetime import datetime
import io
import json
import os
from pathlib import Path
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from companion_core.chat import ChatSession
from companion_core.core import CompanionCore
from companion_core.cpu_answer import CPUAnswer
from companion_core.daemon import CompanionDaemon, DaemonClient
from companion_core.encoding import configure_stdio
from companion_core.event_store import EventStore
from companion_core.intent import IntentRouter
from companion_core.model_adapter import FakeModelAdapter, ModelError, OllamaAdapter
from companion_core.models import Event, Scope, SourceType, Status
from companion_core.prompt import PromptBuilder
from companion_core.style import StyleProfile, StyleValidator

FIXED = datetime.fromisoformat('2026-10-23T07:41:00+09:00')


def snapshot(core):
    return {'state': {k: v for k, v in core.state.snapshot().items() if v['source'] != 'runtime'},
            'memory': [asdict(x) for x in core.memory.items],
            'loops': [asdict(x) for x in core.open_loops.loops],
            'topics': [asdict(x) for x in core.topic.topics],
            'emotion': core.emotion.state.to_dict(), 'subjects': core.knowledge_subjects,
            'assistant': core.last_assistant, 'provenance': core.provenance.last}


class HardeningTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'events.jsonl'

    def session(self, replies=('わかった。',)):
        return ChatSession(FakeModelAdapter(replies), self.path)

    def test_casual_ignores_old_song_in_auxiliary_context_keeps_recent_raw(self):
        chat = self.session()
        chat.turn('LUMEN ARCという曲を聴いた')
        chat.turn('調子どう？')
        self.assertNotIn('LUMEN ARC', chat.adapter.requests[-1][0]['content'])
        self.assertIn('LUMEN ARCという曲を聴いた', [m['content'] for m in chat.adapter.requests[-1][1:-1]])
        self.assertFalse(chat.last_response_meta['unverified'])

    def test_ambiguous_prior_assistant_only(self):
        chat = self.session(('新しい返答', '確認するね'))
        chat.turn('LUMEN ARCという曲を聴いた')
        chat.turn('話を変える。机を片付けたい')
        for text in ('は？', '？？'):
            last = chat.core.last_assistant
            ctx = chat.core.handle(text)
            self.assertEqual(ctx['intent'], 'ambiguous_followup')
            self.assertEqual(ctx['previous_assistant'], last)
            self.assertIsNone(ctx['prompt_context']['topic'])
            self.assertEqual(ctx['prompt_context']['memory'], [])
            request = PromptBuilder().build(ctx, chat.core.events.events)
            self.assertNotIn('LUMEN ARC', request[0]['content'])
            self.assertIn('話を変える。机を片付けたい', [m['content'] for m in request[1:-1]])

    def test_internal_routes_never_call_knowledge_gate(self):
        chat = self.session()
        with patch.object(chat.core.knowledge, 'evaluate', side_effect=AssertionError('gate crossed')):
            for text in ('調子どう？', 'Breaktailの記憶に入ってる？', 'その情報どこから？', '今何時？', '？？', '赤じゃなくて青'):
                chat.turn(text)
                self.assertFalse(chat.last_response_meta['unverified'])

    def test_provenance_generated_is_never_fact_evidence(self):
        chat = self.session(('根拠なしのAIの主張',))
        chat.turn('こんにちは')
        provenance = chat.core.provenance.last
        generated = [s for s in provenance['sources'] if s['kind'] == 'assistant_generated']
        self.assertEqual(generated, [{'kind': 'assistant_generated', 'fact_evidence': False}])
        calls = len(chat.adapter.requests)
        self.assertIn('事実の根拠にならない', chat.turn('その情報どこから？'))
        self.assertEqual(calls, len(chat.adapter.requests))
        self.assertFalse(any('主張' in x.text for x in chat.core.memory.items))

    def test_provenance_persisted_across_restart(self):
        chat = self.session()
        chat.turn('こんにちは')
        last = copy.deepcopy(chat.core.provenance.last)
        restarted = self.session()
        self.assertEqual(last, restarted.core.provenance.last)
        self.assertIn('AI生成', restarted.turn('どこからその情報を？'))

    def test_old_log_missing_provenance_is_unknown(self):
        core = CompanionCore(self.path)
        core.record_assistant_output('以前の生成文')
        chat = self.session()
        self.assertIn('出所記録はない', chat.turn('その情報どこから？'))

    def test_all_provenance_categories(self):
        chat = self.session()
        chat.core.memory.add('LUMEN ARCは架空の楽曲。', SourceType.VERIFIED_MEMORY)
        chat.core.state.propose('probe', 'trusted', SourceType.SYSTEM)
        chat.turn('LUMEN ARC知ってる？')
        kinds = {s['kind'] for s in chat.core.provenance.last['sources']}
        self.assertEqual(kinds, {'memory', 'state', 'runtime', 'external', 'assistant_generated'})

    def test_same_event_id_does_not_mutate_state_twice(self):
        chat = self.session()
        chat.turn('あとで机を片付ける', event_id='request-1')
        before = snapshot(chat.core)
        count = len(chat.core.events.events)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            chat.turn('あとで机を片付ける', event_id='request-1')
        self.assertEqual(before, snapshot(chat.core))
        self.assertEqual(count, len(chat.core.events.events))
        with self.assertRaises(ValueError):
            self.session().turn('あとで机を片付ける', event_id='request-1')

    def test_repeated_text_is_distinct_user_turn_not_implicit_retry(self):
        chat = self.session()
        for _ in range(8):
            chat.turn('あとで机を片付ける')
        self.assertEqual(len(chat.core.events.events), 16)
        self.assertEqual(len(chat.core.open_loops.active()), 1)
        self.assertEqual(len(chat.core.memory.items), 1)
        self.assertFalse(any(x.source == SourceType.VERIFIED_MEMORY for x in chat.core.memory.items))

    def test_replay_exact_nonruntime_derived_metadata(self):
        chat = self.session()
        for text, key in [('あとで机を片付ける', None), ('赤じゃなくて青', 'color'), ('青じゃなくて緑', 'color'), ('記憶にある？', None), ('は？', None)]:
            chat.turn(text, correction_key=key)
        before = snapshot(chat.core)
        raw = self.path.read_bytes()
        for _ in range(3):
            chat.core.replay()
            self.assertEqual(snapshot(chat.core), before)
        self.assertEqual(snapshot(self.session().core), before)
        self.assertEqual(raw, self.path.read_bytes())

    def test_direct_source_gate_for_every_scope(self):
        core = CompanionCore()
        for scope in Scope:
            self.assertFalse(core.state.propose('probe', 'AI', SourceType.ASSISTANT_GENERATED, scope))
            with self.assertRaises(ValueError):
                core.state.correct('probe', 'AI', scope=scope, source=SourceType.ASSISTANT_GENERATED)
        self.assertFalse(core.memory.add('AI', SourceType.ASSISTANT_GENERATED))
        self.assertEqual(core.memory.items, [])

    def test_runtime_clock_cannot_be_overwritten_by_correction(self):
        core = CompanionCore()
        core.handle('こんにちは')
        before = core.state.active['time.year'].value
        core.handle('今年は1900', correction_key='time.year')
        with self.assertRaises(ValueError):
            core.state.correct('time.year', 1900)
        self.assertFalse(core.state.propose('time.year', 1900, SourceType.USER_STATEMENT))
        self.assertEqual(before, core.state.active['time.year'].value)

    def test_duplicate_append_and_collision(self):
        store = EventStore(self.path)
        e = Event('user_input', {'text': '入力'}, SourceType.USER_STATEMENT)
        self.assertTrue(store.append(e))
        before = self.path.read_bytes()
        self.assertFalse(store.append(e))
        e.payload['text'] = '変更'
        with self.assertRaises(ValueError):
            store.append(e)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(store.events[0].payload['text'], '入力')

    def test_duplicate_disk_record_fails(self):
        store = EventStore(self.path)
        store.append(Event('user_input', {'text': '入力'}, SourceType.USER_STATEMENT))
        raw = self.path.read_bytes()
        self.path.write_bytes(raw + raw)
        with self.assertRaisesRegex(ValueError, 'line 2'):
            EventStore(self.path)

    def test_same_size_tamper_detected(self):
        store = EventStore(self.path)
        store.append(Event('user_input', {'text': 'abc'}, SourceType.USER_STATEMENT))
        raw = self.path.read_bytes().replace(b'abc', b'xyz')
        self.path.write_bytes(raw)
        with self.assertRaises(OSError):
            store.append(Event('user_input', {'text': 'next'}, SourceType.USER_STATEMENT))
        self.assertEqual(raw, self.path.read_bytes())

    def test_fsync_failure_poisoned_writer(self):
        store = EventStore(self.path)
        e = Event('user_input', {'text': '入力'}, SourceType.USER_STATEMENT)
        with patch('companion_core.event_store.os.fsync', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                store.append(e)
        self.assertEqual(store.events, [])
        with self.assertRaisesRegex(OSError, 'writer stopped'):
            store.append(e)
        # Complete record may already be durable; restart determines it, never retry in place.
        self.assertEqual(len(EventStore(self.path).events), 1)

    def test_assistant_correction_event_source_cannot_mutate_replay(self):
        core = CompanionCore(self.path)
        core.events.append(Event('correction', {'key': 'probe', 'new': 'AI'}, SourceType.ASSISTANT_GENERATED))
        core.replay()
        self.assertNotIn('probe', core.state.active)
        self.assertEqual(core.memory.items, [])

    def test_cpu_path_skips_model_and_style_rewrite(self):
        chat = self.session(('今日は日曜日、残り99分',))
        with patch.object(chat.core.time, 'now', return_value=FIXED):
            self.assertEqual(chat.turn('今日は何曜日？'), '金曜日。')
            self.assertEqual(chat.turn('8時まであと何分？'), 'あと19分。')
        self.assertEqual(chat.adapter.requests, [])
        self.assertFalse(chat.core.provenance.last['generated'])

    def test_past_deadline_does_not_silently_wrap(self):
        facts = {'time.iso': '2026-10-23T09:00:00+09:00'}
        self.assertIn('過ぎている', CPUAnswer().answer('8時まであと何分？', facts))
        self.assertEqual(CPUAnswer().answer('明日の8時まであと何分？', facts), 'あと1380分。')

    def test_invalid_model_types_never_commit(self):
        for reply in (None, {}, [], 12, '', '  ', '\ud800'):
            with self.subTest(reply=repr(reply)):
                chat = ChatSession(FakeModelAdapter([reply]))
                with self.assertRaises(ModelError):
                    chat.turn('こんにちは')
                self.assertEqual([e.kind for e in chat.core.events.events], ['user_input'])

    def test_model_timeout_keeps_only_user(self):
        chat = self.session()
        with patch('companion_core.model_adapter.urlopen', side_effect=TimeoutError('slow')):
            chat.adapter = OllamaAdapter(timeout=.01)
            with self.assertRaises(ModelError):
                chat.turn('こんにちは')
        self.assertEqual([e.kind for e in chat.core.events.events], ['user_input'])

    def test_stdio_reconfigure_cp932(self):
        streams = [io.TextIOWrapper(io.BytesIO(), encoding='cp932') for _ in range(3)]
        with patch.multiple('sys', stdin=streams[0], stdout=streams[1], stderr=streams[2]):
            configure_stdio()
        for stream in streams:
            self.assertEqual(stream.encoding, 'utf-8')
            self.assertEqual(stream.errors, 'replace')
            stream.close()

    def test_cp932_environment_cli_chat_demo_daemon(self):
        env = {**os.environ, 'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp932'}
        text = '日本語😀！！！ABC123\n/exit\n'
        p = subprocess.run([sys.executable, str(ROOT/'chat.py'), '--fake', '--event-log', str(self.path)], input=text.encode(), capture_output=True, env=env, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr.decode('utf-8'))
        self.assertEqual(EventStore(self.path).events[0].payload['text'], text.splitlines()[0])
        p.stdout.decode('utf-8')
        for name in ('demo.py', 'daemon.py'):
            result = subprocess.run([sys.executable, str(ROOT/name), *(['--help'] if name=='daemon.py' else [])], capture_output=True, env=env, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))
            result.stdout.decode('utf-8')

    def test_empty_long_and_invalid_input_no_commit(self):
        chat = self.session()
        core = chat.core
        for text in ('', ' ', '\n', 'a'*16001, None, 123):
            with self.assertRaises(ValueError):
                chat.turn(text)
        self.assertEqual(core.events.events, [])
        core.handle('日本語\ud800😀\ufffd')
        self.assertEqual(core.events.events[0].payload['text'], '日本語?😀\ufffd')

    def test_style_prevents_boilerplate_recurrence(self):
        for text in ('何か手伝える？', '応援してる', '詳しく教えて'):
            self.assertIn('assistantese', StyleValidator().violations(text, {'profile': vars(StyleProfile()), 'max_chars': 320}))
        request = PromptBuilder().build(CompanionCore().handle('調子どう？'), [])
        self.assertIn('毎回質問で締めない', request[0]['content'])

    def test_unknown_generic_external_fail_closed(self):
        chat = self.session(('勝手な答え',))
        self.assertIn('未確認', chat.turn('作者は誰？'))
        self.assertEqual(chat.adapter.requests, [])

    def test_unnamed_external_question_fails_closed(self):
        chat = self.session(('未確認の断定',))
        for text in ('地球は丸い？', '水は何度で沸騰する？', '電力はどこから来る？'):
            self.assertEqual(chat.core.router.route(text), 'external_knowledge')
            self.assertIn('未確認', chat.turn(text))
        self.assertEqual(chat.adapter.requests, [])

    def test_unnamed_external_question_accepts_matching_trusted_evidence(self):
        chat = self.session(('資料では地球はほぼ球形。',))
        chat.core.memory.add('地球はほぼ球形で丸い。', SourceType.VERIFIED_MEMORY)
        self.assertEqual(chat.turn('地球は丸い？'), '資料では地球はほぼ球形。')
        self.assertFalse(chat.last_response_meta['unverified'])
        self.assertEqual(len(chat.adapter.requests), 1)

    def test_generic_memory_cpu_source_qualified_and_never_personal_experience(self):
        chat = self.session()
        chat.core.handle('LUMEN ARCという曲を聴いた')
        with patch.object(chat.adapter, 'generate', side_effect=AssertionError('model called')):
            reply = chat.turn('Breaktailの記憶に入ってる？')
        self.assertIn('ユーザー申告', reply)
        self.assertIn('LUMEN ARC', reply)
        self.assertIn('確認済み根拠ではない', reply)
        self.assertFalse(chat.core.provenance.last['generated'])
        self.assertEqual([s['kind'] for s in chat.core.provenance.last['sources']], ['memory'])

    def test_generic_memory_does_not_count_current_question(self):
        chat = self.session()
        self.assertIn('まだ見つからない', chat.turn('記憶にある？'))
        self.assertEqual(chat.adapter.requests, [])

    def test_duplicate_append_race_does_not_reapply_core(self):
        core = CompanionCore()
        with patch.object(core.events, 'append', return_value=False):
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                core.handle('あとで机を片付ける', event_id='concurrent-event')
        self.assertEqual(core.memory.items, [])
        self.assertEqual(core.open_loops.loops, [])
        self.assertEqual(core.state.active, {})

    def test_one_command_launcher_ready_then_chat(self):
        import re
        import signal
        result = subprocess.run([sys.executable, str(ROOT/'scripts/start.py'), '--fake', '--event-log', str(self.path)],
                                input='/status\n/exit\n'.encode(), capture_output=True, timeout=30)
        output = result.stdout.decode('utf-8')
        match = re.search(r'daemon PID=(\d+)', output)
        try:
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))
            self.assertIsNotNone(match, output)
            self.assertIn('daemon接続', output)
            self.assertTrue(DaemonClient(self.path).status()['last_pc_observation'])
        finally:
            if match:
                os.kill(int(match[1]), signal.SIGTERM)
                # Wait for the process's OS lease to be released before temporary cleanup.
                from companion_core.ownership import LogLease
                deadline = time.monotonic()+5
                while True:
                    try:
                        lease = LogLease(self.path).acquire()
                        lease.close()
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(.05)

    def test_log_duplicate_key_and_unknown_kind(self):
        for raw in (b'{"id":"a","id":"b","kind":"user_input","payload":{"text":"x"},"source":"user_statement","ts":1}\n',
                    b'{"id":"a","kind":"invented","payload":{},"source":"system","ts":1}\n'):
            self.path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'line 1'):
                EventStore(self.path)
            self.assertEqual(raw, self.path.read_bytes())

    def test_middle_log_corruption_preserved_with_line_number(self):
        store = EventStore(self.path)
        for text in ('a', 'b', 'c'):
            store.append(Event('user_input', {'text': text}, SourceType.USER_STATEMENT))
        lines = self.path.read_bytes().splitlines(keepends=True)
        lines[1] = b'{broken}\n'
        raw = b''.join(lines)
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'line 2'):
            EventStore(self.path)
        self.assertEqual(raw, self.path.read_bytes())

    def test_ambiguous_cpu_path_never_calls_model(self):
        chat = self.session(('直前の返答',))
        chat.turn('こんにちは')
        with patch.object(chat.adapter, 'generate', side_effect=AssertionError('model called')):
            for text in ('は？', '？？'):
                self.assertIn('直前の返答', chat.turn(text))
                self.assertEqual(chat.core.provenance.last['sources'][0]['fact_evidence'], False)

    def test_fuzz_500_turns_and_restart(self):
        rng = random.Random(20261023)
        atoms = ['あ', 'a', '😀', '？', '！', '\ufffd', '\ud800', ' ', '9', '終わった', 'あとでやる']
        chat = self.session()
        with patch.object(chat.core.time, 'now', return_value=FIXED):
            for i in range(500):
                text = ''.join(rng.choice(atoms) for _ in range(rng.randint(1, 25))).strip() or '！'
                chat.turn(text)
                self.assertTrue(all(f.source != SourceType.ASSISTANT_GENERATED for f in chat.core.state.active.values()))
                self.assertTrue(all(m.source not in {SourceType.ASSISTANT_GENERATED, SourceType.VERIFIED_MEMORY} for m in chat.core.memory.items))
                self.assertTrue(all(sum(f.status == Status.ACTIVE for f in facts) == 1 for facts in chat.core.state.history.values()))
            before = snapshot(chat.core)
            self.assertEqual(before, snapshot(self.session().core))
        self.assertEqual(len(chat.core.events.events), 1000)

    def test_disconnected_chat_does_not_reexecute_turn(self):
        entered, release = threading.Event(), threading.Event()
        class Blocking:
            def generate(self, messages):
                entered.set()
                if not release.wait(5):
                    raise ModelError('test timed out')
                return '返答'
        daemon = CompanionDaemon(Blocking(), self.path)
        self.addCleanup(daemon.close)
        daemon.start()
        worker_errors = []
        def request():
            try:
                DaemonClient(self.path, timeout=.1).turn('こんにちは')
            except OSError:
                worker_errors.append('disconnected')
        worker = threading.Thread(target=request)
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            worker.join(2)
            self.assertEqual(worker_errors, ['disconnected'])
        finally:
            release.set()
            worker.join(3)
        # Acquiring the turn lock waits for the server to finish the original request.
        with daemon.turn_lock:
            kinds = [e.kind for e in daemon.session.core.events.events if e.kind != 'runtime_observation']
            self.assertEqual(kinds, ['user_input', 'assistant_output'])


# Independent fixed contracts are separate unittest cases so diagnostic reports name each boundary.
ROUTES = [
 ('casual', '調子どう？', 'casual_chat'), ('greeting', 'こんにちは', 'casual_chat'),
 ('memory', 'Breaktailの記憶に入ってる？', 'self_state_memory'), ('source', 'その情報どこから？', 'self_state_memory'),
 ('source2', 'どこからその情報を？', 'self_state_memory'), ('remember', '記憶にある？', 'self_state_memory'),
 ('followup', 'は？', 'ambiguous_followup'), ('marks', '？？', 'ambiguous_followup'),
 ('time', '今何時？', 'time_calculation'), ('weekday', '今日は何曜日？', 'time_calculation'),
 ('deadline', '8時まであと何分？', 'time_calculation'), ('arithmetic', '2+3*4は？', 'time_calculation'),
 ('external', 'LUMEN ARC知ってる？', 'external_knowledge'), ('facet', 'その作者は誰？', 'external_knowledge'),
 ('correction', '赤じゃなくて青', 'task_correction'), ('date', '今日の日付は？', 'time_calculation')]
for name, text, expected in ROUTES:
    def test(self, text=text, expected=expected):
        self.assertEqual(IntentRouter().route(text), expected)
    setattr(HardeningTests, 'test_route_'+name, test)

CPU_CASES = [
 ('difference', '7:41→8:00', '19分。'), ('midnight', '23:50→0:10', '20分。'),
 ('weekday', '今日は何曜日？', '金曜日。'), ('date', '今日の日付は？', '2026年10月23日。'),
 ('clock', '今何時？', '07:41:00（Asia/Tokyo）。'), ('remaining', '8時まであと何分？', 'あと19分。'),
 ('add', '2+3は？', '5。'), ('order', '2+3*4', '14。'), ('decimal', '0.1+0.2', '0.3。'),
 ('negative', '-5+2', '-3。'), ('parentheses', '(2+3)*4', '20。'), ('divide', '10/4', '2.5。'),
 ('zero', '4-4', '0。'), ('fullwidth', '２＋３', '5。')]
for name, text, expected in CPU_CASES:
    def test(self, text=text, expected=expected):
        self.assertEqual(CPUAnswer().answer(text, {'time.iso': FIXED.isoformat()}), expected)
    setattr(HardeningTests, 'test_cpu_'+name, test)

BAD_LOGS = [('partial_json', b'{"id":'), ('no_delimiter', json.dumps(Event('user_input', {'text':'x'}, SourceType.USER_STATEMENT).to_dict()).encode()),
            ('bad_unicode', b'\xff\n'), ('empty', b'\n'), ('schema', b'{}\n'), ('nonobject', b'[]\n'),
            ('nan', b'{"id":"x","kind":"user_input","payload":{"text":"x"},"source":"user_statement","ts":NaN}\n')]
for name, raw in BAD_LOGS:
    def test(self, raw=raw):
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'line 1'):
            EventStore(self.path)
        self.assertEqual(raw, self.path.read_bytes())
    setattr(HardeningTests, 'test_corrupt_'+name, test)

for name, expression in [('zero_division','1/0'), ('power','2**999999'), ('import', '__import__("os")'), ('nested', '('*200+'1'+')'*200), ('huge', '9'*150+'*9'), ('invalid_time','25:00→8:00')]:
    def test(self, expression=expression):
        self.assertIn('CPUで確定できない', CPUAnswer().answer(expression, {'time.iso': FIXED.isoformat()}))
    setattr(HardeningTests, 'test_cpu_reject_'+name, test)

if __name__ == '__main__':
    unittest.main()
