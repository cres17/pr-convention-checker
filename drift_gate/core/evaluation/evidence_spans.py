"""Link individual facts to byte ranges of the exact original bytes (design W07/W08).

A span names an artifact by its raw SHA-256 and a half-open byte range
``[start, end)`` of those bytes. Spans are computed and verified from bytes the
caller supplies; this module never reads files. A verified span shows where in
the stored original the analyzer's evidence sits. It does not prove that the
analyzer interpreted that text correctly.
"""
import ast
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from drift_gate.core.route_syntax import HTTP_METHODS

KINDS = ('python-route-decorator', 'python-env-key-literal', 'document-route-text', 'openapi-path-key')


@dataclass(frozen=True)
class EvidenceSpan:
    artifact_sha256: str
    artifact_path: str
    artifact_revision: str
    kind: str
    identity: tuple
    start: int
    end: int

    def __post_init__(self):
        if not isinstance(self.artifact_sha256, str) or not re.fullmatch('[0-9a-f]{64}', self.artifact_sha256):
            raise ValueError('span requires the artifact SHA-256')
        if self.kind not in KINDS:
            raise ValueError('unknown span kind')
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start < self.end:
            raise ValueError('span requires a nonempty half-open byte range')
        if not isinstance(self.identity, tuple) or not self.identity:
            raise ValueError('span requires a fact identity')

    def to_dict(self):
        return {'artifact_sha256': self.artifact_sha256, 'artifact_path': self.artifact_path,
                'artifact_revision': self.artifact_revision, 'kind': self.kind,
                'identity': list(self.identity), 'byte_range': [self.start, self.end]}


def _line_offsets(raw):
    offsets, total = [0], 0
    for line in raw.splitlines(keepends=True):
        total += len(line)
        offsets.append(total)
    return offsets


def _node_range(node, offsets):
    # CPython AST column offsets are UTF-8 byte offsets within the line.
    return offsets[node.lineno - 1] + node.col_offset, offsets[node.end_lineno - 1] + node.end_col_offset


def _parse(raw):
    try:
        return ast.parse(raw.decode('utf-8'))
    except (SyntaxError, ValueError, UnicodeDecodeError, RecursionError):
        return None


def python_route_spans(raw, identities, *, artifact):
    """Decorator calls ``<router>.<method>("<suffix>")`` whose literal ends the routed path."""
    tree = _parse(raw)
    if tree is None:
        return [], sorted(identities)
    offsets = _line_offsets(raw)
    candidates = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in HTTP_METHODS and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            candidates.append((node.func.attr.upper(), node.args[0].value, _node_range(node, offsets)))
    spans, unresolved = [], []
    for method, path in sorted(identities):
        matched = [rng for m, literal, rng in candidates
                   if m == method and (path == literal or (literal and path.endswith(literal)))]
        if len(matched) != 1:
            unresolved.append((method, path))  # absent or ambiguous: no span is better than a guess
            continue
        start, end = matched[0]
        spans.append(EvidenceSpan(artifact['sha256'], artifact['path'], artifact['revision'],
                                  'python-route-decorator', (method, path), start, end))
    return spans, unresolved


def env_key_spans(raw, keys, *, artifact):
    tree = _parse(raw)
    if tree is None:
        return [], sorted(keys)
    offsets = _line_offsets(raw)
    found = {}

    def literal(node):
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    for node in ast.walk(tree):
        # Only key literals in an environment access: getenv(K), environ.get(K), environ[K].
        key = None
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''
            if name == 'getenv' or name == 'get' and isinstance(func, ast.Attribute) and (
                    isinstance(func.value, ast.Attribute) and func.value.attr == 'environ'
                    or isinstance(func.value, ast.Name) and func.value.id == 'environ'):
                key, target = literal(node.args[0]), node.args[0]
        elif isinstance(node, ast.Subscript) and (
                isinstance(node.value, ast.Attribute) and node.value.attr == 'environ'
                or isinstance(node.value, ast.Name) and node.value.id == 'environ'):
            key, target = literal(node.slice), node.slice
        if key in keys:
            found.setdefault(key, []).append(_node_range(target, offsets))
    spans, unresolved = [], []
    for key in sorted(keys):
        if key not in found:
            unresolved.append(key)
            continue
        start, end = min(found[key])  # first access literal of this key
        spans.append(EvidenceSpan(artifact['sha256'], artifact['path'], artifact['revision'],
                                  'python-env-key-literal', (key,), start, end))
    return spans, unresolved


def document_route_spans(raw, identities, *, artifact):
    """Lexical location of each documented route: Markdown text or OpenAPI path keys."""
    spans, unresolved = [], []
    path = artifact['path'].lower()
    for method, route in sorted(identities):
        if path.endswith('.json'):
            # The path key, not the operation: JSON object member order carries no method span.
            pattern = re.compile(re.escape(json.dumps(route).encode('utf-8')) + rb'\s*:')
            kind = 'openapi-path-key'
        else:
            pattern = re.compile(rb'(?i)\b' + re.escape(method.encode()) + rb'\b[ \t|]+' + re.escape(route.encode('utf-8'))
                                 + rb'(?![^\s`\'"<>|])')
            kind = 'document-route-text'
        match = pattern.search(raw)
        if match is None:
            unresolved.append((method, route))
            continue
        spans.append(EvidenceSpan(artifact['sha256'], artifact['path'], artifact['revision'], kind,
                                  (method, route), match.start(), match.end()))
    return spans, unresolved


def _boundary(raw, start):
    return start == 0 or not (chr(raw[start - 1]).isalnum() or raw[start - 1] in b'_.')


def _expression(text):
    try:
        return ast.parse(text, mode='eval').body
    except (SyntaxError, ValueError, RecursionError):
        return None


def verify_span(raw, span):
    """Re-check a span against bytes: hash, bounds, token boundary and the exact construct."""
    if sha256(raw).hexdigest() != span.artifact_sha256 or span.end > len(raw) or not _boundary(raw, span.start):
        return False
    try:
        text = raw[span.start:span.end].decode('utf-8')
    except UnicodeDecodeError:
        return False
    if span.kind == 'python-env-key-literal':
        node = _expression(text)
        return isinstance(node, ast.Constant) and node.value == span.identity[0]
    method, route = span.identity
    if span.kind == 'openapi-path-key':
        return text.startswith(json.dumps(route)) and text.rstrip().endswith(':')
    if span.kind == 'python-route-decorator':
        node = _expression(text)
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == method.lower() and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str) and node.args[0].value
                and (route == node.args[0].value or route.endswith(node.args[0].value)))
    return (text[:len(method)].upper() == method and text.endswith(route)
            and (span.end == len(raw) or chr(raw[span.end]) in ' \t\r\n|`\'"<>'))
