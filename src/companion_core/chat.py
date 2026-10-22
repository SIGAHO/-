from .core import CompanionCore
from .prompt import PromptBuilder
from .model_adapter import ModelError
from .knowledge import KnowledgeGate
from .style import StyleValidator


class ChatSession:
    def __init__(self, adapter, event_path=None, *, style_profile=None):
        self.core = CompanionCore(event_path)
        self.adapter = adapter
        self.prompts = PromptBuilder(style_profile)
        self.validator = StyleValidator()
        self.last_response_meta = {}

    def generate_reply(self, context, messages):
        if context["knowledge"]["external_required"]:
            self.last_response_meta = {"unverified": True, "regenerated": False}
            return KnowledgeGate.unverified_reply()
        reply = self.adapter.generate(messages)
        if not isinstance(reply, str) or not reply.strip():
            raise ModelError("モデルが空の応答を返しました")
        reply, meta = self.validator.process(reply.strip(), messages, self.adapter,
                                             self.prompts.style.context(context["user_input"]))
        self.last_response_meta = {"unverified": False, **meta}
        return reply

    def turn(self, text, *, correction_key=None):
        if not text.strip():
            raise ValueError("空入力は送信できません")
        context = self.core.handle(text, correction_key=correction_key)
        if self.core.last_runtime is not None:
            context["runtime"]["pc_observation"] = self.core.last_runtime
        messages = self.prompts.build(context, self.core.events.events)
        reply = self.generate_reply(context, messages)
        self.core.record_assistant_output(reply)
        return reply

    def status(self):
        return self.core.status()

    def close(self):
        pass
