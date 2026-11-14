"""Game rules without creating a desktop window."""
import random
import unittest

from breaktail_fireworks_game import (FireworksGame, WIDTH, clamp, hits_circle,
                                     point_segment_distance)
from breaktail_pixel_art import slash_position, render, KEY


class FireworksGameTests(unittest.TestCase):
    def test_burst_spawns_bombs_and_hits_use_small_player_core(self):
        game = FireworksGame.__new__(FireworksGame)
        game.rng = random.Random(7)
        game.width, game.height = 1920, 1080
        game.boss_x, game.boss_y = 900, 300
        game.bombs = []
        game.explosions = []
        game.launch_firework(10)
        self.assertEqual(len(game.bombs), 18)
        self.assertEqual(len(game.explosions), 1)
        burst = game.explosions[0]
        self.assertTrue(all(b["x"] == burst["x"] and b["y"] == burst["y"]
                            for b in game.bombs))
        self.assertTrue(hits_circle(10, 10, 9, 25, 10, 7))
        self.assertFalse(hits_circle(10, 10, 9, 27, 10, 7))

    def test_scythe_sweeps_across_arena_and_collision_is_local(self):
        left = slash_position(WIDTH, 600, 0)
        right = slash_position(WIDTH, 600, 1)
        self.assertLess(left[0], WIDTH / 2)
        self.assertGreater(right[0], WIDTH / 2)
        self.assertEqual(clamp(-10, 0, 1), 0)
        self.assertEqual(point_segment_distance(50, 20, 0, 0, 100, 0), 20)
        self.assertGreater(point_segment_distance(50, 80, 0, 0, 100, 0), 16)

    def test_pixel_frame_keeps_desktop_key_and_draws_large_scythe(self):
        game = FireworksGame.__new__(FireworksGame)
        game.width, game.height = 900, 600
        game.explosions = []
        game.bombs = []
        game.black_hole = {"born": 10, "x": 450, "y": 300}
        game.scythe = {"born": 9, "direction": 1}
        game.player_x, game.player_y = 150, 450
        game.invulnerable_until = 0
        game.finished = False
        game.lives, game.score = 5, 90
        frame = render(game, 10)
        self.assertEqual(frame.size, (900, 600))
        self.assertEqual(frame.getpixel((450, 550)), KEY)
        self.assertNotEqual(frame.getpixel((450, 300)), KEY)

    def test_black_hole_pulls_player_and_bomb_after_warning(self):
        class Parent:
            def winfo_rootx(self): return 0
            def winfo_rooty(self): return 0
        class Window:
            def winfo_pointerx(self): return -1
            def winfo_pointery(self): return -1
        game = FireworksGame.__new__(FireworksGame)
        game.width, game.height = 900, 600
        game.keys = set()
        game.rng = random.Random(2)
        game.reset()
        game.parent, game.window = Parent(), Window()
        game.player_x, game.player_y = 500, 300
        game.black_hole = {"born": 8, "x": 400, "y": 300}
        game.next_black_hole = game.next_firework = game.next_scythe = float("inf")
        game.bombs = [{"x": 500, "y": 300, "vx": 0, "vy": 0, "radius": 9}]
        game.update(9, 0.05)
        self.assertLess(game.player_x, 500)
        self.assertLess(game.bombs[0]["x"], 500)


if __name__ == "__main__":
    unittest.main()

