"""Opt-in local bullet-hell window for the Breaktail desktop companion."""
from __future__ import annotations

import math
import random
import time
import tkinter as tk


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


def scythe_tip(progress: float, width: int = WIDTH, height: int = HEIGHT,
               origin_x: float | None = None, origin_y: float = 105) -> tuple[float, float]:
    """A broad sweep centered on the moving desktop companion."""
    angle = math.pi * (1.12 - 1.05 * clamp(progress, 0, 1))
    return ((width / 2 if origin_x is None else origin_x) + width * 0.34 * math.cos(angle),
            origin_y + height * 0.43 * math.sin(angle))


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
        self.explosions: list[dict] = []
        self.bombs: list[dict] = []
        self.scythe: dict | None = None
        self.finished = False

    def key_down(self, event):
        self.keys.add(event.keysym)

    def key_up(self, event):
        self.keys.discard(event.keysym)

    def click(self, event):
        if event.x >= self.width - 140 and event.y < 64:
            self.close()
        elif (self.finished and abs(event.x - self.width/2) < 260 and
              abs(event.y - self.height/2) < 90):
            self.reset()
        else:
            self.window.focus_force()

    def launch_firework(self, now: float):
        x = int(clamp(self.boss_x + self.rng.randint(-self.width // 4, self.width // 4),
                      90, self.width - 90))
        y = int(clamp(self.boss_y + self.rng.randint(100, max(110, self.height // 3)),
                      130, self.height - 180))
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
            self.player_x = pointer_x
            self.player_y = pointer_y
        self.player_x = clamp(self.player_x, 20, self.width - 20)
        self.player_y = clamp(self.player_y, 100, self.height - 20)
        if now >= self.next_firework:
            for _ in range(2 if self.score < 150 else 3):
                self.launch_firework(now)
            self.next_firework = now + max(0.65, 1.4 - self.score / 1800)
        if self.scythe is None and now >= self.next_scythe:
            self.scythe = {"born": now}
            self.next_scythe = now + 8.0
        for bomb in self.bombs:
            bomb["x"] += bomb["vx"] * dt
            bomb["y"] += bomb["vy"] * dt
            bomb["vy"] += 45 * dt
            if now >= self.invulnerable_until and hits_circle(
                    bomb["x"], bomb["y"], bomb["radius"], self.player_x, self.player_y, 7):
                self.hit(now)
        self.bombs = [b for b in self.bombs if -20 < b["x"] < self.width + 20 and b["y"] < self.height + 20]
        self.explosions = [e for e in self.explosions if now - e["born"] < 0.9]
        if self.scythe:
            age = now - self.scythe["born"]
            if age >= 2.1:
                self.scythe = None
            elif 0.7 <= age <= 1.65:
                tip = scythe_tip((age - 0.7) / 0.95, self.width, self.height,
                                 self.boss_x, self.boss_y)
                if (now >= self.invulnerable_until and
                        point_segment_distance(self.player_x, self.player_y,
                                               self.boss_x, self.boss_y, *tip) < 16):
                    self.hit(now)
        self.score += dt * 10

    def hit(self, now: float):
        self.lives -= 1
        self.invulnerable_until = now + 1.5
        if self.lives <= 0:
            self.finished = True

    def draw(self, now: float):
        c = self.canvas
        c.delete("all")
        for explosion in self.explosions:
            age = now - explosion["born"]
            cx, cy = explosion["x"], explosion["y"]
            radius = 14 + age * 92
            for i in range(16):
                a = i * math.tau / 16
                px, py = cx + radius * math.cos(a), cy + radius * math.sin(a)
                c.create_line(cx + radius * 0.5 * math.cos(a),
                              cy + radius * 0.5 * math.sin(a), px, py,
                              fill=explosion["color"], width=2)
        for bomb in self.bombs:
            x, y, r = bomb["x"], bomb["y"], bomb["radius"]
            c.create_oval(x-r, y-r, x+r, y+r, fill="#252329", outline="#ff6565", width=2)
            c.create_line(x, y-r, x+4, y-r-7, fill="#ffd36b", width=2)
        if self.scythe:
            age = now - self.scythe["born"]
            tip = scythe_tip(clamp((age - 0.7) / 0.95, 0, 1), self.width, self.height,
                             self.boss_x, self.boss_y)
            if age < 0.7:
                c.create_text(self.boss_x, self.boss_y + 85, text="巨大な鎌が来る！", fill="#ff7e9d",
                              font=("Yu Gothic UI", 23, "bold"))
            else:
                c.create_line(self.boss_x, self.boss_y, *tip, fill="#abb9d7", width=12)
                c.create_line(self.boss_x, self.boss_y, *tip, fill="#fff5ef", width=4)
                x, y = tip
                c.create_polygon(x-12, y-8, x+84, y-82, x+30, y-6, x+8, y+22,
                                 fill="#e8faff", outline="#85dfff", width=3)
        if not (self.finished or now < self.invulnerable_until and int(now * 12) % 2):
            x, y = self.player_x, self.player_y
            c.create_polygon(x, y-18, x-14, y+12, x, y+5, x+14, y+12,
                             fill="#7de4ff", outline="white", width=2)
            c.create_oval(x-3, y-3, x+3, y+3, fill="#fffbcb", outline="")
        c.create_rectangle(8, 8, 255, 58, fill="#151b30", outline="#7de4ff", width=2)
        c.create_text(20, 18, anchor="nw", text=f"♥ {self.lives}    SCORE {int(self.score)}",
                      fill="white", font=("Yu Gothic UI", 18, "bold"))
        c.create_rectangle(self.width-140, 8, self.width-8, 58,
                           fill="#151b30", outline="#ffb855", width=2)
        c.create_text(self.width-74, 33, text="終了  Esc",
                      fill="white", font=("Yu Gothic UI", 15, "bold"))
        c.create_text(self.width/2, 33, text="マウスで避ける  ·  矢印キー/WASDも可",
                      fill="#f5e3af", font=("Yu Gothic UI", 14, "bold"))
        if self.finished:
            cx, cy = self.width/2, self.height/2
            c.create_rectangle(cx-260, cy-90, cx+260, cy+85,
                               fill="#13182b", outline="#ffb855", width=3)
            c.create_text(cx, cy-35, text="ゲームオーバー", fill="#ffb855",
                          font=("Yu Gothic UI", 32, "bold"))
            c.create_text(cx, cy+30, text="クリックかRで再挑戦  ·  Escで終了", fill="white",
                          font=("Yu Gothic UI", 17))

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

