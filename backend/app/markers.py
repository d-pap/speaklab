"""Line markers: the model writes [[L7]] or [[L7:"exact words"]]; the app
resolves them against stored transcript lines so quotes and times are never
model-written."""

import re

MARKER = re.compile(r'\[\[(L\d+)(?::"([^"]+)")?\]\]')
plain_timestamp_pattern = re.compile(r"\b\d{1,2}:\d{2}\b")


def _normalise(text: str) -> tuple[str, list[int]]:
    """Lowercase, collapse whitespace runs; map each output char to its source index."""
    chars: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space:
                chars.append(" ")
                index.append(i)
            prev_space = True
        else:
            for low in ch.lower():  # lower() can yield several chars; keep one index each
                chars.append(low)
                index.append(i)
            prev_space = False
    if chars and chars[-1] == " ":
        chars.pop()
        index.pop()
    return "".join(chars), index


def _quote_from_line(quote: str, line_text: str) -> str:
    needle, _ = _normalise(quote)
    if not needle:
        return line_text
    hay, index = _normalise(line_text)
    pos = hay.find(needle)
    if pos < 0:
        return line_text
    return line_text[index[pos] : index[pos + len(needle) - 1] + 1]


def resolve(text: str, lines: list[dict]) -> list[dict]:
    by_id = {line["id"]: line for line in lines}
    parts: list[dict] = []

    def add_text(chunk: str) -> None:
        if not chunk:
            return
        if parts and parts[-1]["type"] == "text":
            parts[-1]["text"] += chunk
        else:
            parts.append({"type": "text", "text": chunk})

    last = 0
    for match in MARKER.finditer(text):
        add_text(text[last : match.start()])
        last = match.end()
        line = by_id.get(match.group(1))
        if line is None:
            continue
        quote = _quote_from_line(match.group(2), line["text"]) if match.group(2) else ""
        parts.append(
            {"type": "ref", "line_id": line["id"], "start": line.get("start"), "quote": quote}
        )
    add_text(text[last:])
    return parts


def strip_unknown(text: str, lines: list[dict]) -> str:
    known = {line["id"] for line in lines}
    return MARKER.sub(lambda m: m.group(0) if m.group(1) in known else "", text)
