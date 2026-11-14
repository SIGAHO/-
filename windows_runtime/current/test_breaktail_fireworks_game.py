"""Game rules without creating a desktop window."""
import random
import unittest

from breaktail_fireworks_game import (FireworksGame, WIDTH, clamp, hits_circle,
                                     point_segment_distance, scythe_tip)


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
        left = scythe_tip(0)
        right = scythe_tip(1)
        self.assertLess(left[0], WIDTH / 2)
        self.assertGreater(right[0], WIDTH / 2)
        self.assertEqual(clamp(-10, 0, 1), 0)
        self.assertEqual(point_segment_distance(50, 20, 0, 0, 100, 0), 20)
        self.assertGreater(point_segment_distance(50, 80, 0, 0, 100, 0), 16)


if __name__ == "__main__":
    unittest.main()

