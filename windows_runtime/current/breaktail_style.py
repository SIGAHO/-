"""RAM-only observations of user speech and explicit response preferences."""

QUESTION_WORDS = ("どこ", "なに", "何", "誰", "いつ", "なぜ", "なんで", "あるの", "ないの")
CORRECTION_WORDS = ("違う", "ちがう", "返すな", "聞いてるんだけど", "聞いてるの", "そうじゃない")
DIRECT_ANSWER_WORDS = ("質問を", "聞いてるんだけど", "答えて", "どこの国", "具体的")


def make_style_report(samples: list[dict], model: str = "", url: str = "") -> dict:
    """Describe observable turns, not unsupported traits or model behavior."""
    if len(samples) < 6:
        raise ValueError("レポートには、この起動中の発言が最低6件必要です。")

    recent = samples[-60:]
    questions = []
    corrections = []
    direct_answer_requests = []
    for number, item in enumerate(recent, 1):
        user_text = item["user"]
        if ("?" in user_text or "？" in user_text
                or any(word in user_text for word in QUESTION_WORDS)):
            questions.append({"number": number, "quote": user_text})
        if any(word in user_text for word in CORRECTION_WORDS):
            corrections.append({"number": number, "quote": user_text})
        if any(word in user_text for word in DIRECT_ANSWER_WORDS):
            direct_answer_requests.append({"number": number, "quote": user_text})

    return {
        "sample_count": len(recent),
        "questions": questions,
        "corrections": corrections,
        "direct_answer_requests": direct_answer_requests,
        "scope": "この起動中の会話だけ",
        "limit": "話題や場面が限られているため、恒常的な性格・口癖・好みは判定しない",
    }


def print_style_report(report: dict) -> None:
    print("\n発言観測レポート（RAM上・未学習）")
    print(f"対象: {report['scope']}、ユーザー発言 {report['sample_count']}件")
    print("質問らしい発言:")
    if report["questions"]:
        for item in report["questions"]:
            print(f"  [{item['number']}] {item['quote']}")
    else:
        print("  この範囲では見つからない")
    if report["direct_answer_requests"]:
        print("この会話で明示された返答への要求: 質問の対象に具体的に答えること")
        print("  根拠: " + " / ".join(
            f"[{item['number']}] {item['quote']}"
            for item in report["direct_answer_requests"]
        ))
    print("明示的な訂正・要求:")
    if report["corrections"]:
        for item in report["corrections"]:
            print(f"  [{item['number']}] {item['quote']}")
    else:
        print("  この範囲では見つからない")
    print("判断しないこと: " + report["limit"])
    print("これは発言の観測であって、Breaktailが学習した結果ではありません。")
