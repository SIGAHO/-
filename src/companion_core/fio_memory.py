"""Shared chat/daemon writeback and bounded auxiliary context. No State/Memory writes."""
import uuid
from pathlib import Path

from .experience import ExperienceStore
from .session_memory import EXPLICIT_RECALL, SessionRecorder, SessionIndex
from .preferences import PreferenceStore, group_split


class FIOMemory:
    def __init__(self, event_path=None, *, heat_config=None):
        self.session_id = str(uuid.uuid4())
        prefix = str(Path(event_path)) + '.fio' if event_path else None
        self.recorder = SessionRecorder(prefix + '.sessions.jsonl' if prefix else None)
        self.index = SessionIndex(prefix + '.index.sqlite3' if prefix else None)
        self.index.rebuild(self.recorder.records)
        self.experiences = ExperienceStore(prefix + '.experiences.sqlite3' if prefix else None, config=heat_config)
        self.pending = None
        self.needs_recovery = False
        self.preferences = PreferenceStore(prefix + '.preferences' if prefix else None)

    def recover(self, events):
        # Commit envelopes are an outbox for crashes after EventStore fsync and
        # before sidecar writeback. Replay itself never writes these stores.
        for event in events:
            if event.kind == 'assistant_output' and event.payload.get('fio_commit'):
                self.commit(event.payload['fio_commit'])
        # Existing sidecars can contain recovered records appended after later
        # turns. Event outbox order is authoritative for known records; leave
        # records without an outbox in their original slots, without rewriting JSONL.
        order = [e.payload['fio_commit']['session']['turn_id'] for e in events
                 if e.kind == 'assistant_output' and e.payload.get('fio_commit')]
        position = {turn_id: i for i, turn_id in enumerate(order)}
        records = self.recorder.records
        known = iter(sorted((r for r in records if r['turn_id'] in position),
                            key=lambda r: position[r['turn_id']]))
        ordered = [next(known) if r['turn_id'] in position else r for r in records]
        if ordered != self.index.records:
            self.index.rebuild(ordered)
        # A crash can occur after the raw user event fsync but before begin().
        # Recover that last unconfirmed reaction without inventing an answer.
        raw = [e for e in events if e.kind in {'user_input', 'assistant_output'}]
        if raw and raw[-1].kind == 'user_input':
            from .alignment import PolicyPlanner
            user = raw[-1]
            previous = next((e for e in reversed(raw[:-1]) if e.kind == 'assistant_output'), None)
            prior = previous.payload.get('fio_commit', {}).get('session') if previous else None
            if prior and prior.get('provenance', {}).get('alignment'):
                state = PolicyPlanner().observe(user.payload['text'], raw).to_dict()
                self.pending = {'user': user, 'context': {'user_input': user.payload['text'],
                                'conversation_state': state}, 'previous': prior}
                candidate = self.preference_candidate()
                if candidate:
                    self.preferences.append(candidate)
                identity = user.id + ':next_user_reaction'
                if not any(r['id'] == identity for r in self.experiences.all()):
                    self.experiences.append(**self.event('next_user_reaction', {
                        'user': user.payload['text'], 'session_id': prior['session_id'],
                        'causation_id': prior['turn_id'] + ':assistant_response',
                        'next_user_reaction': state['reaction_to_previous'],
                        'explicit_feedback': state['explicit_feedback'],
                        'rejected_strategy': state['previous_assistant_strategy'] if state['reaction_to_previous'] in {'rejected', 'corrected'} else None,
                        'inferred_not_ground_truth': True}, 'user_statement'))
                self.pending = None

        self.pending = None
        self.needs_recovery = False

    def begin(self, core, context):
        user = next(e for e in reversed(core.events.events) if e.kind == 'user_input')
        self.pending = {'user': user, 'context': context}
        previous = next((e for e in reversed(core.events.events) if e.kind == 'assistant_output'), None)
        self.pending['previous'] = previous.payload.get('fio_commit', {}).get('session') if previous else None
        feedback = self.preference_candidate()
        context['feedback_candidate_status'] = {'status': 'pending_human_review' if feedback else 'no_explicit_feedback',
                                                'id': feedback['id'] if feedback else None}
        if feedback:
            self.preferences.append(feedback)
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
        state = context.get('conversation_state', {})
        if state.get('reaction_to_previous') in {'rejected', 'corrected'}:
            # Failure-triggered recall is a lesson, never an old topic/fact.
            context['salient_experiences'] = self.experiences.salient(
                context['user_input'], kinds={'next_user_reaction', 'correction', 'model_failure'})
        # Read before write so the current observation cannot recall itself.
        for event in self.observed_events():
            self.experiences.append(**event)

    def preference_candidate(self):
        context = self.pending['context']
        state = context.get('conversation_state', {})
        prior = self.pending.get('previous')
        feedback = state.get('explicit_feedback')
        if not prior or not feedback or not prior.get('provenance', {}).get('alignment'):
            return None
        user = self.pending['user']
        alignment = prior['provenance']['alignment']
        return {'schema_version': 1, 'id': user.id + ':preference',
                'context': alignment['conversation_state']['recent_raw_turns'] +
                           [{'turn_id': prior['turn_id'], 'role': 'user', 'text': prior['user']}],
                'raw_turn_ids': [r['turn_id'] for r in alignment['conversation_state']['recent_raw_turns']] + [prior['turn_id']],
                'response_spec': alignment['response_spec'],
                'chosen': prior['assistant'] if feedback == 'approval' else None,
                'rejected': prior['assistant'] if feedback != 'approval' else None,
                'source_type': 'real_user_feedback', 'teacher_model': None, 'teacher_generated': False,
                'human_approved': False, 'session_id': prior['session_id'], 'turn_id': prior['turn_id'],
                'split': group_split(prior['session_id']),
                'provenance': {'feedback_turn_id': user.id, 'feedback_text': user.payload['text'],
                               'explicit_feedback': feedback, 'generated_response_source': 'assistant_generated',
                               'causation_id': prior['turn_id'] + ':assistant_response',
                               'not_ground_truth': True}}

    def observed_events(self):
        context = self.pending['context']
        events = []
        state = context.get('conversation_state', {})
        prior = self.pending.get('previous')
        if prior and state and prior.get('provenance', {}).get('alignment'):
            events.append(self.event('next_user_reaction', {
                'user': context['user_input'], 'session_id': self.session_id,
                'causation_id': prior['turn_id'] + ':assistant_response',
                'next_user_reaction': state['reaction_to_previous'],
                'explicit_feedback': state['explicit_feedback'],
                'rejected_strategy': state['previous_assistant_strategy'] if state['reaction_to_previous'] in {'rejected', 'corrected'} else None,
                'inferred_not_ground_truth': True}, 'user_statement'))
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
        alignment = {key: context.get(key) for key in ('conversation_state', 'response_spec', 'verifier_result')}
        if alignment['conversation_state']:
            record['provenance']['alignment'] = alignment
        events = [self.event('turn', {'user': user.payload['text'], 'assistant': reply}, 'assistant_generated')]
        if alignment['conversation_state']:
            events.append(self.event('assistant_response', {
                'user': user.payload['text'], 'policy_spec': alignment['response_spec'],
                'generated_response': reply, 'verifier_result': alignment['verifier_result'],
                'next_user_reaction': None, 'explicit_feedback': None, 'rejected_strategy': None,
                'session_id': self.session_id, 'turn_id': user.id,
                'causation_id': user.id}, 'assistant_generated'))
        events.extend(self.observed_events())
        return {'session': record, 'experiences': events,
                'preferences': [self.preference_candidate()] if self.preference_candidate() else []}

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
        for record in envelope.get('preferences', []):
            self.preferences.append(record)

    def confirmed(self, core, reply, provenance):
        envelope = self.envelope(reply, provenance)
        self.needs_recovery = True
        core.record_assistant_output(reply, provenance, fio_commit=envelope)
        self.commit(envelope)
        self.experiences.reinforce([r['id'] for r in self.pending['context']['salient_experiences']])
        self.pending = None
        self.needs_recovery = False

    def failed(self, error):
        if self.pending:
            # Failure is an observed exception, never a label inferred from model prose.
            self.experiences.append(**self.event('model_failure',
                {'user': self.pending['user'].payload['text'], 'error_type': type(error).__name__}, 'runtime'))
            self.pending = None

    def cancelled(self, core=None):
        if self.pending is None and core is not None:
            # prepare_reply may be interrupted before begin() establishes the
            # pending envelope; the caller has already committed this input.
            user = None
            for event in reversed(core.events.events):
                if event.kind == 'assistant_output':
                    break
                if event.kind == 'user_input':
                    user = event
                    break
            if user is not None:
                self.pending = {'user': user}
        if self.pending:
            # The user stopped the turn; this is not evidence of model failure.
            self.experiences.append(**self.event('generation_cancelled',
                {'user': self.pending['user'].payload['text'], 'reason': 'keyboard_interrupt'}, 'runtime'))
            self.pending = None

    def close(self):
        self.index.close()
        self.experiences.close()
