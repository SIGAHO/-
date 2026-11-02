"""Fail-closed boundaries shared by extraction, registration and export."""
import hashlib
import json
import re
import unicodedata
from pathlib import Path


def normalized(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def target_hash(text):
    return hashlib.sha256(normalized(text).encode("utf-8")).hexdigest()


def blocked_reason(record):
    p = record.get("provenance", {})
    serialized = json.dumps(p, ensure_ascii=False).lower()
    if "failed_v1" in serialized or "failed-v1" in serialized:
        return "FAILED_V1 is permanently excluded"
    if (record.get("purpose") == "base_eval" or p.get("purpose") == "base_eval"
            or record.get("teacher_eligible") is False or p.get("teacher_eligible") is False):
        return "evaluation/reference material is not a teacher"
    if p.get("source") == "model_generated" or p.get("kind") in {"model", "model_generated", "synthetic_candidate"}:
        return "model-generated targets cannot become human teachers"
    if p.get("target_author") not in {"user", "human"}:
        return "verified human target authorship is required"
    if p.get("kind") not in {"raw_turn", "human_chat"}:
        return "unsupported human provenance"
    if p.get("kind") == "human_chat" and not all(p.get(k) is True for k in (
            "target_verified", "context_verified", "privacy_reviewed", "authorship_reviewed", "split_reviewed")):
        return "human chat requires source, privacy, authorship and split review"
    if not record.get("input_context"):
        return "context is required"
    registry = Path(__file__).with_name("phase8_base_eval_v1.jsonl")
    if registry.exists():
        blocked = {target_hash(json.loads(line)["actual_reply"]) for line in registry.read_text(encoding="utf-8").splitlines() if line.strip()}
        if target_hash(record.get("target_text", "")) in blocked:
            return "frozen BASE_EVAL_V1 output cannot become a teacher"
    return None
