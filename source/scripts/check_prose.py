"""Scan written text for phrasing that reads as machine-generated.

Usage: python scripts/check_prose.py <file or folder> [...]

It checks Markdown, text, HTML, JavaScript and Python files, including UI strings
and comments. A clean run does not make the writing good. It only means none of
these coded patterns appear, so the text still needs a read-through.
"""

import re
import statistics
import sys
from pathlib import Path

EXTENSIONS = {".md", ".txt", ".html", ".js", ".py", ".css"}
SKIP_PARTS = {"vendor", "node_modules", ".venv", "__pycache__", ".pytest_cache", "data"}

PATTERNS = [
    ("em dash", re.compile("—")),
    ("en dash used as a dash", re.compile(r"\s–\s")),
    ("tautology (X is X)", re.compile(r"\b([A-Za-z]{4,})\b[^,;:!?]{0,24}?\bis (?:still )?\1\b", re.I)),
    ("'the whole story'", re.compile(r"\bthe whole story\b", re.I)),
    ("inflated verb", re.compile(r"\b(serves as|stands as|boasts|showcases|delves?|leverag(e|es|ing))\b", re.I)),
    ("negative parallelism", re.compile(r"\bnot (just|only)\b[^.]{0,80}\b(but|it'?s|it is)\b", re.I)),
    ("sycophancy", re.compile(
        r"\b(great question|happy to help|i'?d be happy to|excellent point|you'?re absolutely right|"
        r"absolutely!|certainly!|great choice|thank you so much)\b", re.I)),
    ("filler adjective", re.compile(r"\b(seamless(ly)?|robust|cutting-edge|game-chang\w+)\b", re.I)),
]


def bullet_runs(lines):
    """Yield (line number, size) for runs of 6+ bullets whose word counts barely vary."""
    run = []
    for number, line in enumerate(lines + [""], start=1):
        match = re.match(r"\s*[-*] (.+)", line)
        if match:
            run.append((number, len(match.group(1).split())))
            continue
        if len(run) >= 6 and statistics.pstdev([w for _, w in run]) <= 1.5:
            yield run[0][0], len(run)
        run = []


def files(paths):
    for raw in paths:
        path = Path(raw)
        candidates = [path] if path.is_file() else path.rglob("*")
        for f in candidates:
            if f.is_file() and f.suffix in EXTENSIONS and not SKIP_PARTS & set(f.parts):
                yield f


def main(paths):
    problems = 0
    for f in files(paths):
        lines = f.read_text(encoding="utf-8").splitlines()
        if f.name == "check_prose.py":
            continue
        for number, line in enumerate(lines, start=1):
            for name, pattern in PATTERNS:
                if pattern.search(line):
                    problems += 1
                    print(f"{f}:{number}: {name}: {line.strip()[:100]}")
        if f.suffix == ".md":
            for number, size in bullet_runs(lines):
                problems += 1
                print(f"{f}:{number}: {size} bullets of near-identical length; vary or merge them")
    print(f"{problems} issue(s) found")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["."]))
