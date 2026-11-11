"""Convert an uploaded file into document HTML.

Supported: .txt, .md, and .docx files up to 2 MB. Each file becomes a new document
owned by the person who uploaded it. The converted content must also fit the 1 MB
limit for one document, which is the same limit applied on every save.
"""

import html
import io
import os

import mammoth
import markdown

from .sanitize import clean_html
from .services import CONTENT_MAX_BYTES, ServiceError

ALLOWED_EXTENSIONS = {".txt", ".md", ".docx"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


def _text_to_html(text: str) -> str:
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n")]
    return "".join(
        "<p>" + "<br>".join(html.escape(line) for line in p.split("\n")) + "</p>"
        for p in paragraphs
        if p
    )


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ServiceError("The file is not UTF-8 text, so it cannot be imported.") from exc


def convert_upload(filename: str, data: bytes) -> tuple[str, str]:
    """Return (title, html) for an uploaded file, or raise ServiceError."""
    name = os.path.basename(filename or "").strip()
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ServiceError("Only .txt, .md, and .docx files can be imported.")
    if not data:
        raise ServiceError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ServiceError("Files can be up to 2 MB.")

    if ext == ".txt":
        body = _text_to_html(_decode(data))
    elif ext == ".md":
        body = markdown.markdown(_decode(data), extensions=["sane_lists"])
    else:
        try:
            # Mammoth drops underline unless it is mapped explicitly.
            body = mammoth.convert_to_html(io.BytesIO(data), style_map="u => u").value
        except Exception as exc:  # mammoth raises several error types for bad files
            raise ServiceError("The .docx file could not be read. It may be damaged.") from exc

    body = clean_html(body)
    if not body:
        raise ServiceError("The file has no text to import.")
    # Conversion can make text larger (paragraph tags, escaped characters), so the
    # limit is checked on the result, not only on the file.
    if len(body.encode("utf-8")) > CONTENT_MAX_BYTES:
        raise ServiceError(
            "This file has more text than one document can hold (1 MB after conversion). "
            "Split it into smaller files and import them separately."
        )
    title = " ".join(stem.replace("_", " ").replace("-", " ").split())[:120] or "Imported document"
    return title, body
