from __future__ import annotations


class ContextAssembler:
    def build(self, *, user_input: str, state: dict, time_facts: dict, topic, open_loops, memories, emotion, trace_tail):
        return {
            "runtime": time_facts,
            "state": {k: v["value"] for k, v in state.items()},
            "topic": None if topic is None else {"label": topic.label, "score": round(topic.score, 3)},
            "open_loops": [x.text for x in open_loops[:8]],
            "memory": [x.text for x in memories],
            "emotion": {k: round(v, 3) for k, v in emotion.to_dict().items()},
            "user_input": user_input,
            "trace_tail": trace_tail[-12:],
        }
