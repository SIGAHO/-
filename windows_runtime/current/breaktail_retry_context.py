"""Build a retry prompt without discarding the evidence from the first attempt.

The rejected assistant draft is deliberately NOT part of this message list.
Keep source-backed memory, selected character, instructions, and recent dialogue.
When the context is full, remove the oldest message pairs before giving up.
"""

from __future__ import annotations


def estimate_tokens(messages):
    # Same conservative character heuristic as the main prompt composer.
    return 32 + sum(
        sum(1 if ord(c) < 128 else (2 if ord(c) < 65536 else 4)
            for c in item.get("content", "")) + 16
        for item in messages
    )


def build_retry_messages(messages, repair_rule, num_ctx, reserve=512):
    """Return (messages, audit) with system evidence and final user turn intact.

    Never include the failed assistant draft as a style example. If no
    additional instruction fits, preserve the original valid prompt rather
    than sending an over-budget prompt or dropping verified evidence.
    """
    if len(messages) < 2 or messages[0].get("role") != "system" or messages[-1].get("role") != "user":
        raise ValueError("retry expects a system message followed by a user turn")
    if num_ctx <= reserve:
        raise ValueError("context window has no retry budget")

    original = [dict(item) for item in messages]
    retry = [dict(item) for item in messages]
    retry[0]["content"] += "\n\n[再生成で直す条件。元の会話と根拠を維持する]\n" + repair_rule
    limit = num_ctx - reserve
    dropped = 0

    # Remove complete earlier pairs where possible; preserve the current user
    # and never remove trusted source excerpts stored in the system message.
    while estimate_tokens(retry) > limit and len(retry) > 2:
        if len(retry) > 3 and retry[1].get("role") == "user" and retry[2].get("role") == "assistant":
            del retry[1:3]
            dropped += 2
        else:
            del retry[1]
            dropped += 1

    if estimate_tokens(retry) > limit:
        if estimate_tokens(original) > limit:
            raise ValueError("original conversation prompt exceeds context budget")
        return original, {
            "repair_rule_injected": False,
            "dropped_history_messages": 0,
            "reason": "repair_rule_exceeds_context_budget",
            "prompt_token_estimate": estimate_tokens(original),
        }

    return retry, {
        "repair_rule_injected": True,
        "dropped_history_messages": dropped,
        "reason": "preserved_evidence",
        "prompt_token_estimate": estimate_tokens(retry),
    }
