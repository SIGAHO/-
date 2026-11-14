"""The goodbye animation preserves the source and ends fully transparent."""
import unittest

from PIL import Image

from breaktail_vanish import KEY, VanishEffect, dissolve_sprite


class VanishEffectTests(unittest.TestCase):
    def test_original_pixels_turn_into_stars_and_fully_disappear(self):
        source = Image.new("RGBA", (96, 96), (70, 90, 130, 255))
        original = source.copy()
        start = dissolve_sprite(source, 0)
        middle = dissolve_sprite(source, 0.5)
        end = dissolve_sprite(source, 1)
        count = lambda image: sum(alpha > 0 for *_, alpha in image.get_flattened_data())
        self.assertGreater(count(start), count(middle))
        self.assertGreater(count(middle), count(end))
        self.assertEqual(count(end), 0)
        self.assertEqual(source.tobytes(), original.tobytes())
        self.assertNotEqual(middle.getpixel((30, 30))[:3], (70, 90, 130))

    def test_mist_and_bats_leave_no_overlay_after_farewell(self):
        source = Image.new("RGBA", (96, 96), (90, 110, 130, 255))
        effect = VanishEffect(source, (240, 150))
        self.assertGreaterEqual(len(effect.stars), 100)
        self.assertEqual(effect.render(0.5).size, (480, 300))
        self.assertEqual(effect.render(1).getpixel((240, 150)), KEY)


if __name__ == "__main__":
    unittest.main()

