"""HTML allowlist for stored document content.

The editor only produces a small set of tags. Anything else (scripts, inline
styles, event handlers, links with javascript: URLs) is removed before saving,
so content from the editor and from uploads is stored in the same safe form.
"""

import html
import re

import nh3

ALLOWED_TAGS = {
    "p", "br", "h1", "h2", "h3", "strong", "b", "em", "i", "u", "s",
    "ul", "ol", "li", "blockquote", "code", "pre", "hr", "a",
}
ALLOWED_ATTRIBUTES = {"a": {"href"}, "ol": {"start"}}


def clean_html(raw: str) -> str:
    return nh3.clean(
        raw or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    ).strip()


def html_to_excerpt(content: str, limit: int = 160) -> str:
    # Block tags become spaces; inline tags (strong, em, u) are removed without
    # adding a space, so "<u>tax</u>." stays "tax." in the excerpt.
    text = re.sub(r"</?(p|h[1-6]|li|ul|ol|br|blockquote|pre|hr)\b[^>]*>", " ", content or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = " ".join(html.unescape(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
