import tempfile
import unittest
import sqlite3
from pathlib import Path
from io import BytesIO

from PIL import Image

from breaktail_screen_memory import ScreenMemory, visual_signature


class ScreenMemoryTests(unittest.TestCase):
    def test_visual_signature_matches_similar_layout_not_unrelated_one(self):
        image = Image.new("RGB", (80, 80), "black")
        for x in range(40):
            for y in range(80):
                image.putpixel((x, y), (220, 220, 220))
        buffer = BytesIO()
        image.save(buffer, "JPEG")
        left = visual_signature(buffer.getvalue())
        image = Image.new("RGB", (80, 80), "black")
        for x in range(40, 80):
            for y in range(80):
                image.putpixel((x, y), (220, 220, 220))
        buffer = BytesIO()
        image.save(buffer, "JPEG")
        right = visual_signature(buffer.getvalue())
        self.assertNotEqual(left, right)

    def test_repeated_observations_are_scene_matched_and_legacy_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            old_path = Path(folder) / "screen.sqlite3"
            db = sqlite3.connect(old_path)
            try:
                db.execute("""CREATE TABLE observations (category TEXT NOT NULL, summary TEXT NOT NULL,
                    seen_count INTEGER NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
                    PRIMARY KEY (category, summary))""")
                db.execute("INSERT INTO observations VALUES ('ゲーム画面','古い記録',1,1,1)")
                db.commit()
            finally:
                db.close()
            memory = ScreenMemory(Path(folder) / "screen.sqlite3")
            memory.remember("ゲーム画面", "明るい広場が見えるね。", "800000000000000000")
            memory.remember("ゲーム画面", "明るい広場が見えるね。", "800000000000000001")
            memory.remember("ゲーム画面", "暗い洞窟が見えるね。", "20ffffffffffffffff")
            memory.remember("作業画面", "入力欄があるね。", "800000000000000000")
            matches = memory.recent("ゲーム画面", "800000000000000000")
            self.assertEqual([(m["summary"], m["seen_count"]) for m in matches],
                             [("明るい広場が見えるね。", 2)])
            self.assertEqual(memory.recent("ゲーム画面", "20ffffffffffffffff")[0]["summary"],
                             "暗い洞窟が見えるね。")
            self.assertEqual(memory.recent("作業画面", "20ffffffffffffffff"), [])
            self.assertEqual(ScreenMemory(Path(folder) / "screen.sqlite3").count(), 3)
            self.assertEqual(memory.legacy_recent("ゲーム画面")[0]["summary"], "古い記録")
            self.assertEqual(memory.recent("ゲーム画面", "800000000000000000")[0]["summary"],
                             "明るい広場が見えるね。")

    def test_wiki_reference_retains_url_and_expires(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            memory = ScreenMemory(Path(folder) / "screen.sqlite3")
            memory.remember_reference({"title": "Fish Radar", "excerpt": "A tool",
                "url": "https://fisch.wiki/wiki/fish-radar/", "checked_at": 1000})
            self.assertIsNone(memory.reference("Fish Radar", max_age_seconds=1))
            self.assertEqual(memory.reference("Fish Radar", max_age_seconds=10**12)["url"],
                             "https://fisch.wiki/wiki/fish-radar/")


if __name__ == "__main__":
    unittest.main()

