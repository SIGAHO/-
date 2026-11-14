"""Low-resolution, color-keyed artwork for the desktop-wide bullet game."""
from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont


KEY = (255, 0, 255)
INK = "#121326"
CREAM = "#fff1c2"
GOLD = "#ffca68"
PINK = "#ff6b9d"
CYAN = "#83ecff"


def pixel_size(width: int, height: int) -> int:
    return max(2, min(width // 640, height // 360))


def slash_line(width: int, height: int, direction: int = 1) -> tuple[tuple[float, float], tuple[float, float]]:
    if direction > 0:
        return (-120, height * 0.18), (width + 120, height * 0.82)
    return (width + 120, height * 0.18), (-120, height * 0.82)


def slash_position(width: int, height: int, progress: float,
                   direction: int = 1) -> tuple[float, float]:
    a, b = slash_line(width, height, direction)
    p = max(0.0, min(1.0, progress))
    return a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p


def square(draw: ImageDraw.ImageDraw, x: int, y: int, r: int, color: str):
    draw.rectangle((x-r, y-r, x+r, y+r), fill=color)


def star(draw: ImageDraw.ImageDraw, x: int, y: int, r: int, color: str):
    square(draw, x, y, 1, CREAM)
    draw.rectangle((x-r, y, x+r, y), fill=color)
    draw.rectangle((x, y-r, x, y+r), fill=color)
    square(draw, x-r-2, y-1, 0, color)
    square(draw, x+r+2, y+1, 0, color)


def bomb(draw: ImageDraw.ImageDraw, x: int, y: int, tick: int):
    # Eight-bit beveled body, highlight, red rim, and a two-frame fuse.
    draw.rectangle((x-4, y-3, x+4, y+4), fill=INK)
    draw.rectangle((x-3, y-4, x+3, y+3), fill="#8c304b")
    draw.rectangle((x-2, y-3, x+2, y+2), fill="#342037")
    draw.rectangle((x-2, y-2, x-1, y-1), fill="#f49b9a")
    draw.rectangle((x+2, y+2, x+3, y+3), fill="#160d28")
    draw.line((x, y-4, x+1, y-7), fill=GOLD, width=1)
    square(draw, x+1+(tick % 2), y-8, 1, GOLD if tick % 2 else CREAM)


def player(draw: ImageDraw.ImageDraw, x: int, y: int, tick: int):
    # Small cyan ship with a visible white hit core.
    draw.polygon(((x, y-7), (x+5, y+4), (x+2, y+3), (x, y+1),
                  (x-2, y+3), (x-5, y+4)), fill=INK)
    draw.polygon(((x, y-6), (x+4, y+3), (x, y), (x-4, y+3)), fill=CYAN)
    draw.rectangle((x-1, y-1, x+1, y+1), fill=CREAM)
    draw.rectangle((x-2, y+5, x-1, y+7+(tick % 2)), fill=GOLD)
    draw.rectangle((x+1, y+5, x+2, y+7+(tick % 2)), fill=GOLD)


def pixel_scythe(draw: ImageDraw.ImageDraw, x: int, y: int, direction: int):
    """Oversized angular blade with an offset shadow and two shaded faces."""
    d = 1 if direction > 0 else -1
    # Handle and blade are deliberately stepped rather than smoothed.
    handle = [(x-52*d, y+48), (x-48*d, y+53), (x+16*d, y-22),
              (x+10*d, y-28)]
    draw.polygon([(px+4, py+5) for px, py in handle], fill="#170f2c")
    draw.polygon(handle, fill="#5e415d")
    draw.line((x-47*d, y+47, x+10*d, y-23), fill="#39253f", width=5)
    draw.line((x-49*d, y+48, x+12*d, y-25), fill="#e7b27d", width=2)
    for j in range(4):
        band_x = x - (40-j*13)*d
        band_y = y + 39-j*15
        draw.line((band_x-2*d, band_y+3, band_x+3*d, band_y-2),
                  fill="#e5be88", width=2)
    blade = [(x-2*d, y-28), (x+13*d, y-46), (x+43*d, y-62),
             (x+82*d, y-65), (x+99*d, y-57), (x+69*d, y-56),
             (x+47*d, y-46), (x+29*d, y-24), (x+17*d, y-1),
             (x+9*d, y-18)]
    draw.polygon([(px+5, py+6) for px, py in blade], fill="#261b38")
    draw.polygon(blade, fill="#e7f6ff")
    draw.polygon(((x+2*d, y-27), (x+17*d, y-43), (x+41*d, y-56),
                  (x+30*d, y-34), (x+16*d, y-12)), fill="#526c93")
    draw.polygon(((x+13*d, y-43), (x+43*d, y-58), (x+79*d, y-62),
                  (x+53*d, y-49), (x+27*d, y-28)), fill="#88c9db")
    draw.polygon(((x+43*d, y-58), (x+79*d, y-62), (x+93*d, y-58),
                  (x+68*d, y-57), (x+49*d, y-49)), fill="#d2f3ff")
    for j in range(7):
        fx = x + (22 + j*8)*d
        fy = y - (46 + min(j, 4)*3)
        square(draw, fx, fy, 0, CREAM if j % 2 else CYAN)
    draw.line((x+14*d, y-44, x+43*d, y-60, x+82*d, y-64),
              fill=CREAM, width=2)
    draw.rectangle((x+4*d-2, y-27, x+4*d+2, y-23), fill=GOLD)


def render(game, now: float, full_size: bool = True) -> Image.Image:
    """Return a full-screen keyed image; all art is first drawn on a tiny grid."""
    scale = pixel_size(game.width, game.height)
    w, h = math.ceil(game.width / scale), math.ceil(game.height / scale)
    image = Image.new("RGB", (w, h), KEY)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    sx = lambda value: round(value / scale)
    tick = int(now * 9)

    # Dense layered chrysanthemum bursts: fine rays, colored tips, and falling embers.
    for burst in game.explosions:
        age = now - burst["born"]
        cx, cy = sx(burst["x"]), sx(burst["y"])
        radius = (18 + age * 320) / scale
        colors = (GOLD, PINK, CYAN, "#b4ffcc", "#bb9bff", CREAM)
        for i in range(64):
            angle = i * math.tau / 64 + (cx % 11) * 0.012
            ca, sa = math.cos(angle), math.sin(angle)
            reach = radius * (0.74 + (i * 17 % 13) / 45)
            color = colors[(i + cx // 37) % len(colors)]
            inner = reach * (0.18 if i % 3 else 0.38)
            outer_x = round(cx + reach * ca)
            outer_y = round(cy + reach * sa + age * age * (5 + i % 7))
            curl = ((i % 5) - 2) * reach * 0.035
            mid_x = round(cx + reach * 0.62 * ca - curl * sa)
            mid_y = round(cy + reach * 0.62 * sa + curl * ca)
            draw.line((round(cx + inner * ca), round(cy + inner * sa),
                       mid_x, mid_y, outer_x, outer_y), fill=color, width=1)
            if i % 2 == 0:
                square(draw, outer_x, outer_y, 1, CREAM if i % 8 == 0 else color)
            if i % 8 == 0:
                star(draw, outer_x, outer_y, 3, color)
            if i % 4 == 0:
                ember_x = round(cx + (reach * 0.58) * ca)
                ember_y = round(cy + (reach * 0.58) * sa + age * 10)
                square(draw, ember_x, ember_y, 1, colors[(i + 2) % len(colors)])
        # Three fan trails link the moving pet to each burst like launched shells.
        if age < 0.7:
            bx, by = sx(game.boss_x), sx(game.boss_y)
            for offset, color in ((-5, CYAN), (0, CREAM), (5, PINK)):
                draw.line((bx+offset, by, (bx+cx)//2+offset,
                           min(by, cy)-9, cx, cy), fill=color, width=1)
        for j in range(16):
            angle = j * math.tau / 16
            draw.line((cx, cy, round(cx + radius * 0.28 * math.cos(angle)),
                       round(cy + radius * 0.28 * math.sin(angle))),
                      fill=colors[j % len(colors)], width=1)
        draw.ellipse((cx-5, cy-5, cx+5, cy+5), fill=CREAM, outline=GOLD)
        star(draw, cx, cy, 6, CREAM)

    # Black-hole rings, accretion pixels, and dark central disk.
    if game.black_hole:
        hole = game.black_hole
        age = now - hole["born"]
        cx, cy = sx(hole["x"]), sx(hole["y"])
        for j in range(6):
            radius = (12 + j * 7 + (tick % 7))
            draw.arc((cx-radius, cy-radius, cx+radius, cy+radius),
                     25+j*31+tick*7, 250+j*31+tick*7,
                     fill=("#482665", "#aa4bad", PINK, GOLD)[j % 4], width=2)
        for i in range(18):
            angle = i * math.tau / 18 + age * (1.5 + i % 3 * 0.2)
            r = 18 + ((i * 13 + tick * 3) % 32)
            square(draw, round(cx+r*math.cos(angle)), round(cy+r*math.sin(angle)),
                   1, PINK if i % 2 else CYAN)
        draw.ellipse((cx-13, cy-13, cx+13, cy+13), fill=INK, outline=GOLD, width=3)
        draw.ellipse((cx-8, cy-8, cx+8, cy+8), fill="#03040d")
        star(draw, cx, cy, 2, "#523b75")
        if age < 0.8:
            draw.text((cx-35, cy+18), "VOID INCOMING", font=font, fill=CREAM,
                      stroke_width=1, stroke_fill=INK)

    for item in game.bombs:
        bomb(draw, sx(item["x"]), sx(item["y"]), tick)

    if game.scythe:
        age = now - game.scythe["born"]
        a, b = slash_line(game.width, game.height, game.scythe["direction"])
        line = (sx(a[0]), sx(a[1]), sx(b[0]), sx(b[1]))
        if age < 0.85:
            # A flashing, screen-spanning prediction line precedes the hit.
            draw.line(line, fill=INK, width=5)
            draw.line(line, fill=PINK if tick % 2 else CREAM, width=2)
            for i in range(22):
                p = i / 21
                star(draw, sx(a[0]+(b[0]-a[0])*p),
                     sx(a[1]+(b[1]-a[1])*p), 2, GOLD)
            draw.text((w//2-58, 23), "WARNING // SLASH", font=font, fill=CREAM,
                      stroke_width=1, stroke_fill=INK)
        else:
            progress = min(1, (age - 0.85) / 0.9)
            at_x, at_y = slash_position(game.width, game.height, progress,
                                        game.scythe["direction"])
            trail_end = slash_position(game.width, game.height,
                                       max(0, progress - 0.2), game.scythe["direction"])
            draw.line((sx(trail_end[0]), sx(trail_end[1]), sx(at_x), sx(at_y)),
                      fill="#4b2b69", width=8)
            draw.line((sx(trail_end[0]), sx(trail_end[1]), sx(at_x), sx(at_y)),
                      fill=CYAN, width=3)
            pixel_scythe(draw, sx(at_x), sx(at_y), game.scythe["direction"])

    if not (game.finished or now < game.invulnerable_until and tick % 2):
        player(draw, sx(game.player_x), sx(game.player_y), tick)

    # Blocky HUD with English bitmap text to avoid smooth font rendering.
    draw.rectangle((3, 3, 101, 20), fill=INK, outline=CYAN, width=2)
    draw.text((8, 7), f"HP {game.lives}  SCORE {int(game.score):05d}",
              font=font, fill=CREAM)
    draw.rectangle((w-63, 3, w-3, 20), fill=INK, outline=GOLD, width=2)
    draw.text((w-56, 7), "X  EXIT", font=font, fill=CREAM)
    if game.finished:
        draw.rectangle((w//2-100, h//2-27, w//2+100, h//2+27),
                       fill=INK, outline=GOLD, width=3)
        draw.text((w//2-53, h//2-13), "GAME OVER", font=font, fill=GOLD)
        draw.text((w//2-71, h//2+5), "CLICK / R = RETRY", font=font, fill=CREAM)

    return (image.resize((game.width, game.height), Image.Resampling.NEAREST)
            if full_size else image)

