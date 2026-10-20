from __future__ import annotations
import time
from .models import Event, SourceType, Scope
from .event_store import EventStore
from .state import StateEngine
from .correction import CorrectionEngine
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

    def _trace(self, stage: str, detail: dict):
        self.trace.append({"ts": time.time(), "stage": stage, **detail})

    def handle(self, text: str, *, correction_key: str | None = None) -> dict:
        self.events.append(Event(kind="user_input", payload={"text": text}, source=SourceType.USER_STATEMENT))
        self._trace("user_input", {"text": text})

        tf = self.time.runtime_facts()
        for k, v in tf.items():
            self.state.propose(k, v, SourceType.RUNTIME, Scope.TURN)
        self._trace("runtime", tf)

        detected = self.corrections.detect(text)
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
            self.memory.add(f"{correction_key} = {c.new}", SourceType.USER_CORRECTION, 0.9)
            self._trace("correction", {
                "key": correction_key, "old": c.old, "new": c.new, "pattern": c.pattern
            })
        elif detected:
            self._trace("correction_proposal", {
                "items": [c.__dict__ for c in detected],
                "reason": "multiple_candidates" if correction_key else "missing_target",
            })

        topic = self.topic.update(text)
        self.open_loops.observe(text)
        emo = self.emotion.observe_user(text)
        self._trace("topic", {"current": topic.label if topic else None})
        self._trace("emotion", emo.to_dict())

        self.memory.add(text, SourceType.USER_STATEMENT, importance=0.35)
        memories = self.memory.retrieve(text)

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

    def replay(self) -> None:
        old = list(self.events.events)
        self.state = StateEngine()
        self.topic = TopicTracker()
        self.open_loops = OpenLoopTracker()
        self.memory = MemoryEngine()
        self.emotion = EmotionEngine()
        self.trace = []

        for e in old:
            if e.kind == "correction":
                p = e.payload
                self.state.correct(p["key"], p["new"], p.get("old"), Scope.SESSION)
            elif e.kind == "user_input":
                text = e.payload.get("text", "")
                self.topic.update(text)
                self.open_loops.observe(text)
                self.emotion.observe_user(text)
                self.memory.add(text, SourceType.USER_STATEMENT, 0.35)
            elif e.kind == "assistant_output":
                pass
