"""Mechanical contracts; fixtures are probes, not model labels or training examples."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from companion_core.chat import ChatSession
from companion_core.core import CompanionCore
from companion_core.daemon import CompanionDaemon
from companion_core.experience import ExperienceStore, HeatConfig
from companion_core.fio_memory import FIOMemory
from companion_core.intent import IntentRouter
from companion_core.model_adapter import FakeModelAdapter, ModelError
from companion_core.models import SourceType
from companion_core.session_memory import SessionIndex, SessionRecorder, grams, normalize


def record(tid='t1', sid='s1', user='昨日の曲の話', assistant='聞いていたね', ts=100):
    return dict(turn_id=tid, session_id=sid, user=user, assistant=assistant,
                timestamp=ts, status='confirmed', provenance={'fact_evidence': False})


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'sessions.jsonl'
        self.store = SessionRecorder(self.path)

    def test_append_verbatim(self):
        row = record(user='  日本語\n🎵  ', assistant='「応答」\n二行')
        self.store.append(row)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), row)

    def test_duplicate(self):
        row = record()
        self.assertTrue(self.store.append(row))
        self.assertFalse(self.store.append(row))
        self.assertEqual(len(self.path.read_bytes().splitlines()), 1)

    def test_duplicate_conflict(self):
        self.store.append(record())
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.store.append(record(user='different'))

    def test_restart_append(self):
        self.store.append(record())
        restarted = SessionRecorder(self.path)
        restarted.append(record('t2'))
        self.assertEqual([r['turn_id'] for r in SessionRecorder(self.path).records], ['t1', 't2'])

    def test_restart_duplicate(self):
        self.store.append(record())
        self.assertFalse(SessionRecorder(self.path).append(record()))

    def test_incomplete_tail_rejected_preserved(self):
        self.store.append(record())
        with self.path.open('ab') as stream:
            stream.write(b'{"session_id":')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'line 2'):
            SessionRecorder(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_valid_json_without_newline_rejected(self):
        self.path.write_text(json.dumps(record()), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'line 1'):
            SessionRecorder(self.path)

    def test_middle_corruption_rejected(self):
        self.path.write_bytes(b'broken\n' + (json.dumps(record())+'\n').encode())
        with self.assertRaisesRegex(ValueError, 'line 1'):
            SessionRecorder(self.path)

    def test_invalid_utf8(self):
        self.path.write_bytes(b'\xff\n')
        with self.assertRaises(ValueError):
            SessionRecorder(self.path)

    def test_duplicate_json_keys(self):
        self.path.write_text('{"turn_id":"a","turn_id":"b"}\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            SessionRecorder(self.path)

    def test_failed_status_rejected(self):
        with self.assertRaises(ValueError):
            self.store.append({**record(), 'status': 'failed'})

    def test_external_writer_rejected(self):
        other = SessionRecorder(self.path)
        self.store.append(record())
        with self.assertRaises(OSError):
            other.append(record('t2'))

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            self.store.append({**record(), 'timestamp': float('nan')})

    def test_copy_isolated(self):
        row = record()
        self.store.append(row)
        row['provenance']['fact_evidence'] = True
        self.assertFalse(self.store.records[0]['provenance']['fact_evidence'])


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.index = SessionIndex()
        self.addCleanup(self.index.close)

    def load(self, rows):
        self.index.rebuild(rows)

    def test_normalization(self):
        self.assertEqual(normalize('ＡＢＣ　カタカナ！'), 'abcカタカナ')

    def test_bigram_trigram(self):
        self.assertEqual(grams('日本語'), {'日本', '本語', '日本語'})

    def test_exact_japanese(self):
        self.load([record(user='昨日は東京都美術館へ行った')])
        hits = self.index.search('東京都美術館')
        self.assertEqual(hits[0]['hit_turn_id'], 't1')

    def test_two_stage_session_ranking(self):
        self.load([record('weak', 's1', '曲がある'), record('strong', 's2', '星空の曲を聴いた')])
        self.assertEqual(self.index.search('星空の曲')[0]['session_id'], 's2')

    def test_window_ranking(self):
        self.load([record('a', user='パンを焼く'), record('b', user='天体観測をする'), record('c', user='買い物に行く')])
        hit = self.index.search('天体観測')[0]
        self.assertEqual(hit['hit_turn_id'], 'b')
        self.assertEqual({e['turn_id'] for e in hit['exchanges']}, {'a', 'b', 'c'})

    def test_user_greater_than_assistant(self):
        self.load([record('ai', 's1', '別の話', '望遠鏡を作る'), record('human', 's2', '望遠鏡を作る', 'そうだね')])
        self.assertEqual(self.index.search('望遠鏡')[0]['hit_turn_id'], 'human')

    def test_recency_tie(self):
        self.load([record('old', 's1', '望遠鏡', ts=1), record('new', 's2', '望遠鏡', ts=90000)])
        self.assertEqual(self.index.search('望遠鏡', now=90000)[0]['hit_turn_id'], 'new')

    def test_no_recency_without_relevance(self):
        self.load([record('old', 's1', '望遠鏡', ts=1), record('new', 's2', '焼きたてパン', ts=90000)])
        self.assertEqual({h['session_id'] for h in self.index.search('望遠鏡', now=90000)}, {'s1'})

    def test_diversity_and_default_caps(self):
        self.load([record(str(i), 's'+str(i//5), '望遠鏡を作る', ts=i) for i in range(20)])
        hits = self.index.search('望遠鏡')
        self.assertEqual(len({h['session_id'] for h in hits}), 2)
        self.assertLessEqual(len(hits), 4)

    def test_explicit_wider(self):
        self.load([record(str(i), str(i), '望遠鏡', ts=i) for i in range(6)])
        self.assertEqual(len(self.index.search('前に望遠鏡の話したよな？', explicit=True)), 4)

    def test_long_turns_keep_session_diversity(self):
        self.load([record(str(i), str(i), '望遠鏡'*500, '星空'*500) for i in range(4)])
        self.assertEqual(len({h['session_id'] for h in self.index.search('望遠鏡')}), 2)

    def test_query_does_not_strip_substantive_kana(self):
        self.load([record(user='はやぶさの打ち上げ')])
        hit = self.index.search('前にはやぶさの話したよな？', explicit=True)
        self.assertEqual(hit[0]['hit_turn_id'], 't1')

    def test_generic_recall_recent(self):
        self.load([record('a', 'a', ts=1), record('b', 'b', ts=2)])
        self.assertEqual(self.index.search('前に何話した？', explicit=True)[0]['hit_turn_id'], 'b')

    def test_no_unrelated(self):
        self.load([record(user='INTERNET OVERDOSEを聴いた')])
        self.assertEqual(self.index.search('今日の夕飯'), [])

    def test_no_query_injection(self):
        self.load([record()])
        self.assertEqual(self.index.search('" OR * )'), [])

    def test_empty_and_limits(self):
        self.load([record()])
        self.assertEqual(self.index.search(''), [])
        self.assertEqual(self.index.search('曲', max_sessions=0), [])

    def test_char_budget(self):
        self.load([record(user='望遠鏡'*2000, assistant='a'*5000)])
        hits = self.index.search('望遠鏡', char_budget=300)
        self.assertLessEqual(sum(len(e['user'])+len(e['assistant']) for h in hits for e in h['exchanges']), 300)

    def test_long_user_turn_is_omitted_not_quoted_with_lost_negation(self):
        from companion_core.provenance import ProvenanceResponder
        user = '背景。' * 230 + '今私は大会に参加したわけではない。'
        self.load([record(user=user)])
        hit = self.index.search('大会について覚えてる？', explicit=True)[0]
        item = hit['exchanges'][0]
        self.assertFalse(item['user_complete'])
        self.assertEqual(item['user'], '')
        p = ProvenanceResponder()
        p.last = {'generated': True, 'sources': [{'kind': 'session_recall', 'items': [hit]}]}
        self.assertNotIn('私は大会に参加した', p.answer())
        self.assertIn('原文全体を確認できない', p.answer())

    def test_legacy_excerpt_without_completeness_marker_is_not_quoted(self):
        from companion_core.provenance import ProvenanceResponder
        p = ProvenanceResponder()
        p.last = {'generated': False, 'sources': [{'kind': 'session_recall', 'items': [
            {'exchanges': [{'turn_id': 'old', 'user_source': 'user_statement', 'user': '参加した'}]}]}]}
        self.assertNotIn('「参加した」', p.answer())

    def test_source_and_hash(self):
        row = record(user='望遠鏡')
        self.load([row])
        quote = self.index.search('望遠鏡')[0]['exchanges'][0]
        self.assertFalse(quote['verified'])
        self.assertEqual(quote['assistant_source'], 'assistant_generated')
        self.assertEqual(quote['sha256'], hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest())

    def test_window_no_cross_session(self):
        self.load([record('a', 's1', '望遠鏡'), record('b', 's2', '夕飯')])
        self.assertEqual(len(self.index.search('望遠鏡')[0]['exchanges']), 1)

    def test_restart_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'index.db'
            idx = SessionIndex(path)
            idx.rebuild([record(user='望遠鏡')])
            idx = SessionIndex(path)
            idx.rebuild([record(user='望遠鏡')])
            self.assertEqual(len(idx.search('望遠鏡')), 1)


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.store = ExperienceStore(config=HeatConfig(half_life_seconds=100))
        self.addCleanup(self.store.close)

    def add(self, id='e1', ts=0, kind='correction', body=None, source='user_statement'):
        return self.store.append(id=id, kind=kind, turn_id='t', timestamp=ts, source=source, body=body or {'user': '望遠鏡は赤じゃなくて青'})

    def test_decay_half_life(self):
        self.add()
        self.assertAlmostEqual(self.store.live_heat(self.store.all()[0], 100), .5)

    def test_reinforce_cools_then_adds(self):
        self.add()
        self.store.reinforce(['e1'], now=100)
        row = self.store.all()[0]
        self.assertAlmostEqual(row['heat'], .75)
        self.assertEqual(row['references_count'], 1)

    def test_reinforce_cap(self):
        self.add()
        for _ in range(40):
            self.store.reinforce(['e1'], now=0)
        self.assertEqual(self.store.all()[0]['heat'], 4)

    def test_clock_rollback(self):
        self.add(ts=100)
        self.store.reinforce(['e1'], now=0)
        self.assertEqual(self.store.all()[0]['heated_at'], 100)

    def test_relevance_and_order(self):
        self.add('old', 0)
        self.add('new', 100)
        self.add('irrelevant', 100, body={'user': 'パンを焼いた'})
        self.assertEqual([x['id'] for x in self.store.salient('望遠鏡', now=100)], ['new', 'old'])

    def test_body_immutable_on_reinforce(self):
        self.add()
        raw = self.store.all()[0]['body']
        self.store.salient('望遠鏡', now=0, reinforce=True)
        self.assertEqual(self.store.all()[0]['body'], raw)

    def test_no_ai_prose_match(self):
        self.add(body={'assistant': '望遠鏡が真実'}, source='assistant_generated')
        self.assertEqual(self.store.salient('望遠鏡', now=0), [])

    def test_no_truth_promotion(self):
        self.add()
        item = self.store.salient('望遠鏡', now=0)[0]
        self.assertFalse(item['verified'])
        self.assertFalse(item['fact_evidence'])

    def test_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'experience.db'
            store = ExperienceStore(path)
            store.append(id='a', kind='model_failure', turn_id='t', timestamp=10, source='runtime', body={'user': '望遠鏡'})
            store.reinforce(['a'], now=10)
            self.assertEqual(ExperienceStore(path).all()[0]['references_count'], 1)

    def test_duplicate_preserves_reinforcement(self):
        self.add()
        self.store.reinforce(['e1'], now=0)
        self.assertFalse(self.add())
        self.assertEqual(self.store.all()[0]['references_count'], 1)

    def test_conflicting_id(self):
        self.add()
        with self.assertRaises(ValueError):
            self.add(body={'user': '違う'})

    def test_invalid_config(self):
        for value in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                HeatConfig(half_life_seconds=value)

    def test_turn_not_injected(self):
        self.add(kind='turn')
        self.assertEqual(self.store.salient('望遠鏡', now=0), [])

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            self.add(kind='verified')


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'events.jsonl'
        self.chat = ChatSession(FakeModelAdapter(['うん。']*10), self.path)

    def prompt(self):
        return self.chat.adapter.requests[-1][0]['content']

    def test_confirmed_turn(self):
        self.chat.turn('  曲を聴いた🎵\n二行目  ', event_id='id1')
        row = self.chat.fio.recorder.records[0]
        self.assertEqual(row['turn_id'], 'id1')
        self.assertEqual(row['user'], '  曲を聴いた🎵\n二行目  ')
        self.assertEqual(row['assistant'], 'うん。')

    def test_model_failure_not_confirmed(self):
        with patch.object(self.chat.adapter, 'generate', side_effect=ModelError('failed')):
            with self.assertRaises(ModelError):
                self.chat.turn('望遠鏡')
        self.assertEqual(self.chat.fio.recorder.records, [])
        self.assertEqual(self.chat.fio.experiences.all()[0]['kind'], 'model_failure')
        self.assertEqual(len(self.chat.core.events.events), 1)

    def test_greeting_no_old_song(self):
        self.chat.turn('INTERNET OVERDOSEという曲を聴いた')
        self.chat.turn('調子どう？')
        self.assertNotIn('INTERNET OVERDOSE', self.prompt())
        self.assertIn('"session_recall": []', self.prompt())

    def test_restart_explicit_recall(self):
        self.chat.turn('INTERNET OVERDOSEという曲を聴いた')
        sid = self.chat.fio.session_id
        self.chat = ChatSession(FakeModelAdapter(['うん。']), self.path)
        self.chat.turn('前に曲の話したよな？')
        self.assertIn('INTERNET OVERDOSE', self.prompt())
        self.assertIn(sid, self.prompt())
        self.assertNotEqual(sid, self.chat.fio.session_id)

    def test_generic_restart_recall(self):
        self.chat.turn('星空を見た')
        self.chat = ChatSession(FakeModelAdapter(['うん。']), self.path)
        self.chat.turn('前に何話した？')
        self.assertIn('星空を見た', self.prompt())

    def test_ambiguous_previous_assistant(self):
        self.chat.turn('INTERNET OVERDOSEという曲を聴いた')
        ctx = self.chat.core.handle('は？')
        messages = self.chat.prepare_reply(ctx, self.chat.core.events.events)
        self.assertEqual(ctx['previous_assistant'], 'うん。')
        self.assertEqual(ctx['session_recall'], [])
        self.assertNotIn('INTERNET OVERDOSE', messages[0]['content'])

    def test_explicit_route(self):
        for text in ('前に曲の話したよな？', '前に何話した？', 'この前の会話を思い出して'):
            self.assertEqual(IntentRouter().route(text), 'self_state_memory')

    def test_no_assistant_state_memory_promotion(self):
        self.chat.adapter = FakeModelAdapter(['あなたは医者だ。'])
        self.chat.turn('星空を見た')
        self.chat.core.replay()
        self.assertFalse(any('医者' in m.text for m in self.chat.core.memory.items))
        self.assertFalse(any('医者' in str(f.value) for f in self.chat.core.state.active.values()))

    def test_recall_provenance(self):
        self.chat.turn('星空を見た')
        self.chat.turn('前に星空の話したよな？')
        self.assertIn('session_recall', [s['kind'] for s in self.chat.core.provenance.last['sources']])

    def test_correction_experience(self):
        self.chat.turn('赤じゃなくて青', correction_key='favorite.color')
        self.assertIn('correction', [r['kind'] for r in self.chat.fio.experiences.all()])
        self.assertEqual(self.chat.core.state.active['favorite.color'].value, '青')

    def test_task_completion_experience(self):
        self.chat.turn('あとで机を片付ける')
        self.chat.turn('終わった')
        self.assertIn('task_completion', [r['kind'] for r in self.chat.fio.experiences.all()])

    def test_current_experience_not_self_recalled(self):
        self.chat.turn('赤じゃなくて青', correction_key='favorite.color')
        self.assertIn('"salient_experiences": []', self.prompt())

    def test_correction_survives_model_failure(self):
        with patch.object(self.chat.adapter, 'generate', side_effect=ModelError('failed')):
            with self.assertRaises(ModelError):
                self.chat.turn('赤じゃなくて青', correction_key='favorite.color')
        kinds = {r['kind'] for r in self.chat.fio.experiences.all()}
        self.assertEqual(kinds, {'correction', 'model_failure'})
        self.assertEqual(self.chat.fio.recorder.records, [])

    def test_related_experience_reinforced_only_after_confirmation(self):
        self.chat.turn('赤じゃなくて青', correction_key='favorite.color')
        self.chat.turn('赤じゃなくて青', correction_key='favorite.color')
        rows = [r for r in self.chat.fio.experiences.all() if r['kind'] == 'correction']
        self.assertEqual([r['references_count'] for r in rows], [1, 0])

    def test_failed_response_does_not_reinforce(self):
        self.chat.turn('赤じゃなくて青', correction_key='favorite.color')
        with patch.object(self.chat.adapter, 'generate', side_effect=ModelError('failed')):
            with self.assertRaises(ModelError):
                self.chat.turn('赤じゃなくて青', correction_key='favorite.color')
        self.assertTrue(all(r['references_count'] == 0 for r in self.chat.fio.experiences.all()))

    def test_retrieval_success_no_external_body_promotion(self):
        from companion_core.retrieval import ExternalEvidence, RetrievalResult
        import time
        evidence = ExternalEvidence.create('UNKNOWN ARC', 'UNKNOWN ARC', 'https://example.com/article', 'UNIQUE_EXTERNAL_SNIPPET', now=time.time(), score=1)
        with patch.object(self.chat.retrieval, 'retrieve', return_value=RetrievalResult('ok', (evidence,))):
            self.chat.turn('UNKNOWN ARCとは何？')
        rows = self.chat.fio.experiences.all()
        self.assertIn('retrieval_success', [r['kind'] for r in rows])
        self.assertNotIn('UNIQUE_EXTERNAL_SNIPPET', str(rows))
        self.assertFalse(any('UNIQUE_EXTERNAL_SNIPPET' in m.text for m in self.chat.core.memory.items))
        self.assertNotIn('UNIQUE_EXTERNAL_SNIPPET', self.chat.fio.recorder.path.read_text(encoding='utf-8'))

    def test_daemon_model_failure_not_confirmed(self):
        daemon = CompanionDaemon(FakeModelAdapter(['うん。']), self.path)
        try:
            with patch.object(daemon.session.adapter, 'generate', side_effect=ModelError('failed')):
                with self.assertRaises(ModelError):
                    daemon.turn('望遠鏡')
            self.assertEqual(daemon.session.fio.recorder.records, [])
            self.assertEqual(daemon.session.fio.experiences.all()[0]['kind'], 'model_failure')
        finally:
            daemon.close()

    def test_retrieval_failure_experience(self):
        self.chat.turn('UNKNOWN ARCとは何？')
        rows = self.chat.fio.experiences.all()
        self.assertIn('retrieval_failure', [r['kind'] for r in rows])

    def test_outbox_recovery_idempotent(self):
        with patch.object(self.chat.fio, 'commit', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.chat.turn('星空を見た')
        self.chat = ChatSession(FakeModelAdapter(), self.path)
        self.assertEqual(len(self.chat.fio.recorder.records), 1)
        before = self.chat.fio.experiences.all()
        self.chat.fio.recover(self.chat.core.events.events)
        self.assertEqual(self.chat.fio.experiences.all(), before)

    def test_independent_sidecar_restore(self):
        self.chat.turn('星空を見た')
        fio = FIOMemory(self.path)
        self.assertEqual(len(fio.recorder.records), 1)
        self.assertEqual([r['kind'] for r in fio.experiences.all()].count('turn'), 1)
        self.assertEqual({r['kind'] for r in fio.experiences.all()}, {'turn', 'assistant_response'})
        self.assertEqual(len(fio.experiences.all()), 2)

    def test_replay_no_sidecar_mutation(self):
        self.chat.turn('星空を見た')
        before = self.chat.fio.recorder.path.read_bytes()
        rows = self.chat.fio.experiences.all()
        self.chat.core.replay()
        self.assertEqual(self.chat.fio.recorder.path.read_bytes(), before)
        self.assertEqual(self.chat.fio.experiences.all(), rows)

    def test_daemon_chat_consistency(self):
        daemon = CompanionDaemon(FakeModelAdapter(['うん。']), self.path)
        try:
            daemon.turn('星空を見た', event_id='daemon1')
            self.assertEqual(daemon.session.fio.recorder.records[0]['turn_id'], 'daemon1')
            self.assertEqual(daemon.session.fio.recorder.records[0]['status'], 'confirmed')
        finally:
            daemon.close()

    def test_500_turn_restart_durability(self):
        # Avoid NLP throughput dominating this storage/recovery contract.
        fio = self.chat.fio
        for i in range(500):
            envelope = {'session': record(str(i), 's'+str(i//50), '星空'+str(i)), 'experiences': []}
            fio.commit(envelope)
        restarted = FIOMemory(self.path)
        self.assertEqual(len(restarted.recorder.records), 500)
        self.assertTrue(restarted.index.search('星空499'))
