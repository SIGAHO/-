from __future__ import annotations
import re
from .models import OpenLoop
from .textmath import cosine_text, char_ngrams


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
    UNCERTAIN_DONE = re.compile(
        r'(?:終わった|完了した|できた|済んだ|提出した|買った)(?:と(?:は)?(?:言って|いって)ない|とは限らない|かもしれない|かも|可能性)'
    )
    QUESTION = re.compile(r"[?？]|(?:です|ます)?か[。！!\s]*$")
    BARE_DONE = re.compile(
        r"(?:終わった|終わり|完了(?:した)?|できた|済んだ|提出した|買った)(?:です|よ|ね)*[。！!\s]*"
    )
    OTHER_SUBJECT = re.compile(r'(?:友達|友人|先生|家族|母|父|兄|姉|弟|妹|彼|彼女|他の人)(?:が|は)')
    TASK_VERBS = re.compile(r'提出|確認|実装|調べ|買[いうっ]|作[るっ]|やる|やっ|終わ[ったりる]*|完了|できた|済んだ|あとで|予定|する|した')

    def __init__(self):
        self.loops: list[OpenLoop] = []

    def observe(self, text: str) -> None:
        text = text.strip()
        # An example or quoted sentence is not itself the user's commitment.
        # Outside-the-quote commitments remain eligible for observation.
        if re.search(r'(?:という|といった|の)(?:例文|例|文章|発言)', text):
            text = re.sub(r'「[^」]*」|『[^』]*』', '', text).strip()
        # A denial, question, or future condition is not completion evidence.
        # It must not fall through to task creation merely because it mentions
        # the existing task's verb. Mixed/ambiguous utterances stay unchanged.
        if not text or any(pattern.search(text) for pattern in (
            self.NOT_DONE, self.NO_PLAN, self.CONDITIONAL_DONE, self.UNCERTAIN_DONE, self.QUESTION
        )):
            return
        done = any(h in text for h in self.DONE_HINTS)
        if done:
            self._auto_close(text)
        elif any(h in text for h in self.TASK_HINTS):
            if not any(cosine_text(text, x.text) > 0.82 and not x.done for x in self.loops):
                self.loops.append(OpenLoop(text=text[:160]))

    def _auto_close(self, text: str) -> None:
        # A different person's action is not evidence that the user's task
        # was completed, even when the verbs happen to match.
        active = self.active()
        if self.OTHER_SUBJECT.search(text):
            return
        # Unknown names can also be subjects (e.g. 田中が提出した).
        # A leading task noun such as 宿題が終わった remains eligible.
        subject = re.match(r'^([^、。\s]{1,16})(?:が|は)', text)
        subject_text = subject[1].removesuffix('の') if subject else ''
        subject_target = self.TASK_VERBS.sub('', subject_text).replace('作業', '').strip('のをはが')
        matches_task = any(subject_text in loop.text or (subject_target and subject_target in loop.text) for loop in active)
        if subject and subject_text not in ('私', '僕', '俺', '自分') and not matches_task:
            return
        # An explicit cleft construction identifies someone else as actor.
        cleft = re.search(r'(?:終わった|完了した|できた|済んだ|提出した|買った)のは([^、。\s]+)', text)
        if cleft and not re.match(r'(?:私|僕|俺|自分|今日|昨日|一昨日|今朝|昨夜|先週|先月|先日|(?:午前|午後)?\d{1,2}時(?:\d{1,2}分)?)(?:だ|です|[。！!]|$)', cleft[1]):
            return
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
        # Shared verbs alone (e.g. two different things being submitted) do
        # not identify the pending task. Keep ambiguous cases open.
        task_words = set(char_ngrams(self.TASK_VERBS.sub('', loop.text)))
        done_words = set(char_ngrams(self.TASK_VERBS.sub('', text)))
        if score >= 0.18 and unique and task_words & done_words:
            loop.done = True

    def active(self) -> list[OpenLoop]:
        return [x for x in self.loops if not x.done]
