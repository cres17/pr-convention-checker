"""Pure, bounded-scope Python fragment facts; invalid fragments stay unknown."""
import ast
import io
import re
import textwrap
import tokenize


def environment_keys(lines: list[str]) -> set[str] | None:
    """Static os.getenv/os.environ accesses, excluding comments and literals.

    None means the diff fragment could not be parsed, not an empty key set.
    Aliased and dynamic keys remain outside this detector's supported scope.
    """
    try:
        tree = ast.parse(textwrap.dedent('\n'.join(lines)))
    except (SyntaxError, ValueError, RecursionError):
        return None
    keys = set()
    for node in ast.walk(tree):
        key = None
        if isinstance(node, ast.Call) and node.args:
            if _name(node.func) in {'os.getenv', 'os.environ.get', 'getenv'}:
                key = node.args[0]
        elif isinstance(node, ast.Subscript) and _name(node.value) == 'os.environ':
            key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str) and re.fullmatch(r'[A-Z][A-Z0-9_]*', key.value):
            keys.add(key.value)
    return keys


def _name(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _name(node.value) + '.' + node.attr
    return ''


def without_literals(lines: list[str]) -> list[str]:
    """Mask strings/comments only for word-based heuristics, retaining layout.

    On an incomplete token stream retain the original conservative input.
    Literal-dependent checks (routes, environment keys) use their own detector.
    """
    source = '\n'.join(lines)
    masked = [list(line) for line in lines]
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type not in (tokenize.STRING, tokenize.COMMENT):
                continue
            (first, start), (last, end) = token.start, token.end
            for number in range(first, last + 1):
                row = masked[number - 1]
                left = start if number == first else 0
                right = end if number == last else len(row)
                row[left:right] = ' ' * (right - left)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return lines
    return [''.join(line) for line in masked]
