from __future__ import annotations
import time
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

    def _observe_user(self, text, ts):
        topic = self.topic.update(text)
        if topic and self.topic.last_decision in {"new", "matched"}:
            topic.last_seen = ts
        before = len(self.open_loops.loops)
        self.open_loops.observe(text)
        for loop in self.open_loops.loops[before:]:
            loop.created_at = ts
        return topic, self.emotion.observe_user(text)

    def handle(self, text: str, *, correction_key: str | None = None) -> dict:
        user_event = Event(kind="user_input", payload={"text": text}, source=SourceType.USER_STATEMENT)
        self.events.append(user_event)
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
        if correction_key and len(detected) == 1:
            c = detected[0]
            self.state.correct(correction_key, c.new, c.old, Scope.SESSION)
            self.events.append(Event(
                kind="correction",
                payload={"key": correction_key, "old": c.old, "new": c.new},
                source=SourceType.USER_CORRECTION,
            ))
            self._remember_correction(correction_key, c.new, self.events.events[-1].ts)
            self._trace("correction", {
                "key": correction_key, "old": c.old, "new": c.new, "pattern": c.pattern
            })
        elif detected:
            self._trace("correction_proposal", {
                "items": [c.__dict__ for c in detected],
                "reason": "multiple_candidates" if correction_key else "missing_target",
            })

        topic, emo = self._observe_user(text, user_event.ts)
        self._trace("topic", {"current": topic.label if topic else None})
        self._trace("emotion", emo.to_dict())

        memories = self.memory.retrieve(text)
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
        self._trace("context_assembled", {
            "memory_count": len(memories),
            "open_loop_count": len(self.open_loops.active()),
        })
        return ctx

    def record_assistant_output(self, text: str) -> None:
        self.events.append(Event(
            kind="assistant_output",
            payload={"text": text},
            source=SourceType.ASSISTANT_GENERATED,
        ))
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

        pending_memory = None
        for e in old:
            # Live handle commits corrections before storing the raw utterance.
            if e.kind != "correction" and pending_memory is not None:
                self.memory.add(pending_memory.payload.get("text", ""),
                                SourceType.USER_STATEMENT, 0.35, now=pending_memory.ts)
                pending_memory = None
            if e.kind == "correction" and e.source == SourceType.USER_CORRECTION:
                p = e.payload
                self.state.correct(p["key"], p["new"], p.get("old"), Scope.SESSION)
                self._remember_correction(p["key"], p["new"], e.ts)
            elif e.kind == "user_input" and e.source == SourceType.USER_STATEMENT:
                text = e.payload.get("text", "")
                self._observe_user(text, e.ts)
                pending_memory = e
            elif e.kind == "assistant_output":
                pass
            elif e.kind == "runtime_observation":
                self.accept_runtime(e)
        if pending_memory is not None:
            self.memory.add(pending_memory.payload.get("text", ""),
                            SourceType.USER_STATEMENT, 0.35, now=pending_memory.ts)
        # Runtime facts describe this process, never a historical model claim.
        for key, value in self.time.runtime_facts().items():
            self.state.propose(key, value, SourceType.RUNTIME, Scope.TURN)
