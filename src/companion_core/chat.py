from .core import CompanionCore
from .prompt import PromptBuilder
from .model_adapter import ModelError
from .knowledge import KnowledgeGate
from .style import StyleValidator
from .cpu_answer import CPUAnswer
from .intent import IntentRouter
from .encoding import clean_input
from .retrieval import RetrievalEngine
from .fio_memory import FIOMemory
from .alignment import PolicyPlanner, PolicyVerifier
import threading
import copy
from dataclasses import replace


class ChatSession:
    def __init__(self, adapter, event_path=None, *, style_profile=None, retrieval=None, heat_config=None, prompt_mode='legacy'):
        self.core = CompanionCore(event_path)
        self.adapter = adapter
        self.prompts = PromptBuilder(style_profile, mode=prompt_mode)
        self.validator = StyleValidator()
        self.planner = PolicyPlanner()
        self.policy_verifier = PolicyVerifier()
        self.alignment_trace = {}
        self.last_response_meta = {}
        self.turn_lock = threading.RLock()
        self._closed = False
        self.pending_provenance = None
        self.retrieval = retrieval if retrieval is not None else RetrievalEngine.from_environment()
        self.fio = FIOMemory(event_path, heat_config=heat_config)
        self.fio.recover(self.core.events.events)

    def generate_reply(self, context, messages):
        reply = self._generate_reply(context, messages)
        if 'verifier_result' not in context:
            context['verifier_result'] = self.policy_verifier.verify(
                reply, self.planned_spec, self.planned_state, context['user_input'])
            context['verifier_result'].update(candidate_count=0, cpu_bypass=True)
        self.alignment_trace['verifier_result'] = context['verifier_result']
        return reply

    def _generate_reply(self, context, messages):
        self.pending_provenance = None
        self.last_response_meta = {}
        if context['intent'] == 'ambiguous_followup':
            self.pending_provenance = {'intent': 'ambiguous_followup', 'sources': [{'kind': 'assistant_generated', 'fact_evidence': False}], 'generated': False, 'referent': context.get('previous_assistant')}
            self.last_response_meta = {'unverified': False, 'regenerated': False, 'cpu': True}
            return ('直前の返答の受け取り方がずれてた。' if context.get('previous_assistant')
                    else '直前の返答はまだない。何についての反応か教えて。')
        if context['intent'] == 'time_calculation':
            self.pending_provenance = self.core.provenance.capture(context, generated=False)
            self.last_response_meta = {'unverified': False, 'regenerated': False, 'cpu': True}
            answer = CPUAnswer().answer(context['user_input'], context['runtime'])
            self.pending_provenance['calculation'] = {'input': context['user_input'], 'result': answer}
            return answer
        if context['intent'] == 'self_state_memory' and IntentRouter.provenance.search(context['user_input']):
            self.pending_provenance = self.core.provenance.last
            self.last_response_meta = {'unverified': False, 'regenerated': False, 'cpu': True}
            return self.core.provenance.answer()
        if context['intent'] == 'self_state_memory' and self.core.provenance.generic_memory_query(context['user_input']):
            reply, records = self.core.provenance.memory_answer(self.core.memory)
            self.pending_provenance = self.core.provenance.capture({'intent': context['intent'], 'memory': records}, generated=False)
            self.pending_provenance['memory_recall'] = records
            self.last_response_meta = {'unverified': False, 'regenerated': False, 'cpu': True}
            return reply
        if context["knowledge"]["external_required"] and not context.get('external_evidence'):
            self.last_response_meta = {"unverified": True, "regenerated": False, "cpu": True}
            status = context.get('external_retrieval', {}).get('status', 'disabled')
            self.pending_provenance = self.core.provenance.capture({'intent': context['intent']}, generated=False)
            self.pending_provenance['retrieval_status'] = status
            if status in {'disabled', 'offline'}:
                return KnowledgeGate.unverified_reply()
            return 'そこはまだ未確認。外部検索で十分な根拠を取得できなかった（' + status + '）。推測では答えない。'
        reply = self.adapter.generate(messages)
        if not isinstance(reply, str) or not reply.strip():
            raise ModelError("モデルが空の応答を返しました")
        if clean_input(reply) != reply:
            raise ModelError('モデル応答に不正なUnicodeが含まれています')
        state = self.planned_state
        spec = self.planned_spec
        style = self.prompts.style.context(context['user_input'])
        if state.response_risk == 'low' and (self.validator.violations(reply, style)
                                             or self.validator.language_issues(reply, context['user_input'])):
            # Output corruption/style defects raise the observed response risk;
            # an unchanged low-risk turn never receives a second candidate.
            state = replace(state, response_risk='medium')
            self.planned_state = state
            context['conversation_state']['response_risk'] = 'medium'
            context['conversation_state']['risk_escalation'] = 'observed_output_style_or_language'
        verify = lambda text: self.policy_verifier.verify(text, spec, state, context['user_input'])
        initial_verifier = copy.deepcopy(verify(reply))
        if (self.prompts.mode in {'character-jp-repair', 'character-scene', 'character-guided', 'character-dialogue', 'character-fewshot'} and state.response_risk == 'low'
                and not initial_verifier['adherent']):
            state = replace(state, response_risk='medium')
            self.planned_state = state
            context['conversation_state']['response_risk'] = 'medium'
            context['conversation_state']['risk_escalation'] = 'experimental_policy_retry'
        reply, meta = self.validator.process(reply.strip(), messages, self.adapter,
                                             style,
                                             policy_check=verify, response_spec=spec.to_dict(),
                                             risk=state.response_risk,
                                             retry_full_context=self.prompts.mode in {'character-repair', 'character-jp-repair', 'character-scene', 'character-guided', 'character-dialogue', 'character-fewshot'},
                                             reject_unreadable=self.prompts.mode in {'character-repair', 'character-jp-repair', 'character-scene', 'character-guided', 'character-dialogue', 'character-fewshot'},
                                             guided_retry=self.prompts.mode in {'character-guided', 'character-dialogue', 'character-fewshot'})
        context['verifier_result'] = copy.deepcopy(verify(reply))
        context['verifier_result']['initial'] = initial_verifier
        context['verifier_result']['candidate_count'] = 2 if meta.get('regenerated') else 1
        self.alignment_trace['verifier_result'] = context['verifier_result']
        self.last_response_meta = {"unverified": False, **meta,
                                   'web_unverified': bool(context.get('external_evidence'))}
        if meta.get('quality_fallback'):
            self.last_response_meta['cpu'] = True
        if clean_input(reply) != reply:
            raise ModelError('モデル応答に不正なUnicodeが含まれています')
        self.pending_provenance = self.core.provenance.capture(context['_supplied_provenance'], generated=not meta.get('quality_fallback', False))
        if meta.get('quality_fallback'):
            self.pending_provenance['fallback'] = meta['fallback_reason']
        return reply + self.retrieval.citations(context)

    def prepare_reply(self, context, events):
        self.planned_state = self.planner.observe(context['user_input'], events, context['intent'])
        self.planned_spec = self.planner.plan(self.planned_state, context['user_input'], context['intent'])
        context['conversation_state'] = self.planned_state.to_dict()
        context['response_spec'] = self.planned_spec.to_dict()
        self.fio.begin(self.core, context)
        result = self.retrieval.retrieve(context)
        self.retrieval.attach(context, result)
        self.fio.retrieved()
        self.alignment_trace = {key: context.get(key) for key in
                                ('conversation_state', 'response_spec', 'feedback_candidate_status')}
        self.alignment_trace['recall_source'] = {
            'priority': 'recent_raw', 'raw_turn_ids': [r['turn_id'] for r in self.planned_state.recent_raw_turns],
            'session_recall': [r.get('hit_turn_id') for r in context.get('session_recall', [])],
            'experiences': [r['id'] for r in context.get('salient_experiences', [])]}
        return self.prompts.build(context, events)

    def turn(self, text, *, correction_key=None, event_id=None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('空入力は送信できません')
        with self.turn_lock:
            if self._closed:
                raise RuntimeError('終了したセッションには送信できません')
            context = self.core.handle(text, correction_key=correction_key, event_id=event_id)
            if self.core.last_runtime is not None:
                context['runtime']['pc_observation'] = self.core.last_runtime
            try:
                messages = self.prepare_reply(context, self.core.events.events)
                reply = self.generate_reply(context, messages)
            except ModelError as exc:
                self.fio.failed(exc)
                raise
            except KeyboardInterrupt:
                self.fio.cancelled(self.core)
                raise
            self.fio.confirmed(self.core, reply, self.pending_provenance)
            return reply

    def status(self):
        return {**self.core.status(), 'conversation_alignment': self.alignment_trace}

    def close(self):
        with self.turn_lock:
            if not self._closed:
                self._closed = True
                self.fio.close()
