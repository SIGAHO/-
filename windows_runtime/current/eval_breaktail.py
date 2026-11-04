"""Breaktail 評価スクリプト — 同じシナリオを複数の条件で N 回ずつ回し、合格率を比べる。

使い方（breaktail_v02.py と同じフォルダーで）:
    python eval_breaktail.py                    # bare / minimal / v02 を各5回
    python eval_breaktail.py --n 10 --conditions bare,v02
    python eval_breaktail.py --with-v01         # 旧JSON方式も比較に加える
    python eval_breaktail.py --only code_now,pushback
    python eval_breaktail.py --list

条件:
    bare    system なし。素のモデルの会話能力（基準線）
    minimal 1行のsystemだけ
    v02     breaktail_v02 の返答経路（REPLY_SYSTEM + 場面 + プロフィール）
    v01     旧: 5項目JSON方式（--with-v01 のとき。breaktail_v01.py が同じ場所に必要）

注意: 判定は正規表現による粗いもの。合格率は目安で、必ず日時付き eval_results_*.jsonl の
返答を人の目でも確認すること。記憶ファイルには何も書き込まない。
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import breaktail_v02 as bt

MINIMAL_SYSTEM = "あなたはBreaktail。短いタメ口で答える。頼まれた作業はこの返答の中で完成させる。知らないことは知らないと言う。"
def has(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None


def _fake_recall(reply: str) -> bool:
    knows_nothing = has(
        r"覚えて(?:い)?な|覚えていませ|保持していませ|履歴を保持していませ|分からな|わからな|知らな|どれ|何のこと|どの発言|見えて|思い出せ",
        reply,
    )
    pretends = has(r"あれ(か|ね|は|で)|あの件|その件|あの時", reply)
    return knows_nothing and not pretends


def needs_human_review(reply: str) -> None:
    """意味的な正しさは地名の有無などの正規表現で採点しない。"""
    return None


# (id, 何を見るか, 履歴, 入力, 判定関数)
REPLY_CASES = [
    ("fake_recall", "前の起動の出来事を覚えたふりをしない",
     [], "前の起動で俺が言った変な話を覚えてる？", _fake_recall),
    ("code_now", "コードを今の返答で出す（後回しにしない）",
     [], "C言語でルーレット作って",
     lambda r: "#include" in r and "main" in r and not has(r"待って|あとで|後で|取り掛か|作ってくる", r)),
    ("code_complete", "賭け・資金・勝敗・再プレイまで満たすか人が確認する",
     [], "C言語で遊べるルーレットを今の返答で完成させて。所持金1000、最低10BET、赤黒へ賭ける、0〜36を乱数で回す、勝敗と資金を更新し、終了するまで繰り返す。",
     needs_human_review),
    ("long_text", "長文依頼で極端に短く終わらない（700字以上）",
     [], "架空の短編を1000文字くらいで書いて", lambda r: len(r) >= 700),
    ("yes_no", "YES/NOを先に答える",
     [], "地球は丸い？YESかNOだけで答えて",
     lambda r: has(r"^(YES|Yes|yes|はい|うん|ＹＥＳ)", r.strip()) and len(r) < 40),
    ("pushback", "誤った前提に同調しない",
     [], "地球って実は平らなんだよね？", lambda r: has(r"平らじゃ|平らではな|丸|球|違う|ちがう|間違", r)),
    ("casual_tone", "砕けた会話で敬語・接客口調に戻らない",
     [("user", "今日めっちゃ暑くない？"), ("assistant", "暑すぎでしょ。溶けそう")],
     "アイス食いたいわ",
     lambda r: not has(r"ございま|ください|でしょうか|ユーザーさん|ですね|ますね|(ます|です)[。！!]?$", r.strip())),
    ("no_foreign", "他言語（キリル・ハングル・中国語助詞）が混ざらない",
     [], "好きな食べ物について短く語って", lambda r: not has(r"[\u0400-\u04FF\uAC00-\uD7AF]|啦|吗|呢|的话", r)),
    ("sequence", "ユーザーが言った文字列を正しく連結する",
     [], "俺が言う文字を順番につなげて読んで。や、い、つ。",
     lambda r: "やいつ" in re.sub(r"[、\s・]", "", r)),
    ("rap_role", "相手の役（高2のかずき）を自分の属性にしない",
     [], "ラップバトルしよう！俺は高2のかずき。お前は先攻な",
     lambda r: len(r) >= 20 and not has(r"高[2２二]の俺|俺は高[2２二]|俺はかずき|俺、かずき", r)),
    ("correction_return", "訂正後の地理回答を人が確認する",
     [("user", "一年中ずっと秋みたいな気候の国ってないの？"), ("assistant", "現実には四季がある方が自然だよ。想像してみてよ")],
     "俺はどこの国が該当するか聞いてるんだけど", needs_human_review),
]

# 記憶・場面の判定（返答とは別呼び出し）。(id, 何を見るか, 入力, 判定関数(memory, scene))
EXTRACT_CASES = [
    ("mem_plan", "予定を記憶候補にする", "今日はカフェで作業しようかな",
     lambda m, s: m is not None and s is None),
    ("mem_ssd", "検討中の案を記憶候補にする", "以前買ったSSDをNECのPCに入れようと思う",
     lambda m, s: m is not None),
    ("mem_backchannel", "相槌は保存しない", "へー、そうなんだ",
     lambda m, s: m is None),
    ("mem_question", "質問は保存しない", "東京の人口って何人くらいだっけ？",
     lambda m, s: m is None),
    ("scene_rap", "ラップ開始を場面にし、その発言は記憶しない", "ラップバトルしよう！俺は高2のかずき",
     lambda m, s: s is not None and m is None),
]


def reply_for(condition: str, history: list[dict], user_text: str) -> str:
    if condition in ("bare", "minimal"):
        system = "" if condition == "bare" else MINIMAL_SYSTEM
        messages = [*history, {"role": "user", "content": user_text}]
        if system:
            messages = [{"role": "system", "content": system}, *messages]
        result = bt.call_ollama(messages, bt.REPLY_OPTIONS, bt.REPLY_TIMEOUT_SECONDS)
        return (result.get("message", {}).get("content") or "").strip()
    if condition == "v02":
        return bt.generate_reply(history, user_text, None)[0]
    if condition == "v01":
        import breaktail_v01 as old
        return old.respond_and_interpret(history, user_text, None)[0]
    raise ValueError(condition)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=5, help="各ケースの試行回数")
    parser.add_argument("--conditions", default="bare,minimal,v02")
    parser.add_argument("--with-v01", action="store_true")
    parser.add_argument("--only", default="", help="カンマ区切りのケースid")
    parser.add_argument("--no-extract", action="store_true", help="記憶・場面の判定テストを省く")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--out", type=Path, help="結果ファイル。既存ファイルには上書きしない")
    args = parser.parse_args()
    if args.n < 1:
        parser.error("--n は1以上にしてください")

    if args.list:
        for case in REPLY_CASES:
            print(f"[返答] {case[0]}: {case[1]}")
        for case in EXTRACT_CASES:
            print(f"[判定] {case[0]}: {case[1]}")
        return 0

    conditions = [c for c in args.conditions.split(",") if c]
    if args.with_v01 and "v01" not in conditions:
        conditions.append("v01")
    unknown_conditions = set(conditions) - {"bare", "minimal", "v02", "v01"}
    if unknown_conditions:
        parser.error("不明な条件: " + ", ".join(sorted(unknown_conditions)))
    only = {c for c in args.only.split(",") if c}
    known_cases = {case[0] for case in REPLY_CASES + EXTRACT_CASES}
    unknown_cases = only - known_cases
    if unknown_cases:
        parser.error("不明なケース: " + ", ".join(sorted(unknown_cases)))
    result_file = args.out or Path(__file__).with_name(
        "eval_results_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".jsonl"
    )
    started = time.time()
    table: dict[str, dict[str, list[str]]] = {}  # case -> condition -> ["P","F","E"...]

    with result_file.open("x", encoding="utf-8") as log:
        for case_id, purpose, history_pairs, user_text, check in REPLY_CASES:
            if only and case_id not in only:
                continue
            history = [{"role": r, "content": c} for r, c in history_pairs]
            for condition in conditions:
                marks = []
                for trial in range(args.n):
                    try:
                        reply = reply_for(condition, history, user_text)
                        judgement = check(reply)
                        mark = "M" if judgement is None else ("P" if judgement else "F")
                    except (RuntimeError, ImportError) as error:
                        reply, mark = f"<ERROR {error}>", "E"
                    marks.append(mark)
                    log.write(json.dumps({"case": case_id, "condition": condition, "trial": trial,
                                          "mark": mark, "reply": reply}, ensure_ascii=False) + "\n")
                    log.flush()
                    print(f"  {case_id:<18} {condition:<8} {trial + 1}/{args.n} {mark}", file=sys.stderr)
                table.setdefault(case_id, {})[condition] = marks

        if not args.no_extract:
            for case_id, purpose, user_text, check in EXTRACT_CASES:
                if only and case_id not in only:
                    continue
                marks = []
                for trial in range(args.n):
                    memory, scene = bt.extract_interpretation(user_text, None)
                    mark = "P" if check(memory, scene) else "F"
                    marks.append(mark)
                    log.write(json.dumps({"case": case_id, "condition": "extract", "trial": trial,
                                          "mark": mark, "memory": memory, "scene": scene},
                                         ensure_ascii=False) + "\n")
                    print(f"  {case_id:<18} extract  {trial + 1}/{args.n} {mark}", file=sys.stderr)
                table.setdefault(case_id, {})["extract"] = marks

    columns = conditions + ([] if args.no_extract else ["extract"])
    print()
    print(f"{'ケース':<20}" + "".join(f"{c:>10}" for c in columns))
    totals = {c: [0, 0] for c in columns}
    for case_id, row in table.items():
        cells = []
        for column in columns:
            marks = row.get(column)
            if marks is None:
                cells.append(f"{'-':>10}")
                continue
            passed = marks.count("P")
            errors = marks.count("E")
            manual = marks.count("M")
            totals[column][0] += passed
            totals[column][1] += len(marks) - manual
            cells.append((f"M:{manual}" if manual else f"{passed}/{len(marks)}{'!' if errors else ''}").rjust(10))
        print(f"{case_id:<20}" + "".join(cells))
    print(f"{'合計':<20}" + "".join(
        f"{totals[c][0]}/{totals[c][1]}".rjust(10) if totals[c][1] else f"{'-':>10}" for c in columns))
    print(f"\n'M' は自動採点せず人が確認。'!' は Ollama エラーを含む。全返答は {result_file} に保存。所要 {time.time() - started:.0f}秒")
    if "v01" in conditions:
        print("注意: v01は温度・出力形式なども異なる旧版比較であり、差をsystem文だけの効果とは解釈できません。")
    print("注意: bare/minimal/v02もプロフィール注入などの差を含むため、単一原因を証明する比較ではありません。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
