"""Run from checkout: python chat.py"""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from companion_core.chat import ChatSession
from companion_core.model_adapter import FakeModelAdapter, OllamaAdapter, ModelError


def main(argv=None):
    # Preserve Japanese/emoji in both Windows consoles and redirected pipes.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Breaktail v2 — Companion Core + Ollama")
    parser.add_argument("--model", help="既定: BREAKTAIL_MODEL または qwen2.5:14b")
    parser.add_argument("--host", help="既定: OLLAMA_HOST または http://127.0.0.1:11434")
    parser.add_argument("--event-log", default=os.environ.get("BREAKTAIL_EVENT_LOG", "data/events.jsonl"))
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--fake", action="store_true", help="接続確認用。自然会話の評価には使わない")
    args = parser.parse_args(argv)
    try:
        adapter = FakeModelAdapter() if args.fake else OllamaAdapter(args.model, args.host, args.timeout)
        session = ChatSession(adapter, args.event_log)
    except (OSError, ValueError, KeyError) as exc:
        print(f"起動できません: {exc}", file=sys.stderr)
        return 1
    print("Breaktail v2" + (" [Fake接続テスト]" if args.fake else "") + " — /exit で終了。/correct キー 訂正文 で対象を指定して訂正。")
    while True:
        try:
            text = input("you> ").strip()
            if text in {"/exit", "/quit"}:
                break
            if not text:
                continue
            key = None
            if text.startswith("/correct "):
                parts = text.split(maxsplit=2)
                if len(parts) != 3:
                    print("使い方: /correct キー 訂正文")
                    continue
                _, key, text = parts
            print("Breaktail> " + session.turn(text, correction_key=key))
        except ModelError as exc:
            print(f"応答できません: {exc}\n入力は保存済みです。次の入力で続けられます。", file=sys.stderr)
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except OSError as exc:
            print(f"ログ保存に失敗: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
