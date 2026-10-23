from .core import CompanionCore
from .prompt import PromptBuilder
from .model_adapter import ModelError
from .knowledge import KnowledgeGate
from .style import StyleValidator
from .cpu_answer import CPUAnswer
from .intent import IntentRouter
from .encoding import clean_input
import threading


class ChatSession:
    def __init__(self, adapter, event_path=None, *, style_profile=None):
        self.core = CompanionCore(event_path)
        self.adapter = adapter
        self.prompts = PromptBuilder(style_profile)
        self.validator = StyleValidator()
        self.last_response_meta = {}
        self.turn_lock = threading.RLock()
        self.pending_provenance = None

    def generate_reply(self, context, messages):
        self.pending_provenance = None
        self.last_response_meta = {}
        if context['intent'] == 'ambiguous_followup':
            self.pending_provenance = {'intent': 'ambiguous_followup', 'sources': [{'kind': 'assistant_generated', 'fact_evidence': False}], 'generated': False, 'referent': context.get('previous_assistant')}
            self.last_response_meta = {'unverified': False, 'regenerated': False, 'cpu': True}
            return ('直前の返答について、どの部分が引っかかった？' if context.get('previous_assistant')
                    else '直前の返答はまだない。何についての反応か教えて。')
        if context['intent'] == 'time_calculation':
            self.pending_provenance = self.core.provenance.capture(context, generated=False)
            self.last_response_meta = {'unverified': False, 'regenerated': False, 'cpu': True}
            return CPUAnswer().answer(context['user_input'], context['runtime'])
        if context['intent'] == 'self_state_memory' and IntentRouter.provenance.search(context['user_input']):
            self.pending_provenance = self.core.provenance.last
            self.last_response_meta = {'unverified': False, 'regenerated': False, 'cpu': True}
            return self.core.provenance.answer()
        if context['intent'] == 'self_state_memory' and self.core.provenance.generic_memory_query(context['user_input']):
            reply, records = self.core.provenance.memory_answer(self.core.memory)
            self.pending_provenance = self.core.provenance.capture({**context, 'memory': records, 'state': {}, 'runtime': {}, 'prompt_context': {}}, generated=False)
            self.last_response_meta = {'unverified': False, 'regenerated': False, 'cpu': True}
            return reply
        if context["knowledge"]["external_required"]:
            self.last_response_meta = {"unverified": True, "regenerated": False}
            self.pending_provenance = self.core.provenance.capture({**context, "state": {}, "runtime": {}, "memory": [], "prompt_context": {}}, generated=False)
            return KnowledgeGate.unverified_reply()
        reply = self.adapter.generate(messages)
        if not isinstance(reply, str) or not reply.strip():
            raise ModelError("モデルが空の応答を返しました")
        reply, meta = self.validator.process(reply.strip(), messages, self.adapter,
                                             self.prompts.style.context(context["user_input"]))
        self.last_response_meta = {"unverified": False, **meta}
        if clean_input(reply) != reply:
            raise ModelError('モデル応答に不正なUnicodeが含まれています')
        self.pending_provenance = self.core.provenance.capture(context, generated=True)
        return reply

    def turn(self, text, *, correction_key=None, event_id=None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('空入力は送信できません')
        with self.turn_lock:
            context = self.core.handle(text, correction_key=correction_key, event_id=event_id)
            if self.core.last_runtime is not None:
                context['runtime']['pc_observation'] = self.core.last_runtime
            messages = self.prompts.build(context, self.core.events.events)
            reply = self.generate_reply(context, messages)
            self.core.record_assistant_output(reply, self.pending_provenance)
            return reply

    def status(self):
        return self.core.status()

    def close(self):
        pass
