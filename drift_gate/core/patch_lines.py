"""Shared changed-line extraction; unproven comments stay code (pure)."""
import io
import re
import tokenize


def _python_comments(source):
    if source is None:
        return set()
    comments = set()
    lines = source.splitlines()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT and not lines[token.start[0] - 1][:token.start[1]].strip():
                comments.add(token.start[0])
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return set()
    return comments


def changed_lines(file, *, code_only=False):
    old = new = 1
    rows = []
    sides = {'-': [], '+': []}
    starts = {'-': None, '+': None}
    single_hunk = True
    for line in file.patch.splitlines():
        hunk = re.match(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
        if hunk:
            old, new = map(int, hunk.groups())
            if starts['-'] is not None:
                single_hunk = False
            starts['-'], starts['+'] = old, new
            continue
        if not line or line.startswith(('+++', '---', 'diff --git', 'index ', '\\')):
            continue
        marker, text = line[0], line[1:]
        if marker not in ('+', '-', ' '):
            continue
        if marker in ('-', ' '):
            sides['-'].append(text)
        if marker in ('+', ' '):
            sides['+'].append(text)
        if marker in ('+', '-'):
            rows.append((marker, text, new if marker == '+' else old))
        old += marker in ('-', ' ')
        new += marker in ('+', ' ')
    comments = {'-': set(), '+': set()}
    if file.path.endswith('.py'):
        for marker, source in [('-', file.before_source), ('+', file.after_source)]:
            offset = 0
            if source is None and single_hunk and starts[marker] is not None:
                source = '\n'.join(sides[marker])
                offset = starts[marker] - 1
            comments[marker] = {number + offset for number in _python_comments(source)}
    return [(marker, text) for marker, text, number in rows
            if not code_only or (text.strip() and number not in comments[marker])]
