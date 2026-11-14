"""Read one named Fisch Wiki page; never upload screenshots or unrestricted OCR text."""
from __future__ import annotations

from html.parser import HTMLParser
import re
import time
from urllib import error, request
from urllib.parse import quote, urlparse


WIKI_HOST = "fisch.wiki"
GAME_TERMS = ("rod", "bait", "radar", "fish", "crate", "relic", "bay",
              "island", "megalodon", "moosewood", "lantern", "bobber")


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
    slug = re.sub(r"-+", "-", term.casefold().replace("'", "").replace(" ", "-"))
    url = f"https://{WIKI_HOST}/wiki/{quote(slug)}/"
    try:
        response = request.urlopen(request.Request(url, headers={"User-Agent": "Breaktail/0.2"}),
                                   timeout=timeout)
        with response:
            final = urlparse(response.url)
            if final.scheme != "https" or final.hostname != WIKI_HOST:
                return None
            if response.status != 200:
                return None
            data = response.read(250_001)
        if len(data) > 250_000:
            return None
        page = _Page()
        page.feed(data.decode("utf-8", "replace"))
        if not page.heading or page.heading.casefold() != term.casefold():
            return None
        return {"title": page.heading, "excerpt": (page.paragraphs[0][:240] if page.paragraphs else ""),
                "url": url, "checked_at": time.time()}
    except (error.URLError, TimeoutError, OSError, ValueError):
        return None

