import tempfile
import unittest
from pathlib import Path

from breaktail_screen_memory import ScreenMemory


class ScreenMemoryTests(unittest.TestCase):
    def test_repeated_observations_are_local_bounded_and_retrievable(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            memory = ScreenMemory(Path(folder) / "screen.sqlite3")
            memory.remember("ゲーム画面", "明るい広場が見えるね。")
            memory.remember("ゲーム画面", "明るい広場が見えるね。")
            memory.remember("作業画面", "入力欄があるね。")
            self.assertEqual(memory.recent("ゲーム画面"),
                             [{"summary": "明るい広場が見えるね。", "seen_count": 2}])
            self.assertEqual(ScreenMemory(Path(folder) / "screen.sqlite3").count(), 2)
            for number in range(220):
                memory.remember("ゲーム画面", f"観察{number}")
            self.assertEqual(memory.count(), 200)


if __name__ == "__main__":
    unittest.main()

