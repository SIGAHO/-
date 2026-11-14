"""Small Windows desktop companion. Screen images stay in memory and local Ollama.

Movement and window-change reactions are deterministic. Vision is opt-in from the
menu, with a cooldown for automatic observations. This process never writes the
conversation, memory, or configuration databases.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
from io import BytesIO
import json
from pathlib import Path
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import Menu
from urllib import error, request
import webbrowser

from PIL import Image, ImageGrab, ImageTk


BG = "#ff00ff"
SIZE = (256, 166)
MODEL = "qwen3.5:4b"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
WEB_URL = "http://127.0.0.1:8765/"


def active_window_title() -> str:
    user32 = ctypes.windll.user32
    handle = user32.GetForegroundWindow()
    if not handle:
        return ""
    length = user32.GetWindowTextLengthW(handle)
    if not length:
        return ""
    buffer = ctypes.create_unicode_buffer(min(length + 1, 512))
    user32.GetWindowTextW(handle, buffer, len(buffer))
    return buffer.value


def window_category(title: str) -> str:
    """Classify a title without displaying document names or private page text."""
    title = title.casefold()
    if any(word in title for word in ("visual studio code", "vscode", "codex")):
        return "作業画面"
    if any(word in title for word in ("chrome", "edge", "firefox")):
        return "ブラウザ"
    if any(word in title for word in ("powershell", "terminal", "cmd.exe")):
        return "ターミナル"
    if any(word in title for word in ("explorer", "エクスプローラー")):
        return "ファイル画面"
    if "discord" in title:
        return "チャット画面"
    return "別の画面"


def clean_comment(value: str) -> str:
    value = re.sub(r"<think>.*?</think>", "", value or "", flags=re.I | re.S)
    value = re.sub(r"https?://\S+|www\.\S+|[A-Za-z]:\\\S+|[\w.+-]+@[\w.-]+",
                   "（詳細は省略）", value, flags=re.I)
    value = re.sub(r"[`*_#]", "", value).strip().splitlines()
    return (value[0][:36] if value and value[0] else "画面は見えたけど、うまく言葉にできないな。")


def vision_comment(jpeg: bytes, model: str = MODEL, timeout: int = 120) -> str:
    prompt = ("このPC画面を見て、見えているもの一つに対して友達のような自然な感想を日本語一文だけ。"
              "読めない文字や画面外のことは推測しない。個人名、会話本文、URL、パス、通知内容は引用しない。"
              "30字以内。『画像です』『画面です』という説明文や箇条書きは避ける。")
    body = {"model": model, "stream": False, "think": False, "keep_alive": "15m",
            "messages": [{"role": "user", "content": prompt,
                          "images": [base64.b64encode(jpeg).decode("ascii")]}],
            "options": {"temperature": 0.5, "num_predict": 64, "num_ctx": 2048}}
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    call = request.Request(OLLAMA_URL, data=payload,
                           headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(call, timeout=timeout) as response:
        answer = json.load(response)
    return clean_comment(answer.get("message", {}).get("content", ""))


def capture_screen() -> bytes:
    image = ImageGrab.grab().convert("RGB")
    image.thumbnail((960, 540), Image.Resampling.LANCZOS)
    memory = BytesIO()
    image.save(memory, format="JPEG", quality=62, optimize=True)
    return memory.getvalue()


def sprite_frames(path: Path, root: tk.Tk):
    source = Image.open(path)
    frames = []
    for index in range(getattr(source, "n_frames", 1)):
        source.seek(index)
        image = source.convert("RGBA").resize((96, 96), Image.Resampling.NEAREST)
        frames.append((ImageTk.PhotoImage(image, master=root),
                       max(80, int(source.info.get("duration", 200)))))
    return frames


class DesktopPet:
    def __init__(self, sprite: Path, model: str = MODEL, look_on_start: bool = False):
        self.root = tk.Tk()
        self.root.title("Breaktail Pet")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", BG)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.model = model
        self.frames = sprite_frames(sprite, self.root)
        self.frame_index = 0
        self.canvas = tk.Canvas(self.root, width=SIZE[0], height=SIZE[1], bg=BG,
                                highlightthickness=0)
        self.canvas.pack()
        self.sprite = self.canvas.create_image(128, 118, image=self.frames[0][0])
        self.bubble = None
        self.bubble_text = None
        self.hide_after = None
        self.x = max(0, self.root.winfo_screenwidth() - SIZE[0] - 80)
        self.y = max(0, self.root.winfo_screenheight() - SIZE[1] - 60)
        self.direction = -1
        self.drag = None
        self.last_window = ""
        self.last_reaction = 0.0
        self.last_vision = 0.0
        self.vision_busy = False
        self.auto_vision = tk.BooleanVar(value=False)
        self.results = queue.Queue()
        self.root.geometry(f"{SIZE[0]}x{SIZE[1]}+{self.x}+{self.y}")
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", lambda _: webbrowser.open(WEB_URL))
        self.canvas.bind("<Button-3>", self.open_menu)
        self.root.after(self.frames[0][1], self.animate)
        self.root.after(60, self.move)
        self.root.after(4000, self.observe_window)
        self.root.after(200, self.poll_results)
        self.say("よお。ここにいるよ。")
        if look_on_start:
            self.root.after(1200, self.look)

    def say(self, message: str):
        if self.bubble is not None:
            self.canvas.delete(self.bubble)
            self.canvas.delete(self.bubble_text)
        self.bubble = self.canvas.create_rectangle(8, 4, 248, 54, fill="#24242a",
                                                    outline="#79d5d0", width=2)
        self.bubble_text = self.canvas.create_text(128, 29, text=message[:64],
                                                   width=222, fill="white",
                                                   font=("Yu Gothic UI", 10, "bold"))
        if self.hide_after:
            self.root.after_cancel(self.hide_after)
        self.hide_after = self.root.after(10000, self.hide_bubble)

    def hide_bubble(self):
        if self.bubble is not None:
            self.canvas.delete(self.bubble)
            self.canvas.delete(self.bubble_text)
            self.bubble = self.bubble_text = None
        self.hide_after = None

    def animate(self):
        self.frame_index = (self.frame_index + 1) % len(self.frames)
        image, delay = self.frames[self.frame_index]
        self.canvas.itemconfigure(self.sprite, image=image)
        self.root.after(delay, self.animate)

    def move(self):
        if self.drag is None:
            screen = self.root.winfo_screenwidth()
            self.x += self.direction
            if self.x < 0 or self.x > screen - SIZE[0]:
                self.x = max(0, min(screen - SIZE[0], self.x))
                self.direction *= -1
            self.root.geometry(f"+{self.x}+{self.y}")
        self.root.after(60, self.move)

    def observe_window(self):
        title = active_window_title()
        now = time.monotonic()
        if title and title != "Breaktail Pet" and title != self.last_window:
            self.last_window = title
            if now - self.last_reaction >= 30:
                self.say(f"{window_category(title)}に移ったね。")
                self.last_reaction = now
            if self.auto_vision.get() and now - self.last_vision >= 120:
                self.look()
        self.root.after(4000, self.observe_window)

    def look(self):
        if self.vision_busy:
            return
        self.vision_busy = True
        self.last_vision = time.monotonic()
        self.say("いまの画面を見てる…")
        self.root.withdraw()
        self.root.after(180, self.capture_and_ask)

    def capture_and_ask(self):
        try:
            jpeg = capture_screen()
        except Exception:
            self.root.deiconify()
            self.vision_busy = False
            self.say("画面を取れなかった。")
            return
        self.root.deiconify()
        def worker():
            try:
                self.results.put((True, vision_comment(jpeg, self.model)))
            except (error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
                self.results.put((False, "画像の感想は今出せない。動くのは続けるよ。"))
        threading.Thread(target=worker, daemon=True).start()

    def poll_results(self):
        try:
            ok, message = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.vision_busy = False
            self.say(message)
        self.root.after(200, self.poll_results)

    def on_press(self, event):
        self.drag = (event.x_root - self.x, event.y_root - self.y)

    def on_drag(self, event):
        if self.drag:
            self.x = max(0, min(self.root.winfo_screenwidth() - SIZE[0], event.x_root - self.drag[0]))
            self.y = max(0, min(self.root.winfo_screenheight() - SIZE[1], event.y_root - self.drag[1]))
            self.root.geometry(f"+{self.x}+{self.y}")

    def on_release(self, _event):
        self.drag = None

    def open_menu(self, event):
        menu = Menu(self.root, tearoff=False)
        menu.add_command(label="今の画面を見て感想", command=self.look)
        menu.add_checkbutton(label="画面が変わったら自動で見る（2分以上間隔）",
                             variable=self.auto_vision)
        menu.add_command(label="Breaktailの会話を開く", command=lambda: webbrowser.open(WEB_URL))
        menu.add_separator()
        menu.add_command(label="終了", command=self.root.destroy)
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Breaktail desktop pet")
    parser.add_argument("--sprite", type=Path,
                        default=Path(__file__).resolve().parent.parent / "assets" / "gomi_blink.gif")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--look-on-start", action="store_true",
                        help="observe the current screen once after opening")
    args = parser.parse_args()
    if not args.sprite.is_file():
        parser.error(f"sprite GIF not found: {args.sprite}")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    mutex = kernel32.CreateMutexW(None, True, "Local\\BreaktailDesktopPet")
    if not mutex:
        raise OSError("Could not create desktop pet mutex")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(mutex)
        return
    try:
        DesktopPet(args.sprite, args.model, args.look_on_start).run()
    finally:
        kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()

