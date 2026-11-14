"""Opt-in local bullet-hell window for the Breaktail desktop companion."""
from __future__ import annotations

import math
import random
import time
import tkinter as tk
from breaktail_pixel_art import render, slash_position
from breaktail_pixel_blit import blit


WIDTH, HEIGHT = 900, 600  # fallback dimensions for pure rule checks
TRANSPARENT = "#ff00ff"


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def hits_circle(ax: float, ay: float, ar: float,
                bx: float, by: float, br: float) -> bool:
    return (ax - bx) ** 2 + (ay - by) ** 2 <= (ar + br) ** 2


def point_segment_distance(px: float, py: float, ax: float, ay: float,
                           bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    ratio = clamp(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy), 0, 1) if dx or dy else 0
    return math.hypot(px - ax - ratio * dx, py - ay - ratio * dy)


class FireworksGame:
    def __init__(self, parent: tk.Tk, on_close=None):
        self.parent = parent
        self.window = tk.Toplevel(parent)
        self.window.title("Breaktail 花火弾幕")
        self.width = self.window.winfo_screenwidth()
        self.height = self.window.winfo_screenheight()
        self.window.overrideredirect(True)
        self.window.geometry(f"{self.width}x{self.height}+0+0")
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)
        self.window.wm_attributes("-transparentcolor", TRANSPARENT)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda _event: self.close())
        self.window.bind("<KeyPress>", self.key_down)
        self.window.bind("<KeyRelease>", self.key_up)
        self.window.bind("<r>", lambda _event: self.reset() if self.finished else None)
        self.canvas = tk.Canvas(self.window, width=self.width, height=self.height, bg=TRANSPARENT,
                                highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self.click)
        self.on_close = on_close
        self.rng = random.Random()
        self.keys: set[str] = set()
        self.last_time = time.monotonic()
        self.reset()
        self.window.focus_force()
        self.frames_drawn = 0
        self.window.after(16, self.tick)

    def reset(self):
        self.keys.clear()
        self.last_key_move = 0.0
        self.player_x = self.width / 2
        self.player_y = self.height - 68
        self.boss_x = self.width / 2
        self.boss_y = 105
        self.lives = 5
        self.score = 0
        self.invulnerable_until = 0.0
        self.started = time.monotonic()
        self.next_firework = self.started + 0.45
        self.next_scythe = self.started + 5.5
        self.next_black_hole = self.started + 9.0
        self.explosions: list[dict] = []
        self.bombs: list[dict] = []
        self.scythe: dict | None = None
        self.black_hole: dict | None = None
        self.finished = False

    def key_down(self, event):
        self.keys.add(event.keysym)

    def key_up(self, event):
        self.keys.discard(event.keysym)

    def click(self, event):
        if event.x >= self.width - 250 and event.y < 84:
            self.close()
        elif (self.finished and abs(event.x - self.width/2) < 260 and
              abs(event.y - self.height/2) < 90):
            self.reset()
        else:
            self.window.focus_force()

    def launch_firework(self, now: float):
        x = self.rng.randint(110, self.width - 110)
        y = self.rng.randint(max(110, self.height // 8),
                             max(180, self.height * 2 // 3))
        self.explosions.append({"x": x, "y": y, "born": now, "color":
                                self.rng.choice(("#ffb855", "#fb65cb", "#8ceeff"))})
        # Bombs start at the burst and fan out toward the lower play field.
        for index in range(18):
            angle = 2 * math.pi * index / 18 + self.rng.uniform(-0.12, 0.12)
            speed = self.rng.uniform(85, 160)
            self.bombs.append({"x": x, "y": y, "vx": math.cos(angle) * speed,
                               "vy": math.sin(angle) * speed + 56, "radius": 9})

    def update(self, now: float, dt: float):
        if self.finished:
            return
        self.boss_x = self.parent.winfo_rootx() + 128
        self.boss_y = self.parent.winfo_rooty() + 118
        speed = 330 * dt
        if "Left" in self.keys or "a" in self.keys:
            self.player_x -= speed
        if "Right" in self.keys or "d" in self.keys:
            self.player_x += speed
        if "Up" in self.keys or "w" in self.keys:
            self.player_y -= speed
        if "Down" in self.keys or "s" in self.keys:
            self.player_y += speed
        if self.keys.intersection({"Left", "Right", "Up", "Down", "a", "d", "w", "s"}):
            self.last_key_move = now
        # Track the global cursor even when transparent pixels pass clicks through.
        pointer_x = self.window.winfo_pointerx()
        pointer_y = self.window.winfo_pointery()
        if (now - self.last_key_move > 1.5 and
                0 <= pointer_x < self.width and 0 <= pointer_y < self.height):
            follow = min(1.0, dt * 11)
            self.player_x += (pointer_x - self.player_x) * follow
            self.player_y += (pointer_y - self.player_y) * follow
        self.player_x = clamp(self.player_x, 20, self.width - 20)
        self.player_y = clamp(self.player_y, 100, self.height - 20)
        if now >= self.next_firework:
            for _ in range(2 if self.score < 150 else 3):
                self.launch_firework(now)
            self.next_firework = now + max(0.65, 1.4 - self.score / 1800)
        if self.scythe is None and now >= self.next_scythe:
            self.scythe = {"born": now, "direction": self.rng.choice((-1, 1))}
            self.next_scythe = now + 8.0
        if self.black_hole is None and now >= self.next_black_hole:
            self.black_hole = {"born": now,
                               "x": self.rng.randint(self.width // 4, self.width * 3 // 4),
                               "y": self.rng.randint(self.height // 3, self.height * 2 // 3)}
            self.next_black_hole = now + 13.0
        if self.black_hole:
            hole = self.black_hole
            age = now - hole["born"]
            if age >= 4.2:
                self.black_hole = None
            elif age >= 0.8:
                dx, dy = hole["x"] - self.player_x, hole["y"] - self.player_y
                distance = math.hypot(dx, dy)
                if 1 < distance < 360:
                    pull = 230 * (1 - distance / 360) * dt
                    self.player_x += dx / distance * pull
                    self.player_y += dy / distance * pull
                if now >= self.invulnerable_until and distance < 32:
                    self.hit(now)
        for bomb in self.bombs:
            if self.black_hole and now - self.black_hole["born"] >= 0.8:
                dx = self.black_hole["x"] - bomb["x"]
                dy = self.black_hole["y"] - bomb["y"]
                distance = max(1, math.hypot(dx, dy))
                if distance < 400:
                    force = 80 * (1 - distance / 400) * dt
                    bomb["vx"] += dx / distance * force
                    bomb["vy"] += dy / distance * force
            bomb["x"] += bomb["vx"] * dt
            bomb["y"] += bomb["vy"] * dt
            bomb["vy"] += 45 * dt
            if now >= self.invulnerable_until and hits_circle(
                    bomb["x"], bomb["y"], bomb["radius"], self.player_x, self.player_y, 7):
                self.hit(now)
        self.bombs = [b for b in self.bombs if -20 < b["x"] < self.width + 20 and b["y"] < self.height + 20]
        self.explosions = [e for e in self.explosions if now - e["born"] < 1.05]
        if self.scythe:
            age = now - self.scythe["born"]
            if age >= 2.1:
                self.scythe = None
            elif 0.85 <= age <= 1.75:
                progress = (age - 0.85) / 0.9
                x, y = slash_position(self.width, self.height, progress,
                                      self.scythe["direction"])
                if (now >= self.invulnerable_until and
                        hits_circle(self.player_x, self.player_y, 7, x, y, 95)):
                    self.hit(now)
        self.score += dt * 10

    def hit(self, now: float):
        self.lives -= 1
        self.invulnerable_until = now + 1.5
        if self.lives <= 0:
            self.finished = True

    def draw(self, now: float):
        blit(self.canvas, render(self, now, full_size=False), self.width, self.height)
        self.frames_drawn += 1

    def tick(self):
        if not self.window.winfo_exists():
            return
        now = time.monotonic()
        dt = min(now - self.last_time, 0.05)
        self.last_time = now
        self.update(now, dt)
        self.draw(now)
        self.window.after(16, self.tick)

    def close(self):
        if self.window.winfo_exists():
            self.window.destroy()
        if self.on_close:
            self.on_close()

