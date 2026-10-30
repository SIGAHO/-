"""Inference only. No training, judging, teacher store, or model asset loading."""
from abc import ABC, abstractmethod
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ModelError(RuntimeError):
    pass


class ModelAdapter(ABC):
    @abstractmethod
    def generate(self, messages: list[dict[str, str]]) -> str:
        """Return one assistant reply, or raise ModelError."""


class OllamaAdapter(ModelAdapter):
    def __init__(self, model=None, base_url=None, timeout=180):
        self.model = model or os.environ.get("BREAKTAIL_MODEL", "qwen2.5:14b")
        self.base_url = (base_url or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        if "://" not in self.base_url:
            self.base_url = "http://" + self.base_url
        self.timeout = timeout

    def generate(self, messages):
        body = json.dumps({"model": self.model, "messages": messages, "stream": False,
                           "options": {"num_predict": 256, "temperature": 0.6}}, ensure_ascii=False).encode("utf-8")
        request = Request(self.base_url + "/api/chat", data=body,
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
            reply = data["message"]["content"]
            if not isinstance(reply, str) or not reply.strip() or data.get("done") is not True:
                raise ValueError("empty or incomplete reply")
            if data.get('done_reason') == 'length':
                raise ValueError('reply exceeded generation limit')
            return reply.strip()
        except HTTPError as exc:
            raise ModelError(f"Ollama HTTP {exc.code}: check model '{self.model}' (ollama pull {self.model})") from exc
        except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
            raise ModelError(f"Ollama response unavailable: {exc}. Check ollama serve and --host / OLLAMA_HOST.") from exc


class FakeModelAdapter(ModelAdapter):
    """Scripted plumbing tests only; never used as a quality judge or teacher."""
    def __init__(self, replies=("こんにちは。今日はどんな話をしようか。",)):
        self.replies = iter(replies)
        self.requests = []

    def generate(self, messages):
        self.requests.append(messages)
        return next(self.replies, "うん、続きを聞かせて。")
