"""Minimal HTML-to-text used only as a fallback when an email carries no
`text/plain` part.

Deliberately small: `email_adapter.normalize` is what does the real
noise-stripping (quoting, forwarding boilerplate) on whatever text this
produces. The job here is just to turn an HTML-only body into readable
lines so that downstream normalization + A2/A3 have something to work
with, rather than dropping the message. `html.parser` from the standard
library — no `beautifulsoup4` / `lxml` dependency.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "blockquote",
}
_DROP_CONTENT_TAGS = {"script", "style", "head", "title"}
_WHITESPACE_RUN = re.compile(r"[ \t]{2,}")
_BLANK_LINE_RUN = re.compile(r"\n{3,}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._suppress_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_CONTENT_TAGS:
            self._suppress_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_CONTENT_TAGS and self._suppress_depth > 0:
            self._suppress_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._suppress_depth == 0 and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        joined = unescape("".join(self._chunks))
        lines = [_WHITESPACE_RUN.sub(" ", line).strip() for line in joined.splitlines()]
        collapsed = "\n".join(line for line in lines if line is not None)
        return _BLANK_LINE_RUN.sub("\n\n", collapsed).strip()


def html_to_text(html: str) -> str:
    """Render an HTML fragment to plain text. Returns `""` for input that
    is empty or contains no readable text."""
    if not html or not html.strip():
        return ""
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
        extractor.close()
    except (ValueError, AssertionError):
        # `html.parser` is very tolerant; on the rare structural error,
        # fall back to a blunt tag strip rather than dropping the body.
        return _BLANK_LINE_RUN.sub("\n\n", unescape(re.sub(r"<[^>]+>", " ", html))).strip()
    return extractor.text()


__all__ = ["html_to_text"]
