import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from companion_core import CompanionCore

core = CompanionCore()

samples = [
    ("今日はAIの設計をやる", None),
    ("あとでメモリの式も作る", None),
    ("今年は2023", None),
    ("違う、2026", "time.user_year"),
    ("感情も数式で外側に出したい！！！", None),
]

for text, key in samples:
    ctx = core.handle(text, correction_key=key)
    print("\nUSER:", text)
    print(json.dumps(ctx, ensure_ascii=False, indent=2))

core.record_assistant_output("これはAIが勝手に作った事実です")
print("\nAI output admitted to state?", "これはAIが勝手に作った事実です" in str(core.state.snapshot()))
