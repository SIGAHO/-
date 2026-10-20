from __future__ import annotations
import re
from .models import OpenLoop
from .textmath import cosine_text


class OpenLoopTracker:
    TASK_HINTS = ("やる", "やらないと", "しないと", "あとで", "予定", "作る", "買う", "提出", "確認", "調べる", "実装")
    DONE_HINTS = ("終わった", "終わり", "完了", "できた", "済んだ", "提出した", "買った")
    NOT_DONE = re.compile(
        r"(?:終わ(?:って(?:い)?|ら|り)|完了して(?:い)?|できて(?:い)?|済んで(?:い)?|提出して(?:い)?|買って(?:い)?)(?:ない|ません)"
        r"|(?:終わった|終わり|完了(?:した)?|できた|済んだ|提出した|買った)(?:わけ|訳)?(?:じゃ|では|で)ない"
        r"|未完了|未提出"
    )
    NO_PLAN = re.compile(
        r"(?:予定|つもり)(?:は|が|も)?(?:ない|ありません)"
        r"|(?:やら|作ら|買わ|調べ|確認し|実装し|提出し)ない(?!と)"
    )
    CONDITIONAL_DONE = re.compile(
        r"(?:終わった|完了した|できた|済んだ|提出した|買った)(?:ら|場合|とき|時|あと|後)"
    )
    QUESTION = re.compile(r"[?？]|(?:です|ます)?か[。！!\s]*$")
    BARE_DONE = re.compile(
        r"(?:終わった|終わり|完了(?:した)?|できた|済んだ|提出した|買った)(?:です|よ|ね)*[。！!\s]*"
    )

    def __init__(self):
        self.loops: list[OpenLoop] = []

    def observe(self, text: str) -> None:
        text = text.strip()
        # A denial, question, or future condition is not completion evidence.
        # It must not fall through to task creation merely because it mentions
        # the existing task's verb. Mixed/ambiguous utterances stay unchanged.
        if not text or any(pattern.search(text) for pattern in (
            self.NOT_DONE, self.NO_PLAN, self.CONDITIONAL_DONE, self.QUESTION
        )):
            return
        done = any(h in text for h in self.DONE_HINTS)
        if done:
            self._auto_close(text)
        elif any(h in text for h in self.TASK_HINTS):
            if not any(cosine_text(text, x.text) > 0.82 and not x.done for x in self.loops):
                self.loops.append(OpenLoop(text=text[:160]))

    def _auto_close(self, text: str) -> None:
        active = self.active()
        if self.BARE_DONE.fullmatch(text):
            # A subject-free completion is resolvable only with one pending task.
            if len(active) == 1:
                active[0].done = True
            return
        candidates = sorted(((cosine_text(text, x.text), x) for x in active), key=lambda z: z[0], reverse=True)
        if not candidates:
            return
        score, loop = candidates[0]
        unique = len(candidates) == 1 or score - candidates[1][0] > 1e-12
        if score >= 0.18 and unique:
            loop.done = True

    def active(self) -> list[OpenLoop]:
        return [x for x in self.loops if not x.done]
