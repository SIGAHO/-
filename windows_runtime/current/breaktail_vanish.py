"""Short local farewell animation: body pixels become stars and bat-shaped mist."""
from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw


KEY = (255, 0, 255)
WIDTH, HEIGHT = 480, 300
STAR_COLORS = ((255, 249, 206), (153, 235, 255), (240, 169, 255),
               (255, 215, 135))


def pixel_threshold(x: int, y: int) -> float:
    """Stable six-pixel clusters with finer breakup along each edge."""
    cluster = ((x // 6 * 193 + y // 6 * 397 + (x // 6 * y // 6) * 23) % 997) / 997
    fleck = ((x * 73 + y * 151 + x * y * 17) % 991) / 991
    return 0.72 * cluster + 0.28 * fleck


def dissolve_sprite(source: Image.Image, progress: float) -> Image.Image:
    """Keep the original body visible while randomly exposing star-colored pixels."""
    original = source.convert("RGBA")
    output = original.copy()
    pixels = output.load()
    progress = max(0.0, min(1.0, progress))
    for y in range(output.height):
        for x in range(output.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha < 32:
                continue
            threshold = pixel_threshold(x, y)
            if threshold < progress:
                pixels[x, y] = (0, 0, 0, 0)
            elif threshold < progress + 0.12 and (x + 2*y) % 4 == 0:
                color = STAR_COLORS[(x + y) % len(STAR_COLORS)]
                pixels[x, y] = (*color, alpha)
    return output


def draw_star(draw: ImageDraw.ImageDraw, x: float, y: float,
              size: float, color: tuple[int, int, int]):
    x, y, size = round(x), round(y), max(1, round(size))
    draw.line((x-size, y, x+size, y), fill=color, width=2)
    draw.line((x, y-size, x, y+size), fill=color, width=2)
    draw.point((x, y), fill=(255, 255, 255))


def draw_bat(draw: ImageDraw.ImageDraw, x: float, y: float,
             size: float, flap: float, color: tuple[int, int, int]):
    """Tiny winged silhouette that can dissolve into the same purple mist."""
    x, y, size = round(x), round(y), max(4, round(size))
    wing = round(size * (0.35 + flap * 0.35))
    points = [(x-size, y-wing), (x-size//2, y-wing//3),
              (x-size//4, y+size//4), (x, y),
              (x+size//4, y+size//4), (x+size//2, y-wing//3),
              (x+size, y-wing), (x+size//2, y+size//3),
              (x+size//5, y+size//4), (x, y+size//2),
              (x-size//5, y+size//4), (x-size//2, y+size//3)]
    draw.polygon(points, fill=color)
    draw.line(points + [points[0]], fill=(155, 111, 171), width=1)
    draw.point((x-2, y), fill=(255, 184, 230))
    draw.point((x+2, y), fill=(255, 184, 230))


class VanishEffect:
    def __init__(self, source: Image.Image, center: tuple[float, float], seed: int = 49):
        self.source = source.convert("RGBA").resize((96, 96), Image.Resampling.NEAREST)
        self.center = center
        rng = random.Random(seed)
        visible = [(x, y) for y in range(0, 96, 2) for x in range(0, 96, 2)
                   if self.source.getpixel((x, y))[3] > 80]
        self.stars = []
        for x, y in rng.sample(visible, min(130, len(visible))):
            dx, dy = x - 48, y - 48
            angle = math.atan2(dy - 25, dx) + rng.uniform(-0.7, 0.7)
            speed = rng.uniform(55, 165)
            self.stars.append((x, y, pixel_threshold(x, y),
                               math.cos(angle)*speed, math.sin(angle)*speed,
                               rng.randint(2, 5), rng.choice(STAR_COLORS)))
        self.mist = [(rng.uniform(-35, 35), rng.uniform(-28, 26),
                      rng.uniform(-140, 140), rng.uniform(-90, 5),
                      rng.uniform(18, 36), rng.uniform(0, 0.22))
                     for _ in range(22)]
        self.bats = [(rng.uniform(-20, 20), rng.uniform(-10, 20),
                      rng.uniform(-185, 185), rng.uniform(-145, -35),
                      rng.uniform(13, 23), rng.uniform(0.12, 0.43))
                     for _ in range(11)]
        self.bats.extend(((-18, 4, -220, -80, 24, 0.16),
                          (18, -2, 220, -100, 27, 0.2)))

    def render(self, progress: float) -> Image.Image:
        progress = max(0.0, min(1.0, progress))
        frame = Image.new("RGB", (WIDTH, HEIGHT), KEY)
        draw = ImageDraw.Draw(frame)
        cx, cy = self.center
        # Open-ended wisps and stipple read as mist without covering the desktop.
        for index, (ox, oy, vx, vy, radius, born) in enumerate(self.mist):
            if progress < born or progress >= 0.93:
                continue
            age = progress - born
            x = cx + ox + vx * age
            y = cy + oy + vy * age - 15 * age * age
            r = radius * (0.65 + age * 1.4)
            color = ((54, 35, 69), (91, 65, 99), (128, 104, 139))[index % 3]
            for step in range(3):
                px = x + (step-1) * r * 0.65
                py = y + math.sin(step * 2 + index) * r * 0.28
                draw.arc((px-r*0.65, py-r*0.35, px+r*0.65, py+r*0.35),
                         170 + index*17 % 55, 345 + step*12,
                         fill=color, width=2 if index % 3 == 0 else 1)
            for dot in range(7):
                hx = round(x + ((index*13+dot*19) % 23 - 11) * r / 10)
                hy = round(y + ((index*7+dot*11) % 19 - 9) * r / 13)
                draw.rectangle((hx, hy, hx+1, hy+1), fill=color)
        body_progress = min(1.0, progress / 0.78)
        body = dissolve_sprite(self.source, body_progress)
        frame.paste(body, (round(cx-48), round(cy-48)), body)
        for index, (ox, oy, vx, vy, size, born) in enumerate(self.bats):
            if born <= progress < 0.88:
                age = progress - born
                draw_bat(draw, cx+ox+vx*age, cy+oy+vy*age, size,
                         math.sin(progress*38+index)*0.5+0.5,
                         ((38, 23, 52), (72, 41, 80), (105, 65, 112))[index % 3])
        for x, y, born, vx, vy, size, color in self.stars:
            start = born * 0.7
            if progress < start or progress >= 0.99:
                continue
            age = progress - start
            if progress > 0.81 and (round(progress*50) + x) % 5 < 2:
                continue
            px = cx + x - 48 + vx*age
            py = cy + y - 48 + vy*age - age*age*18
            if 0 <= px < WIDTH and 0 <= py < HEIGHT:
                draw_star(draw, px, py, size*(1-age*0.6), color)
        return frame

