from .core import CompanionCore
from .prompt import PromptBuilder
from .model_adapter import ModelError


class ChatSession:
    def __init__(self, adapter, event_path=None):
        self.core = CompanionCore(event_path)
        self.adapter = adapter
        self.prompts = PromptBuilder()

    def turn(self, text, *, correction_key=None):
        if not text.strip():
            raise ValueError("空入力は送信できません")
        context = self.core.handle(text, correction_key=correction_key)
        if self.core.last_runtime is not None:
            context["runtime"]["pc_observation"] = self.core.last_runtime
        messages = self.prompts.build(context, self.core.events.events)
        reply = self.adapter.generate(messages)
        if not isinstance(reply, str) or not reply.strip():
            raise ModelError("モデルが空の応答を返しました")
        self.core.record_assistant_output(reply)
        return reply

    def status(self):
        return self.core.status()

    def close(self):
        pass
