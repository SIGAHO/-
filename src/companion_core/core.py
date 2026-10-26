from __future__ import annotations
import time
import re
import hashlib
from .intent import normalized
from .models import Event, SourceType, Scope, Status
from .event_store import EventStore
from .state import StateEngine
from .correction import CorrectionEngine, Correction
from .time_engine import TimeEngine
from .topic import TopicTracker
from .open_loops import OpenLoopTracker
from .memory import MemoryEngine
from .emotion import EmotionEngine
from .context import ContextAssembler
from .knowledge import KnowledgeGate, KnowledgeDecision
from .intent import IntentRouter
from .encoding import clean_input
from .provenance import ProvenanceResponder
from .textmath import cosine_text


class CompanionCore:
    def __init__(self, event_path=None):
        self.events = EventStore(event_path)
        self.state = StateEngine()
        self.corrections = CorrectionEngine()
        self.time = TimeEngine()
        self.topic = TopicTracker()
        self.open_loops = OpenLoopTracker()
        self.memory = MemoryEngine()
        self.emotion = EmotionEngine()
        self.context = ContextAssembler()
        self.trace: list[dict] = []
        self.last_runtime = None
        self.knowledge = KnowledgeGate()
        self.router = IntentRouter()
        self.provenance = ProvenanceResponder()
        self.last_assistant = None
        self.knowledge_subjects = ()
        if self.events.events:
            self.replay()

    def _remember_correction(self, key, value, ts):
        text = f"{key} = {value}"
        for item in self.memory.items:
            if item.source == SourceType.USER_CORRECTION and item.text.startswith(f"{key} = ") and item.text != text:
                item.status = Status.ARCHIVED
        self.memory.add(text, SourceType.USER_CORRECTION, 0.9, now=ts)

    def _trace(self, stage: str, detail: dict):
        self.trace.append({"ts": time.time(), "stage": stage, **detail})
        del self.trace[:-1200]

    def _observe_user(self, text, ts):
        intent = self.router.route(text, previous_subjects=self.knowledge_subjects)
        bypass = (intent in {'ambiguous_followup', 'continuation', 'self_state_memory', 'time_calculation'}
                  or self.router.casual.fullmatch(normalized(text)))
        if bypass:
            self.topic.last_decision = 'route_bypass'
        topic = self.topic.current() if bypass else self.topic.update(text)
        if topic and self.topic.last_decision in {"new", "matched"}:
            topic.last_seen = ts
        before = len(self.open_loops.loops)
        self.open_loops.observe(text)
        for loop in self.open_loops.loops[before:]:
            loop.created_at = ts
            loop.id = hashlib.sha256(f"{ts}:{loop.text}".encode()).hexdigest()
        return topic, self.emotion.observe_user(text)

    def handle(self, text: str, *, correction_key: str | None = None, event_id=None) -> dict:
        text = clean_input(text)
        if len(text) > 16000:
            raise ValueError('入力は1〜16000文字にしてください')
        if correction_key is not None and not isinstance(correction_key, str):
            raise ValueError('invalid correction key')
        if event_id is not None and any(e.id == event_id for e in self.events.events):
            raise ValueError('duplicate input event; state was not updated')
        intent = self.router.route(text, correction_key=correction_key, previous_subjects=self.knowledge_subjects)
        payload = {"text": text}
        if correction_key is not None:
            payload['correction_key'] = correction_key
        user_event = Event(kind="user_input", payload=payload, source=SourceType.USER_STATEMENT,
                           **({'id': event_id} if event_id is not None else {}))
        if not self.events.append(user_event):
            raise ValueError('duplicate input event; state was not updated')
        self._trace("user_input", {"text": text})

        tf = self.time.runtime_facts()
        for k, v in tf.items():
            self.state.propose(k, v, SourceType.RUNTIME, Scope.TURN)
        self._trace("runtime", tf)

        detected = self.corrections.detect(text)
        # An explicit year assertion can correct a user-year fact only when
        # its target is supplied. Keep runtime time.year authoritative and
        # do not reinterpret year statements as names or generic corrections.
        if not detected and correction_key in {"year", "time.user_year"}:
            year = self.time.parse_user_year_statement(text)
            if year is not None:
                detected = [Correction(old=None, new=year, confidence=1.0, pattern="explicit_year_statement")]
        # A target key alone does not identify which of several corrections
        # belongs to it. Never choose the first candidate arbitrarily.
        if correction_key and correction_key.startswith("time.") and correction_key != "time.user_year":
            detected = []
        if correction_key and len(detected) == 1:
            c = detected[0]
            correction_event = Event(
                kind="correction",
                payload={"key": correction_key, "old": c.old, "new": c.new},
                source=SourceType.USER_CORRECTION,
            )
            self.events.append(correction_event)
            self.state.correct(correction_key, c.new, c.old, Scope.SESSION,
                               now=correction_event.ts, event_id=correction_event.id)
            self._remember_correction(correction_key, c.new, self.events.events[-1].ts)
            self._trace("correction", {
                "key": correction_key, "old": c.old, "new": c.new, "pattern": c.pattern
            })
        elif detected:
            self._trace("correction_proposal", {
                "items": [c.__dict__ for c in detected],
                "reason": "multiple_candidates" if correction_key else "missing_target",
            })

        done_before = {x.id for x in self.open_loops.loops if x.done}
        topic, emo = self._observe_user(text, user_event.ts)
        self._trace("topic", {"current": topic.label if topic else None})
        self._trace("emotion", emo.to_dict())

        memories = self.memory.retrieve(text)
        decision = (self.knowledge.evaluate(text, self.memory, self.state, self.knowledge_subjects, force_external=True)
                    if intent == 'external_knowledge' else KnowledgeDecision(False, False, (), (), 'route_bypass'))
        if intent == 'external_knowledge' and not decision.reliable_context:
            decision = KnowledgeDecision(True, False, decision.subjects, (), 'missing_reliable_evidence')
        # Replace the referent on each substantive new user topic; AI output
        # never supplies or resolves a referent.
        if decision.subjects:
            self.knowledge_subjects = decision.subjects
        elif self.topic.last_decision == "new":
            self.knowledge_subjects = ()
        self.memory.add(text, SourceType.USER_STATEMENT, importance=0.35,
                        now=user_event.ts)

        ctx = self.context.build(
            user_input=text,
            state=self.state.snapshot(),
            time_facts=tf,
            topic=topic,
            open_loops=self.open_loops.active(),
            memories=memories,
            emotion=emo,
            trace_tail=self.trace,
        )
        observed = {key: ctx[key] for key in ('topic', 'memory', 'open_loops')}
        ctx['intent'] = intent
        ctx['completed_loop_ids'] = [x.id for x in self.open_loops.loops if x.done and x.id not in done_before]
        ctx['previous_assistant'] = self.last_assistant
        if intent in {'ambiguous_followup', 'continuation'} or self.router.casual.fullmatch(normalized(text)):
            ctx['topic'] = None
            ctx['memory'] = []
            ctx['open_loops'] = []
        elif intent == 'casual_chat' and topic and not (self.topic.last_decision in {"new", "matched"} or cosine_text(text, topic.label) >= .35 or re.search(r'その|それ|さっき|続き', text)):
            ctx['topic'] = None
            ctx['memory'] = [m.text for m in memories if cosine_text(text, m.text) >= .35]
        ctx['prompt_context'] = {key: ctx[key] for key in observed}
        ctx.update(observed)
        ctx["knowledge"] = decision.to_dict()
        self._trace("context_assembled", {
            "memory_count": len(memories),
            "open_loop_count": len(self.open_loops.active()),
        })
        return ctx

    def record_assistant_output(self, text: str, provenance=None, *, fio_commit=None) -> None:
        self.events.append(Event(
            kind="assistant_output",
            payload={"text": clean_input(text), "provenance": provenance,
                     **({'fio_commit': fio_commit} if fio_commit is not None else {})},
            source=SourceType.ASSISTANT_GENERATED,
        ))
        self.last_assistant = clean_input(text)
        self.provenance.last = provenance
        self._trace("assistant_output", {"text": text, "state_admission": False})

    def accept_runtime(self, event):
        """Only the OS observation route may provide runtime metadata, never AI text."""
        allowed = {"current_time", "uptime", "active_processes", "foreground_window_title"}
        if (event.kind != "runtime_observation" or event.source != SourceType.RUNTIME
                or not {"current_time", "uptime", "active_processes"} <= event.payload.keys()
                or not event.payload.keys() <= allowed):
            return False
        self.last_runtime = dict(event.payload)
        return True

    def status(self):
        topic = self.topic.current()
        return {"current_time": self.time.now().isoformat(timespec="seconds"),
                "open_loops": [x.text for x in self.open_loops.active()],
                "topic": topic.label if topic else None,
                "emotion": self.emotion.state.to_dict(),
                "last_pc_observation": self.last_runtime}

    def replay(self) -> None:
        old = list(self.events.events)
        self.state = StateEngine()
        self.topic = TopicTracker()
        self.open_loops = OpenLoopTracker()
        self.memory = MemoryEngine()
        self.emotion = EmotionEngine()
        self.trace = []
        self.last_runtime = None
        self.knowledge_subjects = ()
        self.last_assistant = None
        self.provenance.last = None

        pending_memory = None
        for e in old:
            # Live handle commits corrections before storing the raw utterance.
            if e.kind != "correction" and pending_memory is not None:
                self.memory.add(pending_memory.payload.get("text", ""),
                                SourceType.USER_STATEMENT, 0.35, now=pending_memory.ts)
                pending_memory = None
            if e.kind == "correction" and e.source == SourceType.USER_CORRECTION:
                p = e.payload
                self.state.correct(p["key"], p["new"], p.get("old"), Scope.SESSION, now=e.ts, event_id=e.id)
                self._remember_correction(p["key"], p["new"], e.ts)
            elif e.kind == "user_input" and e.source == SourceType.USER_STATEMENT:
                text = e.payload.get("text", "")
                intent = self.router.route(text, correction_key=e.payload.get('correction_key'), previous_subjects=self.knowledge_subjects)
                decision = (self.knowledge.evaluate(text, self.memory, self.state, self.knowledge_subjects, force_external=True)
                            if intent == 'external_knowledge' else KnowledgeDecision(False, False, (), (), 'route_bypass'))
                self._observe_user(text, e.ts)
                if decision.subjects:
                    self.knowledge_subjects = decision.subjects
                elif self.topic.last_decision == "new":
                    self.knowledge_subjects = ()
                pending_memory = e
            elif e.kind == "assistant_output" and e.source == SourceType.ASSISTANT_GENERATED:
                self.last_assistant = e.payload.get('text', '')
                self.provenance.last = e.payload.get('provenance')
            elif e.kind == "runtime_observation":
                self.accept_runtime(e)
        if pending_memory is not None:
            self.memory.add(pending_memory.payload.get("text", ""),
                            SourceType.USER_STATEMENT, 0.35, now=pending_memory.ts)
        # Runtime facts describe this process, never a historical model claim.
        for key, value in self.time.runtime_facts().items():
            self.state.propose(key, value, SourceType.RUNTIME, Scope.TURN)
