"""Exercise the patched reply/extract web handlers in an isolated ephemeral server."""
import json
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import breaktail_v02 as tail
import breaktail_web as web

ROOT = Path(__file__).resolve().parent
FIXTURE = "テスト用の保存記憶: ユーザーは返答を『要点、その次に注意点』の順で短くまとめるのを好む。"
HISTORY = [
    {"role": "user", "content": "次からその順番でまとめてほしい。"},
    {"role": "assistant", "content": "分かった。"},
]
CURRENT = "あの順番ってどんな形だった？"


def post(url, body):
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Breaktail-Token": web.TOKEN},
    )
    with urllib.request.urlopen(request, timeout=400) as response:
        return json.loads(response.read().decode("utf-8"))


def unload_qwen():
    payload = json.dumps({"model": tail.MODEL, "prompt": "", "stream": False, "keep_alive": 0}).encode("utf-8")
    request = urllib.request.Request(tail.OLLAMA_URL.rsplit("/api/chat", 1)[0] + "/api/generate", data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30):
            pass
    except Exception:
        pass


def main():
    with tempfile.TemporaryDirectory(prefix="breaktail-qwen-smoke-") as temp_dir:
        tail.MEMORY_FILE = Path(temp_dir) / "memory.jsonl"
        tail.MEMORY_FILE.write_text(json.dumps({"id": 1, "content": FIXTURE, "status": "unverified_interpretation"}, ensure_ascii=False) + "\n", encoding="utf-8")
        web.STATE.update(history=list(HISTORY), messages=[], scene=None, pending=None, busy=False)
        server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started = time.perf_counter()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            reply = post(base + "/api/reply", {"text": CURRENT})
            reply_seconds = round(time.perf_counter() - started, 2)
            extraction_started = time.perf_counter()
            extraction = post(base + "/api/extract", {"turn_id": reply["turn_id"]})
            extraction_seconds = round(time.perf_counter() - extraction_started, 2)
            result = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "model": tail.MODEL,
                "reply": reply["reply"],
                "reply_complete": reply["complete"],
                "extraction_warning": extraction["warning"],
                "extraction_saved_memory": bool(extraction["memory"]),
                "scene": extraction["scene"],
                "reply_seconds": reply_seconds,
                "extraction_seconds": extraction_seconds,
                "total_seconds": round(time.perf_counter() - started, 2),
                "isolated_state_message_count": len(web.STATE["messages"]),
                "test_memory_file_removed": True,
            }
            path = ROOT / "migration_web_smoke.json"
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print(f"Saved: {path}")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            unload_qwen()


if __name__ == "__main__":
    main()
