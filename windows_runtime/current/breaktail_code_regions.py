"""Lossless structural spans. Never run prose rewriting inside these regions."""
import json
import re


def split_code_regions(text: str) -> list[tuple[bool, str]]:
    spans = []
    # Fences include their delimiters and whitespace, including incomplete fences.
    fence = re.compile(r"(?m)^ {0,3}(`{3,}|~{3,})[^\r\n]*\r?\n")
    pos = 0
    while match := fence.search(text, pos):
        marker = match[1]
        close = re.search(r"(?m)^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*(?:\r?\n|$)", text[match.end():])
        end = match.end() + close.end() if close else len(text)
        spans.append((match.start(), end))
        pos = end
    patterns = [
        r"(?s)(`+)(?!`)(.+?)\1",
        r"(?is)<!doctype\b[^>]*>\s*<html\b[^>]*>.*?</html\s*>",
        r"(?is)<([a-zA-Z][\w:.-]*)\b[^>]*>.*?</\1\s*>",
        r"(?is)<\?xml\b.*?\?>",
        r"(?is)<[a-zA-Z][\w:.-]*\b[^>]*?/>",
        r"(?ims)^[ \t]*(?:<!doctype\b|<html\b|<script\b|<style\b)[\s\S]*\Z",
        r"(?m)^(?:\d{4}-\d\d-\d\d[T ][^\n]*|\[?(?:INFO|WARN|ERROR|DEBUG|TRACE)\]?\b[^\n]*)(?:\n|$)",
        r"(?m)^(?: {4}|\t)\S[^\n]*(?:\n|$)",
        r"(?m)^(?:const |let |var |function |class |def |import |from |//|#include)[^\n]*(?:\n(?!\s*$)[^\n]*)*",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            # A match that starts inside an already protected region must not
            # extend that region past its real closing boundary.
            # Example: `let ...` inside a fenced block must not swallow prose
            # appearing after the closing fence.
            if any(a <= match.start() < b for a, b in spans):
                continue
            spans.append(match.span())
    decoder = json.JSONDecoder()
    for match in re.finditer(r"(?m)^[ \t]*(?=[{\[])", text):
        try:
            _, size = decoder.raw_decode(text[match.end():])
            spans.append((match.start(), match.end() + size))
        except ValueError:
            pass
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    result, pos = [], 0
    for start, end in merged:
        if start > pos:
            result.append((False, text[pos:start]))
        result.append((True, text[start:end]))
        pos = end
    if pos < len(text):
        result.append((False, text[pos:]))
    return result


def map_prose(text, transform):
    """Keep exact source slices, including the separators around code."""
    output = []
    for protected, part in split_code_regions(text):
        if protected or not part.strip():
            output.append(part)
            continue
        leading = part[:len(part) - len(part.lstrip())]
        trailing = part[len(part.rstrip()):]
        output.append(leading + transform(part.strip()) + trailing)
    return ''.join(output)
