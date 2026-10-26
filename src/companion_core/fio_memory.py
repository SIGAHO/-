"""Shared chat/daemon writeback and bounded auxiliary context. No State/Memory writes."""
import uuid
from pathlib import Path

from .experience import ExperienceStore
from .session_memory import EXPLICIT_RECALL, SessionRecorder, SessionIndex


class FIOMemory:
    def __init__(self, event_path=None, *, heat_config=None):
        self.session_id = str(uuid.uuid4())
        prefix = str(Path(event_path)) + '.fio' if event_path else None
        self.recorder = SessionRecorder(prefix + '.sessions.jsonl' if prefix else None)
        self.index = SessionIndex(prefix + '.index.sqlite3' if prefix else None)
        self.index.rebuild(self.recorder.records)
        self.experiences = ExperienceStore(prefix + '.experiences.sqlite3' if prefix else None, config=heat_config)
        self.pending = None

    def recover(self, events):
        # Commit envelopes are an outbox for crashes after EventStore fsync and
        # before sidecar writeback. Replay itself never writes these stores.
        for event in events:
            if event.kind == 'assistant_output' and event.payload.get('fio_commit'):
                self.commit(event.payload['fio_commit'])

    def begin(self, core, context):
        user = next(e for e in reversed(core.events.events) if e.kind == 'user_input')
        self.pending = {'user': user, 'context': context}
        context['session_recall'] = []
        context['salient_experiences'] = []
        explicit = bool(EXPLICIT_RECALL.search(context['user_input']))
        # Exact greetings and ambiguous followups never reopen historical topics.
        if context['intent'] not in {'ambiguous_followup', 'continuation'} and not core.router.casual.fullmatch(context['user_input'].replace('？', '?')):
            if explicit:
                context['session_recall'] = self.index.search(context['user_input'], explicit=True)
            elif context['intent'] == 'task_correction':
                context['session_recall'] = self.index.search(context['user_input'])
            if context['intent'] == 'task_correction' or explicit:
                context['salient_experiences'] = self.experiences.salient(context['user_input'])
            elif context['intent'] == 'external_knowledge':
                context['salient_experiences'] = self.experiences.salient(context['user_input'], kinds={'retrieval_failure', 'model_failure'})
        # Read before write so the current observation cannot recall itself.
        for event in self.observed_events():
            self.experiences.append(**event)

    def observed_events(self):
        context = self.pending['context']
        events = []
        if context['intent'] == 'task_correction':
            events.append(self.event('correction', {'user': context['user_input']}, 'user_statement'))
        for loop_id in context.get('completed_loop_ids', []):
            events.append(self.event('task_completion', {'user': context['user_input'], 'loop_id': loop_id}, 'user_statement', suffix=loop_id))
        result = context.get('external_retrieval', {}).get('status')
        if result and result != 'bypass':
            kind = 'retrieval_success' if result == 'ok' else 'retrieval_failure'
            events.append(self.event(kind, {'user': context['user_input'], 'status': result}, 'runtime'))
        return events

    def retrieved(self):
        for event in self.observed_events():
            self.experiences.append(**event)

    def envelope(self, reply, provenance):
        pending = self.pending
        user, context = pending['user'], pending['context']
        # No external snippets copied to auxiliary stores. The spoken response
        # remains a verbatim assistant_generated quotation, even if it cites Web.
        summary = {'intent': context['intent'], 'generated': bool((provenance or {}).get('generated')),
                   'source_kinds': sorted({s.get('kind', 'unknown') for s in (provenance or {}).get('sources', [])}),
                   'fact_evidence': False}
        record = {'session_id': self.session_id, 'turn_id': user.id, 'timestamp': user.ts,
                  'status': 'confirmed', 'user': user.payload['text'], 'assistant': reply, 'provenance': summary}
        events = [self.event('turn', {'user': user.payload['text'], 'assistant': reply}, 'assistant_generated')]
        events.extend(self.observed_events())
        return {'session': record, 'experiences': events}

    def event(self, kind, body, source, suffix=''):
        user = self.pending['user']
        return {'id': user.id + ':' + kind + suffix, 'kind': kind, 'turn_id': user.id,
                'timestamp': user.ts, 'source': source, 'body': body}

    def commit(self, envelope):
        record = envelope['session']
        self.recorder.append(record)
        self.index.add(record)
        for event in envelope['experiences']:
            self.experiences.append(**event)

    def confirmed(self, core, reply, provenance):
        envelope = self.envelope(reply, provenance)
        core.record_assistant_output(reply, provenance, fio_commit=envelope)
        self.commit(envelope)
        self.experiences.reinforce([r['id'] for r in self.pending['context']['salient_experiences']])
        self.pending = None

    def failed(self, error):
        if self.pending:
            # Failure is an observed exception, never a label inferred from model prose.
            self.experiences.append(**self.event('model_failure',
                {'user': self.pending['user'].payload['text'], 'error_type': type(error).__name__}, 'runtime'))
            self.pending = None

    def close(self):
        self.index.close()
        self.experiences.close()
