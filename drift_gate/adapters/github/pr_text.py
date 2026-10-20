"""Which parts of a pull request description count as written instructions."""
import re

_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})[^\n]*$")


def mask_inactive_markup(body):
    """Blank out HTML comments and fenced code blocks; every other character stays in place.

    A pull request template can carry an example inside a comment, and a
    description can quote the directive syntax in a code block. Neither is the
    author asking for a waiver, so directive parsing ignores them. Newlines are
    kept, so line-based matching sees the same lines. An unterminated comment or
    fence runs to the end of the text, as Markdown renders it.
    """
    def blank(match):
        return re.sub(r"[^\n]", " ", match.group(0))

    out, fence = [], None
    for line in _COMMENT.sub(blank, body).split("\n"):
        if fence is None:
            opened = _FENCE_OPEN.match(line)
            if opened and not (opened.group(1)[0] == "`" and "`" in line.lstrip(" `")):
                fence = opened.group(1)
                out.append(" " * len(line))
            else:
                out.append(line)
            continue
        out.append(" " * len(line))
        if re.match(r"^ {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*$", line):
            fence = None
    return "\n".join(out)
