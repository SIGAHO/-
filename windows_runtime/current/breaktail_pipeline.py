"""Additive pipeline-contract instrumentation for Breaktail.

This module deliberately does not choose wording or replace the 14B.  It makes
the whole desired architecture observable while retaining existing v0.2 routes.
Every record is append-only and safe to ignore by older Trace readers.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

from breaktail_working_state import recent_entity_states
from breaktail_values import value_projection


PIPELINE_SCHEMA_VERSION = 2

STAGES = (
    "input_normalization", "conversation_intent", "working_state",
    "correction_resolver", "recent_entity_state", "memory_retrieval",
    "runtime_facts", "passive_continuity", "self_core", "value_state",
    "relationship_state", "persona_projection", "context_assembler",
    "fast_path", "generation_14b", "capability_self_grounding",
    "correction_grounding", "conversation_policy", "postprocess",
    "persistence", "display",
)


def _summary(value: Any) -> dict[str, Any]:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        text = repr(value)
    return {
        "count": 0 if not text else 1,
        "chars": len(text),
        "token_estimate": (len(text) + 3) // 4,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        "preview": text[:240],
    }


def normalize_input(user_text: str) -> str:
    """A non-semantic normalization suitable for routing and tracing only."""
    return re.sub(r"\s+", " ", user_text or "").strip()


def minimal_intent(user_text: str) -> dict[str, str]:
    """Small routing hint, explicitly not a classifier or a personality label."""
    text = normalize_input(user_text)
    if re.fullmatch(r"(?:[ぁ-んァ-ヶー!！wWｗ\s]{1,20}|草+|笑+)", text):
        return {"mode": "social_reaction", "reason": "short_affective_utterance"}
    if re.search(r"どう返(?:す|したら)|返事", text):
        return {"mode": "direct_reply_request", "reason": "explicit_reply_request"}
    if re.search(r"訂正|違う|じゃなくて|ではなく", text):
        return {"mode": "possible_correction", "reason": "explicit_correction_marker"}
    casual_state = re.fullmatch(r"(?:今日(?:は)?|マジで|ちょっと)?(?:だるい|眠い|しんどい|疲れた|もう無理)[…。、！!〜ー]*", text)
    explicit_help = re.search(r"(?:どうす(?:れ|れば)|助け|対策|方法|教えて|できる|したい|[？?])", text)
    if casual_state and not explicit_help:
        return {"mode": "casual_state_share", "reason": "short_state_without_explicit_help_request"}
    personal_discovery = re.search(
        r"(?:最近|急に).{0,32}(?:気づいた|好きになった|面白くなった|楽しくなった)", text
    )
    if personal_discovery and not explicit_help:
        return {"mode": "personal_discovery_share", "reason": "personal_change_without_explicit_help_request"}
    personal_experience = re.search(
        r"(?:俺|おれ|僕|私).{0,72}(?:したこと(?:も)?あ(?:る|った)|行った|やった|楽しんだ|歌った)", text
    )
    if personal_experience and not explicit_help:
        return {"mode": "personal_experience_share", "reason": "personal_experience_without_explicit_help_request"}
    shared_observation = re.search(
        r".{1,36}(?:って|とは).{0,20}(?:人柄|個性|十人十色|面白い).{0,12}(?:だよね|よね)", text
    )
    if shared_observation and not explicit_help:
        return {"mode": "shared_observation", "reason": "concrete_observation_without_explicit_help_request"}
    return {"mode": "free_chat", "reason": "no_minimal_route"}


def intent_prompt_rule(intent: dict[str, str]) -> dict[str, str] | None:
    """Return only bounded request-shape rules that have observed failures."""
    if intent.get("mode") == "direct_reply_request":
        return {
            "id": "direct_reply_only",
            "instruction": "ユーザーは返し方の解説ではなく、そのまま送れる返答だけを求めている。説明・選択肢・前置きは付けず、返答本文だけを出す。",
        }
    if intent.get("mode") == "social_reaction":
        return {
            "id": "mirror_short_affect",
            "instruction": "短い感情・相づちには、相手の勢いまたは温度に釣り合う短い自然な返しをする。"
                           "頼まれていない健康助言、事情聴取、問題解決、一般論を始めない。質問は必要な時だけにする。",
        }
    if intent.get("mode") == "casual_state_share":
        return {
            "id": "acknowledge_casual_state",
            "instruction": "短い状態共有には、まず自然な共感・相づちを一、二文で返す。ユーザーが助けや方法を求めていない限り、"
                           "健康助言、診断、休息手順、一般論、事情聴取を始めない。問題解決を求める明示的な依頼があればこの方針は使わない。",
        }
    if intent.get("mode") == "personal_discovery_share":
        return {
            "id": "reflect_personal_discovery",
            "instruction": "ユーザーは自分の興味や感覚の変化を共有している。まずその発見を自然に受け取る。次に、発言内の変化や対比を一つ拾い、"
                           "今回の本人にとってどういう意味がありそうかという自分の見方を自然に一段だけ足す。単なる言い換えで終えず、二文の型にも固定しない。"
                           "頼まれていない手順、計画、自己改善の助言、一般論を始めない。方法や案を明示的に求められた時だけ提案する。",
        }
    if intent.get("mode") == "personal_experience_share":
        return {
            "id": "respond_to_personal_experience",
            "instruction": "ユーザーは自分の具体的な経験を話している。まずその中の一つの具体的な場面に自然に反応する。次に、その場面から見える今回らしい意味や"
                           "面白さを、自分の見方として一段だけ足す。抽象的な総評や人格分析にはせず、二文の型にも固定しない。"
                           "頼まれていない助言、教訓、励ましの結論、箇条書き、一般論を足さない。",
        }
    if intent.get("mode") == "shared_observation":
        return {
            "id": "extend_shared_observation",
            "instruction": "ユーザーは具体的な観察を共有している。まず観察そのものを受け取り、次に発言にある具体物から自分の見方を一段だけ足す。"
                           "同意の言い換え、一般論、性格診断、助言に逃げず、二文の型にも固定しない。",
        }
    return None


def correction_candidate(user_text: str) -> dict[str, Any]:
    """Conservative detector; it only reports evidence and never mutates state."""
    text = normalize_input(user_text)
    match = re.search(r"(?:訂正(?:する|です)?|違う(?:よ)?|じゃなくて|ではなく)", text)
    return {"candidate": bool(match), "evidence": match.group(0) if match else None,
            "reason": "explicit_marker" if match else "no_explicit_marker"}


def resolve_user_correction_constraints(history: list[dict] | None, user_text: str,
                                        max_user_turns: int = 12) -> list[dict[str, str]]:
    """Project only two explicit, safety-relevant user corrections into this turn.

    This is deliberately not a broad correction classifier. It does not infer
    preferences from explanations and does not persist state; the evidence must
    still be present in the current conversation history.
    """
    user_turns = [item.get("content", "") for item in (history or [])
                  if item.get("role") == "user" and isinstance(item.get("content"), str)]
    if user_text:
        user_turns.append(user_text)
    user_turns = user_turns[-max_user_turns:]
    resolved: dict[str, dict[str, str]] = {}
    media_correction = re.compile(
        r"[見み]て(?:い)?な(?:い)?.{0,16}[見み]たかのような(?:発言|はつげん|感想).{0,10}(?:やめ|しないで|するな)"
    )
    dishonesty_correction = re.compile(r"(?:嘘|噓).{0,8}(?:つかないで|つくな|言わないで|断定しないで)")
    for source in user_turns:
        compact = re.sub(r"\s+", "", source)
        # A quoted sentence supplied for proofreading is not evidence that the
        # user is correcting Breaktail. Keep this exclusion deliberately
        # narrow; ordinary correction wording remains authoritative.
        if re.match(r"(?:この|次の)?(?:文章|文|テキスト|台詞)を(?:訂正|修正|校正|翻訳)して[:：]", compact):
            continue
        if media_correction.search(compact):
            key = "no_claimed_media_experience"
            resolved[key] = {
                "id": key,
                "instruction": "作品を実際に視聴・体験したと主張しない。作品情報として知っている事実と、自分の視聴経験や感想を分け、経験がないならそう伝える。",
                "scope": "current_conversation",
                "evidence_hash": hashlib.sha256(source.encode("utf-8")).hexdigest()[:16],
            }
        if dishonesty_correction.search(compact):
            key = "no_unsupported_claims"
            resolved[key] = {
                "id": key,
                "instruction": "未確認の事実や実行していない行為を断定しない。分かる範囲と不確かな部分を区別する。",
                "scope": "current_conversation",
                "evidence_hash": hashlib.sha256(source.encode("utf-8")).hexdigest()[:16],
            }
    return list(resolved.values())


_FIRST_PERSON_MEDIA_CLAIM = re.compile(
    r"(?:私|僕|俺|自分)(?:は|が)?[^。！？\n]{0,18}(?:見(?:た|て)|観(?:た|て)|視聴(?:した|して))"
)


def ground_correction_reply(reply: str, constraints: list[dict[str, str]] | None) -> tuple[str, dict[str, Any]]:
    """Apply one narrow post-generation guard for an explicit media-experience correction.

    A complete safe fallback is preferred to an unsafe word replacement: the
    latter can leave the false first-person claim in another clause. Nothing is
    changed without both user-authored constraint evidence and an explicit
    first-person viewing claim in the draft.
    """
    active = {item.get("id") for item in (constraints or [])}
    if "no_claimed_media_experience" not in active:
        return reply, {"status": "not_invoked", "adjusted": False,
                       "decision": "no_media_experience_constraint", "reason": "no_matching_user_constraint"}
    if not _FIRST_PERSON_MEDIA_CLAIM.search(reply or ""):
        return reply, {"status": "invoked_empty", "adjusted": False,
                       "decision": "media_claim_scan", "reason": "no_explicit_first_person_viewing_claim"}
    safe_reply = "実際に見た経験としては言えない。作品情報として分かる範囲なら、視聴経験や感想とは分けて話す。"
    return safe_reply, {"status": "invoked_used", "adjusted": True,
                        "decision": "replace_explicit_media_experience_claim",
                        "reason": "user_correction_has_priority_over_draft_claim",
                        "rule_id": "no_claimed_media_experience"}


class PipelineObserver:
    """Writes schema-v2 spans through Breaktail's existing trace callback."""

    def __init__(self, trace: dict | None, emit: Callable[..., None]):
        self.trace = trace
        self.emit = emit

    def record(self, stage: str, status: str, input_value: Any = None,
               output_value: Any = None, decision: str = "", reason: str = "",
               provenance: list[str] | None = None, error: str | None = None,
               latency_ms: float | None = None) -> None:
        if not self.trace:
            return
        self.emit(self.trace, "stage_span", schema_version=PIPELINE_SCHEMA_VERSION,
                  stage=stage, status=status, input_summary=_summary(input_value),
                  output_summary=_summary(output_value), latency_ms=latency_ms,
                  latency_source="runtime-measured" if latency_ms is not None else "not-measured",
                  decision=decision, reason=reason, provenance=provenance or [], error=error)

    def bootstrap(self, user_text: str, working_state: dict, continuity_meta: dict,
                  self_context: dict, continuity_section: str = "",
                  history: list[dict] | None = None) -> dict[str, Any]:
        normalized = normalize_input(user_text)
        intent = minimal_intent(normalized)
        intent_rule = intent_prompt_rule(intent)
        correction = correction_candidate(normalized)
        correction_constraints = resolve_user_correction_constraints(history, user_text)
        values = value_projection(normalized)
        self.record("input_normalization", "invoked_used", user_text, normalized,
                    "whitespace_normalized", "non-semantic normalization", ["user_input"])
        self.record("conversation_intent", "invoked_used" if intent_rule else "invoked_empty",
                    normalized, {"intent": intent, "rule": intent_rule},
                    intent_rule["id"] if intent_rule else "no_connected_intent_rule",
                    "direct reply, short affect, and explicit-help-free state-sharing rules are connected; other modes remain observational",
                    ["input_normalization", "breaktail_pipeline"])
        self.record("working_state", "invoked_used", normalized, working_state,
                    "existing_state_updater", "v0.2 working state", ["breaktail_working_state"])
        self.record("correction_resolver", "invoked_used" if correction_constraints else "invoked_empty",
                    {"current_input": normalized, "prior_user_turns": sum(
                        item.get("role") == "user" for item in (history or []))},
                    correction_constraints, "project_scoped_explicit_constraints" if correction_constraints else "no_supported_rule",
                    "narrow explicit honesty/media-experience patterns; session-local, no persistence",
                    ["user_history", "breaktail_pipeline"] if correction_constraints else ["user_history"])
        entity_states = recent_entity_states(working_state)
        self.record("recent_entity_state", "invoked_used" if entity_states else "invoked_empty",
                    normalized, entity_states,
                    "explicit_consumable_state" if entity_states else "no_supported_entity_transition",
                    "newest explicit consumable state overrides an older retained state",
                    ["breaktail_working_state"] if entity_states else [])
        self.record("runtime_facts", "invoked_used", normalized, self_context.get("runtime_context", {}),
                    "build_self_context", "existing runtime facts", ["breaktail_self"])
        self.record("passive_continuity", "invoked_used" if continuity_section else "invoked_empty",
                    normalized, continuity_section, "prepare_user_turn", "existing continuity state", ["breaktail_passive_continuity"])
        self.record("self_core", "invoked_used", normalized, {"name": "Breaktail", "model": "qwen2.5:14b"},
                    "code_owned_identity", "identity is code/runtime-fact owned", ["breaktail_self"])
        self.record("value_state", "invoked_used" if values else "invoked_empty", normalized, values or {"axes": []},
                    "provisional_judgment_projection" if values else "no_direct_stance_request",
                    "bounded current-turn axes; not persistent ideology or user profile",
                    ["breaktail_values"] if values else [])
        mode = working_state.get("mode", {})
        roleplay_active = bool(mode.get("active") and mode.get("type") == "roleplay")
        relationship = {
            "scope": "current_roleplay" if roleplay_active else "none",
            "signals": ["playful_roleplay"] if roleplay_active else [],
            "constraints": list(mode.get("constraints", [])) if roleplay_active else [],
            "prohibited": ["forced_exclusivity", "isolation", "threats", "guilt_binding"],
            "persistent": False,
        }
        self.record("relationship_state", "invoked_used" if roleplay_active else "invoked_empty",
                    normalized, relationship,
                    "roleplay_boundary_projection" if roleplay_active else "no_active_relationship_context",
                    "existing roleplay prompt permits expression but forbids coercion and isolation; no relationship profile is retained",
                    ["breaktail_working_state", "breaktail_v02"] if roleplay_active else [])
        register = working_state.get("register", {})
        self.record("persona_projection", "invoked_used" if register.get("style") else "invoked_empty",
                    normalized, register, "explicit_register_preference" if register.get("style") else "no_explicit_register",
                    "only explicit user register preference is projected; no style inference",
                    ["breaktail_working_state"] if register.get("style") else [])
        return {"normalized": normalized, "intent": intent, "intent_rule": intent_rule, "correction": correction,
                "correction_constraints": correction_constraints, "value_projection": values}

    def missing_after_generation(self, draft: str, final: str,
                                 correction_grounding: dict[str, Any] | None = None) -> None:
        if correction_grounding:
            self.record("correction_grounding", correction_grounding["status"], draft, final,
                        correction_grounding["decision"], correction_grounding["reason"],
                        ["breaktail_pipeline"] if correction_grounding["status"] != "not_invoked" else [])
        else:
            self.record("correction_grounding", "not_invoked", draft, final,
                        "fast_path_or_legacy_route", "no free-chat correction grounding ran", [])
        self.record("conversation_policy", "invoked_used", draft, final,
                    "existing_reply_policy", "REPLY_SYSTEM and postprocess", ["REPLY_SYSTEM"])

