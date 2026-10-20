"""Escaping for Markdown text that is not written by Drift Gate itself.

File paths, policy messages, ``reason:`` lines from the pull request description
and model output all end up in a pull request comment. Left raw they can close
a code span, open a code fence, add links or images, notify people, or make the
report look like something else. These helpers keep such text inert; they do
not try to sanitize HTML for security, since GitHub already does that.
"""
import html
import re

_ZERO_WIDTH = "\u200b"
_SPACES = re.compile(r"\s+")
_ALWAYS = re.compile(r"([\\`*\[\]|~])")
_UNDERSCORE = re.compile(r"(?<![0-9A-Za-z])_|_(?![0-9A-Za-z])")
_LINE_START = re.compile(r"^(\s*)(#{1,6}(?=\s|$)|[-+=])")
_ORDERED_START = re.compile(r"^(\s*\d+)([.)])(?=\s|$)")
_MENTION = re.compile(r"@(?=[A-Za-z0-9_])")
_BACKTICK_RUN = re.compile(r"`+")
_FENCE_RUN = re.compile(r"(?m)^[ \t]*(`{3,}|~{3,})")


def _escape_line(line):
    line = html.escape(line, quote=False)
    line = _ALWAYS.sub(r"\\\1", line)
    line = _UNDERSCORE.sub(lambda match: "\\" + match.group(0), line)
    line = _MENTION.sub("@" + _ZERO_WIDTH, line)
    line = _ORDERED_START.sub(lambda match: match.group(1) + "\\" + match.group(2), line, count=1)
    return _LINE_START.sub(lambda match: match.group(1) + "\\" + match.group(2), line, count=1)


def text(value):
    """Inline text on one line: whitespace collapsed, Markdown and HTML made inert."""
    return _escape_line(_SPACES.sub(" ", str(value if value is not None else "")).strip())


def block(value):
    """Multi-line text: every line escaped on its own, line breaks kept."""
    raw = str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_escape_line(line.rstrip()) for line in raw.split("\n"))


def code(value, *, table=False):
    """A code span that the value cannot close, on one line."""
    flat = _SPACES.sub(" ", str(value if value is not None else "")).strip()
    if table:
        flat = flat.replace("|", "\\|")
    longest = max((len(run) for run in _BACKTICK_RUN.findall(flat)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if flat.startswith("`") or flat.endswith("`") else ""
    return f"{fence}{pad}{flat}{pad}{fence}"


def fenced(value, language=""):
    """A code block whose fence is longer than any fence inside the value."""
    body = str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n")
    longest = max((len(run) for run in _FENCE_RUN.findall(body)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{body}\n{fence}"
