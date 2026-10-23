"""Start a hidden resident daemon if needed, then attach the interactive chat."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from companion_core.daemon import DaemonClient
from companion_core.encoding import configure_stdio


def main():
    configure_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument('--event-log', default=os.environ.get('BREAKTAIL_EVENT_LOG', str(ROOT/'data/events.jsonl')))
    parser.add_argument('--fake', action='store_true')
    args = parser.parse_args()
    event_path = Path(args.event_log).resolve()
    event_path.parent.mkdir(parents=True, exist_ok=True)
    def ready():
        try:
            DaemonClient(event_path, timeout=1).status()
            return True
        except (OSError, ValueError, KeyError):
            return False
    extra = ['--fake'] if args.fake else []
    if not ready():
        output = Path(str(event_path)+'.daemon.log')
        with output.open('ab') as log:
            daemon = subprocess.Popen([sys.executable, str(ROOT/'daemon.py'), '--event-log', str(event_path), *extra],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        deadline = time.monotonic()+20
        while not ready():
            if daemon.poll() is not None or time.monotonic() >= deadline:
                print(f'daemon起動失敗。診断ログ: {output}', file=sys.stderr)
                return 1
            time.sleep(.1)
        print(f'daemon PID={daemon.pid}（chatを閉じても常駐）。終了: Stop-Process -Id {daemon.pid}')
    return subprocess.call([sys.executable, str(ROOT/'chat.py'), '--event-log', str(event_path), *extra], cwd=ROOT)

if __name__ == '__main__':
    raise SystemExit(main())
