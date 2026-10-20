from __future__ import annotations
from .models import OpenLoop
from .textmath import cosine_text


class OpenLoopTracker:
    TASK_HINTS = ("やる", "やらないと", "しないと", "あとで", "予定", "作る", "買う", "提出", "確認", "調べる", "実装")
    DONE_HINTS = ("終わった", "終わり", "完了", "できた", "済んだ", "提出した", "買った")

    def __init__(self):
        self.loops: list[OpenLoop] = []

    def observe(self, text: str) -> None:
        if any(h in text for h in self.DONE_HINTS):
            self._auto_close(text)
        if any(h in text for h in self.TASK_HINTS) and not any(h in text for h in self.DONE_HINTS):
            if not any(cosine_text(text, x.text) > 0.82 and not x.done for x in self.loops):
                self.loops.append(OpenLoop(text=text[:160]))

    def _auto_close(self, text: str) -> None:
        candidates = [(cosine_text(text, x.text), x) for x in self.loops if not x.done]
        if not candidates:
            return
        score, loop = max(candidates, key=lambda z: z[0])
        if score >= 0.18:
            loop.done = True

    def active(self) -> list[OpenLoop]:
        return [x for x in self.loops if not x.done]
