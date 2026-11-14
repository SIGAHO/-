"""Read one named Fisch Wiki page; never upload screenshots or unrestricted OCR text."""
from __future__ import annotations

from html.parser import HTMLParser
from difflib import SequenceMatcher
import re
import threading
import time
from urllib import error, request
from urllib.parse import quote, urlparse


WIKI_HOST = "fisch.wiki"
GAME_TERMS = ("rod", "bait", "radar", "fish", "crate", "relic", "bay",
              "island", "megalodon", "moosewood", "lantern", "bobber")
_INDEX = []
_INDEX_FETCHED = 0.0
_INDEX_LOCK = threading.Lock()


def _normalized(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


class _Index(HTMLParser):
    def __init__(self):
        super().__init__()
        self.pages = []
        self.href = ""
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            self.href = href if re.fullmatch(r"/wiki/[a-z0-9%-]+/", href) else ""
            self.parts = []

    def handle_data(self, data):
        if self.href:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            title = re.sub(r"\s+", " ", "".join(self.parts)).strip()
            if title:
                self.pages.append((title, f"https://{WIKI_HOST}{self.href}"))
            self.href = ""


def _fetch(url: str, timeout: float, maximum: int) -> tuple[bytes, str] | None:
    response = request.urlopen(request.Request(url, headers={"User-Agent": "Breaktail/0.2"}),
                               timeout=timeout)
    with response:
        final = urlparse(response.url)
        if final.scheme != "https" or final.hostname != WIKI_HOST or response.status != 200:
            return None
        data = response.read(maximum + 1)
    return (data, response.url) if len(data) <= maximum else None


def resolve_page(term: str, timeout: float = 6) -> tuple[str, str] | None:
    """Match a name locally against the public wiki index; no OCR query is sent."""
    global _INDEX, _INDEX_FETCHED
    with _INDEX_LOCK:
        if not _INDEX or time.time() - _INDEX_FETCHED > 86400:
            try:
                result = _fetch(f"https://{WIKI_HOST}/wiki/", timeout, 500_000)
                parser = _Index()
                if result:
                    parser.feed(result[0].decode("utf-8", "replace"))
                if len(parser.pages) >= 100:
                    _INDEX = parser.pages
                    _INDEX_FETCHED = time.time()
            except (error.URLError, TimeoutError, OSError, ValueError):
                pass
        pages = list(_INDEX)
    needle = _normalized(term)
    exact = [(title, url) for title, url in pages if _normalized(title) == needle]
    if len(exact) == 1:
        return exact[0]
    near = []
    for title, url in pages:
        key = _normalized(title)
        if abs(len(key) - len(needle)) <= 2:
            score = SequenceMatcher(None, needle, key).ratio()
            if score >= 0.88:
                near.append((score, title, url))
    near.sort(reverse=True)
    if near and (len(near) == 1 or near[0][0] - near[1][0] >= 0.05):
        return near[0][1], near[0][2]
    return None


def select_fisch_term(ocr: dict) -> str:
    """Allow only short, game-shaped terms to leave the PC."""
    for line in ocr.get("lines", []):
        text = str(line.get("text", "")).strip()
        if (float(line.get("score", 0)) >= 0.8 and
                re.fullmatch(r"[A-Za-z][A-Za-z' -]{2,39}", text) and
                len(text.split()) <= 4 and
                any(text.casefold().endswith(word) for word in GAME_TERMS)):
            return text
    return ""


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tag = ""
        self.skip = 0
        self.heading = ""
        self.paragraphs = []
        self.current = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if not self.skip and tag in ("h1", "p"):
            self.tag = tag
            self.current = []

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag == self.tag:
            value = re.sub(r"\s+", " ", "".join(self.current)).strip()
            if tag == "h1" and not self.heading:
                self.heading = value
            elif tag == "p" and self.heading and len(value) >= 30:
                self.paragraphs.append(value)
            self.tag = ""
            self.current = []

    def handle_data(self, data):
        if self.tag and not self.skip:
            self.current.append(data)


def lookup(term: str, timeout: float = 6) -> dict | None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z' -]{2,39}", term):
        return None
    resolved = resolve_page(term, timeout)
    slug = re.sub(r"-+", "-", term.casefold().replace("'", "").replace(" ", "-"))
    url = resolved[1] if resolved else f"https://{WIKI_HOST}/wiki/{quote(slug)}/"
    try:
        result = _fetch(url, timeout, 250_000)
        if not result:
            return None
        page = _Page()
        page.feed(result[0].decode("utf-8", "replace"))
        if not page.heading or _normalized(page.heading) != _normalized(resolved[0] if resolved else term):
            return None
        return {"title": page.heading, "excerpt": (page.paragraphs[0][:240] if page.paragraphs else ""),
                "url": url, "checked_at": time.time()}
    except (error.URLError, TimeoutError, OSError, ValueError):
        return None

