"""Breaktail resident process. Stop with Ctrl+C; no automatic PC actions."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from companion_core.encoding import configure_stdio
from companion_core.daemon import CompanionDaemon
from companion_core.runtime import OSRuntimeObserver
from companion_core.model_adapter import FakeModelAdapter, OllamaAdapter


def main(argv=None):
    configure_stdio()
    parser = argparse.ArgumentParser(description="Breaktail v2 resident companion")
    parser.add_argument("--event-log", default=os.environ.get("BREAKTAIL_EVENT_LOG", "data/events.jsonl"))
    parser.add_argument("--interval", type=float, default=os.environ.get("BREAKTAIL_OBSERVE_INTERVAL", "30"))
    parser.add_argument("--foreground", action="store_true", help="ウィンドウタイトル取得を明示的に有効化")
    parser.add_argument("--model")
    parser.add_argument("--host")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args(argv)
    daemon = None
    try:
        adapter = FakeModelAdapter() if args.fake else OllamaAdapter(args.model, args.host, args.timeout)
        daemon = CompanionDaemon(adapter, args.event_log, OSRuntimeObserver(args.foreground), args.interval)
        print("Breaktail daemon: 常駐開始。終了はCtrl+C。", flush=True)
        daemon.run()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"常駐できません: {exc}", file=sys.stderr)
        return 1
    finally:
        if daemon is not None:
            daemon.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
