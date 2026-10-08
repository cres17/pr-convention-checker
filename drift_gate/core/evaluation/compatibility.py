"""Direction-aware OpenAPI compatibility (design W14 13.2).

Consistency (implementation matches the document) and compatibility (existing
consumers keep working) are separate predicates. Compatibility here is strict
JSON Schema language inclusion between the before and after documents:

  response:  every value the new server may send was valid before   (new ⊆ old)
  request:   every value an existing client may send is still valid (old ⊆ new)

Supported profiles: primitive ``type``, ``required``, ``nullable`` (OpenAPI 3.0
flag and 3.1 ``"null"`` type), ``enum``, object ``properties`` /
``additionalProperties`` (default true, as in JSON Schema), array ``items``,
response status codes and media types, request body requirement and
parameters. Composites: local ``$ref`` (``#/components/schemas``), ``allOf``
with mergeable object/type constraints, ``oneOf``/``anyOf`` as unions (only
the sound "each new alternative fits some old alternative" direction proves
compatibility). Recursive references compare equal only when both sides are
byte-identical definitions; anything else outside these profiles is U, never a
silent pass. Real consumers may tolerate more than strict inclusion.
"""
from dataclasses import dataclass
import json

from drift_gate.core.contracts.planner import Truth

PRIMITIVES = ('string', 'integer', 'number', 'boolean', 'object', 'array', 'null')
MAX_DEPTH = 16
METHODS = ('get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace')


class Unsupported(Exception):
    """Schema construct outside the supported compatibility profiles."""


@dataclass(frozen=True)
class Node:
    types: frozenset              # allowed JSON types; all PRIMITIVES = unconstrained type
    enum: tuple | None = None     # canonical JSON strings
    properties: tuple = ()        # ((name, Node), ...)
    required: frozenset = frozenset()
    additional: object = True     # True, False or Node
    items: object = None          # Node or None (unconstrained)
    alternatives: tuple = ()      # union members (oneOf/anyOf); empty = not a union
    recursive: str = ''           # reference name when cut at a cycle


ANY = Node(frozenset(PRIMITIVES))


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _resolve(ref, components):
    prefix = '#/components/schemas/'
    if not isinstance(ref, str) or not ref.startswith(prefix):
        raise Unsupported(f'non-local $ref {ref!r}')
    name = ref[len(prefix):]
    if name not in components:
        raise Unsupported(f'unresolved $ref {ref!r}')
    return name, components[name]


def normalize(schema, components, *, depth=0, stack=()):
    if depth > MAX_DEPTH:
        raise Unsupported('schema depth limit')
    if schema is True or schema == {}:
        return ANY
    if not isinstance(schema, dict):
        raise Unsupported('schema must be an object')
    if '$ref' in schema:
        if set(schema) - {'$ref', 'description', 'summary'}:
            raise Unsupported('$ref with sibling constraints')
        name, target = _resolve(schema['$ref'], components)
        if name in stack:
            return Node(frozenset(PRIMITIVES), recursive=name)
        return normalize(target, components, depth=depth + 1, stack=(*stack, name))
    known = {'type', 'nullable', 'enum', 'properties', 'required', 'additionalProperties', 'items', 'allOf',
             'oneOf', 'anyOf', 'description', 'title', 'example', 'examples', 'format', 'default', 'deprecated',
             'readOnly', 'writeOnly'}
    unknown = set(schema) - known
    if unknown:
        raise Unsupported(f'unsupported keywords {sorted(unknown)}')
    if 'default' in schema:
        pass  # defaults change behaviour, not the accepted value set; not part of inclusion
    for name in ('oneOf', 'anyOf'):
        if name in schema:
            if set(schema) - {name, 'description', 'title'}:
                raise Unsupported(f'{name} with sibling constraints')
            members = tuple(normalize(item, components, depth=depth + 1, stack=stack) for item in schema[name])
            if not members:
                raise Unsupported(f'empty {name}')
            return Node(frozenset(PRIMITIVES), alternatives=members)
    if 'allOf' in schema:
        parts = [normalize(item, components, depth=depth + 1, stack=stack) for item in schema['allOf']]
        rest = {k: v for k, v in schema.items() if k != 'allOf'}
        if rest and set(rest) - {'description', 'title'}:
            parts.append(normalize(rest, components, depth=depth + 1, stack=stack))
        return _merge(parts)
    declared = schema.get('type')
    if declared is None:
        types = set(PRIMITIVES)
    elif isinstance(declared, str):
        types = {declared}
    elif isinstance(declared, list) and declared:
        types = set(declared)
    else:
        raise Unsupported('invalid type')
    if types - set(PRIMITIVES):
        raise Unsupported(f'unknown type {sorted(types - set(PRIMITIVES))}')
    if schema.get('nullable') is True:
        types.add('null')
    if 'integer' in types and 'number' not in types:
        pass  # integer ⊂ number is handled in _subset
    enum = None
    if 'enum' in schema:
        if not isinstance(schema['enum'], list) or not schema['enum']:
            raise Unsupported('enum must be a nonempty list')
        enum = tuple(sorted({_canonical(value) for value in schema['enum']}))
    properties = {}
    for name, sub in (schema.get('properties') or {}).items():
        properties[name] = normalize(sub, components, depth=depth + 1, stack=stack)
    required = frozenset(schema.get('required') or ())
    additional = schema.get('additionalProperties', True)
    if isinstance(additional, dict):
        additional = normalize(additional, components, depth=depth + 1, stack=stack)
    elif additional not in (True, False):
        raise Unsupported('additionalProperties must be a boolean or schema')
    items = normalize(schema['items'], components, depth=depth + 1, stack=stack) if 'items' in schema else None
    return Node(frozenset(types), enum, tuple(sorted(properties.items())), required, additional, items)


def _merge(parts):
    types = frozenset(PRIMITIVES)
    properties, required, enum, additional, items = {}, set(), None, True, None
    for part in parts:
        if part.alternatives or part.recursive:
            raise Unsupported('allOf over unions or recursive references')
        types &= part.types
        for name, node in part.properties:
            if name in properties and properties[name] != node:
                raise Unsupported(f'allOf property {name} has conflicting schemas')
            properties[name] = node
        required |= part.required
        if part.enum is not None:
            enum = part.enum if enum is None else tuple(sorted(set(enum) & set(part.enum)))
        if part.additional is not True:
            if additional is not True and additional != part.additional:
                raise Unsupported('allOf additionalProperties conflict')
            additional = part.additional
        if part.items is not None:
            if items is not None and items != part.items:
                raise Unsupported('allOf items conflict')
            items = part.items
    if not types:
        raise Unsupported('allOf has no common type')
    return Node(types, enum, tuple(sorted(properties.items())), frozenset(required), additional, items)


def _and(values):
    values = list(values)
    if Truth.FALSE in values:
        return Truth.FALSE
    return Truth.UNKNOWN if Truth.UNKNOWN in values else Truth.TRUE


def _type_subset(a, b):
    expanded = set(b) | ({'integer'} if 'number' in b else set())
    return set(a) <= expanded


def subset(a, b, path, witnesses):
    """Truth of L(a) ⊆ L(b); appends ``(path, check)`` witnesses for proven F."""
    if a.recursive or b.recursive:
        if a.recursive and a.recursive == b.recursive:
            return Truth.UNKNOWN  # equality of recursive definitions is decided by the caller
        return Truth.UNKNOWN
    if b == ANY:
        return Truth.TRUE
    if a.alternatives:
        return _and(subset(member, b, path, witnesses) for member in a.alternatives)
    if b.alternatives:
        local = []
        results = [subset(a, member, path, local) for member in b.alternatives]
        return Truth.TRUE if Truth.TRUE in results else Truth.UNKNOWN
    if a.enum is not None:
        # Finite left side: decide value by value.
        values = [json.loads(v) for v in a.enum if admits(Node(a.types, None, a.properties, a.required, a.additional,
                                                                 a.items), json.loads(v)) == Truth.TRUE]
        results = [admits(b, value) for value in values]
        if Truth.FALSE in results:
            return _fail(witnesses, path, 'enum')
        return Truth.UNKNOWN if Truth.UNKNOWN in results else Truth.TRUE
    if b.enum is not None:
        if a.types & {'string', 'integer', 'number', 'object', 'array'}:
            return _fail(witnesses, path, 'enum')  # infinitely many values cannot fit a finite enum
        finite = ([True, False] if 'boolean' in a.types else []) + ([None] if 'null' in a.types else [])
        results = [admits(b, value) for value in finite]
        if Truth.FALSE in results:
            return _fail(witnesses, path, 'enum')
        return Truth.UNKNOWN if Truth.UNKNOWN in results else Truth.TRUE
    if not _type_subset(a.types, b.types):
        check = 'nullable' if a.types - set(b.types) == {'null'} else 'type'
        return _fail(witnesses, path, check)
    results = []
    if 'object' in a.types and 'object' in b.types:
        results.append(_object_subset(a, b, path, witnesses))
    if 'array' in a.types and 'array' in b.types and b.items is not None:
        results.append(subset(a.items or ANY, b.items, path + '[]', witnesses))
    return _and(results)


def admits(node, value):
    """Truth that a concrete JSON value is in L(node)."""
    if node.recursive:
        return Truth.UNKNOWN
    if node.alternatives:
        results = [admits(member, value) for member in node.alternatives]
        return Truth.TRUE if Truth.TRUE in results else Truth.UNKNOWN if Truth.UNKNOWN in results else Truth.FALSE
    if node.enum is not None and _canonical(value) not in node.enum:
        return Truth.FALSE
    kind = _value_type(_canonical(value))
    if not (kind in node.types or kind == 'integer' and 'number' in node.types):
        return Truth.FALSE
    if kind == 'object':
        if not node.required <= set(value):
            return Truth.FALSE
        properties, results = dict(node.properties), []
        for key, item in value.items():
            schema = properties.get(key, node.additional if isinstance(node.additional, Node) else
                                     ANY if node.additional else None)
            if schema is None:
                return Truth.FALSE
            results.append(admits(schema, item))
        return _and(results)
    if kind == 'array' and node.items is not None:
        return _and(admits(node.items, item) for item in value)
    return Truth.TRUE


def _value_type(canonical):
    value = json.loads(canonical)
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    return {float: 'number', str: 'string', list: 'array', dict: 'object'}[type(value)]


def _fail(witnesses, path, check):
    witnesses.append((path, check))
    return Truth.FALSE


def _object_subset(a, b, path, witnesses):
    a_props, b_props = dict(a.properties), dict(b.properties)
    results = []
    for name in sorted(b.required - a.required):
        witnesses.append((f'{path}.{name}', 'required'))
        results.append(Truth.FALSE)
    for name in sorted(set(a_props) | set(b_props)):
        left = a_props.get(name, a.additional if isinstance(a.additional, Node) else ANY if a.additional else None)
        right = b_props.get(name, b.additional if isinstance(b.additional, Node) else ANY if b.additional else None)
        if left is None:
            continue  # a never admits this property
        if right is None:
            witnesses.append((f'{path}.{name}', 'additional-properties'))
            results.append(Truth.FALSE)
            continue
        results.append(subset(left, right, f'{path}.{name}', witnesses))
    if a.additional is not False and b.additional is not True:
        # a admits unlisted properties that b restricts or forbids.
        if b.additional is False:
            witnesses.append((path, 'additional-properties'))
            results.append(Truth.FALSE)
        else:
            results.append(subset(a.additional if isinstance(a.additional, Node) else ANY, b.additional,
                                  path + '.*', witnesses))
    return _and(results)


@dataclass(frozen=True)
class Finding:
    operation: str
    location: str
    check: str
    detail: str = ''

    def to_dict(self):
        return {'operation': self.operation, 'location': self.location, 'check': self.check, 'detail': self.detail}


@dataclass(frozen=True)
class CompatibilityResult:
    truth: Truth
    breaking: tuple
    unknown: tuple
    direction: str

    def to_dict(self):
        return {'schema': 'api-compatibility-v1', 'direction': self.direction, 'truth': self.truth.value,
                'breaking': [item.to_dict() for item in self.breaking],
                'unknown': [item.to_dict() for item in self.unknown],
                'semantics': 'strict-json-schema-inclusion'}


def _components(document):
    return ((document.get('components') or {}).get('schemas') or {})


def _operations(document):
    paths = document.get('paths')
    if not isinstance(paths, dict):
        raise Unsupported('document has no paths object')
    rows = {}
    for path, item in paths.items():
        if not isinstance(item, dict) or '$ref' in item:
            raise Unsupported(f'path item {path} is not inline')
        for method in METHODS:
            if method in item:
                rows[f'{method.upper()} {path}'] = item[method]
    return rows


def _closure(schema, components):
    """Canonical text of every definition reachable through local $ref."""
    seen, pending = {}, [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            ref = node.get('$ref')
            if isinstance(ref, str) and ref.startswith('#/components/schemas/'):
                name = ref.rsplit('/', 1)[1]
                if name not in seen and name in components:
                    seen[name] = _canonical(components[name])
                    pending.append(components[name])
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return seen


def _schema_pair(old, new, old_doc, new_doc, operation, location, direction, breaking, unknown):
    try:
        a = normalize(old, _components(old_doc))
        b = normalize(new, _components(new_doc))
    except Unsupported as exc:
        unknown.append(Finding(operation, location, 'unsupported', str(exc)))
        return
    if _canonical(old) == _canonical(new) and _closure(old, _components(old_doc)) == _closure(new, _components(new_doc)):
        return  # identical schema and identical referenced definitions (including recursive ones)
    witnesses = []
    truth = subset(b, a, location, witnesses) if direction == 'response' else subset(a, b, location, witnesses)
    if truth == Truth.FALSE:
        breaking.extend(Finding(operation, path, check) for path, check in witnesses)
    elif truth == Truth.UNKNOWN:
        unknown.append(Finding(operation, location, 'undecided'))


def compare_documents(old_doc, new_doc, direction):
    if direction not in {'request', 'response'}:
        raise ValueError('direction must be request or response')
    breaking, unknown = [], []
    try:
        old_ops, new_ops = _operations(old_doc), _operations(new_doc)
    except Unsupported as exc:
        return CompatibilityResult(Truth.UNKNOWN, (), (Finding('*', '*', 'unsupported', str(exc)),), direction)
    for operation in sorted(old_ops):
        if operation not in new_ops:
            breaking.append(Finding(operation, 'operation', 'removed-operation'))
            continue
        old, new = old_ops[operation], new_ops[operation]
        if direction == 'response':
            _responses(operation, old, new, old_doc, new_doc, breaking, unknown)
        else:
            _requests(operation, old, new, old_doc, new_doc, breaking, unknown)
    truth = Truth.FALSE if breaking else Truth.UNKNOWN if unknown else Truth.TRUE
    return CompatibilityResult(truth, tuple(breaking), tuple(unknown), direction)


def _content(container):
    content = (container or {}).get('content') or {}
    if not isinstance(content, dict):
        raise Unsupported('content must be an object')
    return content


def _responses(operation, old, new, old_doc, new_doc, breaking, unknown):
    old_res, new_res = old.get('responses') or {}, new.get('responses') or {}
    for status in sorted(set(new_res) - set(old_res)):
        if status != 'default' and 'default' not in old_res:
            breaking.append(Finding(operation, f'responses.{status}', 'status-added'))
    for status in sorted(set(new_res) & set(old_res)):
        try:
            old_media, new_media = _content(old_res[status]), _content(new_res[status])
        except Unsupported as exc:
            unknown.append(Finding(operation, f'responses.{status}', 'unsupported', str(exc)))
            continue
        for media in sorted(set(new_media) - set(old_media)):
            breaking.append(Finding(operation, f'responses.{status}.{media}', 'media-added'))
        for media in sorted(set(new_media) & set(old_media)):
            _schema_pair(old_media[media].get('schema', {}), new_media[media].get('schema', {}), old_doc, new_doc,
                         operation, f'responses.{status}.{media}', 'response', breaking, unknown)


def _requests(operation, old, new, old_doc, new_doc, breaking, unknown):
    old_body, new_body = old.get('requestBody'), new.get('requestBody')
    if new_body and new_body.get('required') and not (old_body and old_body.get('required')):
        breaking.append(Finding(operation, 'requestBody', 'body-became-required'))
    if old_body and not new_body:
        unknown.append(Finding(operation, 'requestBody', 'body-removed-framework-dependent'))
    if old_body and new_body:
        try:
            old_media, new_media = _content(old_body), _content(new_body)
        except Unsupported as exc:
            unknown.append(Finding(operation, 'requestBody', 'unsupported', str(exc)))
        else:
            for media in sorted(set(old_media) - set(new_media)):
                breaking.append(Finding(operation, f'requestBody.{media}', 'media-removed'))
            for media in sorted(set(old_media) & set(new_media)):
                _schema_pair(old_media[media].get('schema', {}), new_media[media].get('schema', {}), old_doc,
                             new_doc, operation, f'requestBody.{media}', 'request', breaking, unknown)
    old_params = {(p.get('in'), p.get('name')): p for p in old.get('parameters') or [] if isinstance(p, dict)}
    new_params = {(p.get('in'), p.get('name')): p for p in new.get('parameters') or [] if isinstance(p, dict)}
    for key in sorted(set(new_params) - set(old_params)):
        if new_params[key].get('required'):
            breaking.append(Finding(operation, f'parameters.{key[0]}.{key[1]}', 'required-parameter-added'))
    for key in sorted(set(old_params) - set(new_params)):
        unknown.append(Finding(operation, f'parameters.{key[0]}.{key[1]}', 'parameter-removed-framework-dependent'))
    for key in sorted(set(old_params) & set(new_params)):
        if new_params[key].get('required') and not old_params[key].get('required'):
            breaking.append(Finding(operation, f'parameters.{key[0]}.{key[1]}', 'parameter-became-required'))
        _schema_pair(old_params[key].get('schema', {}), new_params[key].get('schema', {}), old_doc, new_doc,
                     operation, f'parameters.{key[0]}.{key[1]}', 'request', breaking, unknown)


def compatibility_requirement(group, triggers, changed_files, session=None):
    """Policy adapter: every selected OpenAPI JSON document must stay compatible in the group's direction."""
    from drift_gate.core.evaluation.content_result import ContentCheck, combine, unknown as open_check
    from drift_gate.utils.glob_matcher import matches_any
    directions = ('request', 'response') if group.direction == 'both' else (group.direction,)
    checks = []
    for file in changed_files:
        if not matches_any(file.path, list(group.any_changed or group.all_changed)):
            continue
        if not file.path.lower().endswith('.json'):
            checks.append(open_check('api-compatibility supports OpenAPI JSON documents', 'api-compatibility'))
            continue
        if file.status in {'added', 'deleted'} or file.before_source is None or file.after_source is None:
            checks.append(open_check('before and after documents are both required', 'api-compatibility'))
            continue
        try:
            old_doc, new_doc = json.loads(file.before_source), json.loads(file.after_source)
        except ValueError:
            checks.append(open_check('document is not valid JSON', 'api-compatibility'))
            continue
        for direction in directions:
            result = compare_documents(old_doc, new_doc, direction)
            reason = (f'{file.path} {direction}: ' + ('; '.join(f'{b.operation} {b.location} {b.check}'
                      for b in result.breaking[:10]) or 'compatible' if result.truth != Truth.UNKNOWN
                      else f'{len(result.unknown)} construct(s) outside supported profiles'))
            decision = {Truth.TRUE: 'satisfied', Truth.FALSE: 'violated', Truth.UNKNOWN: 'undetermined'}[result.truth]
            checks.append(ContentCheck(decision, 'verified' if result.truth != Truth.UNKNOWN else 'unverified',
                                       reason, 'api-compatibility'))
    if not checks:
        return ContentCheck('satisfied', 'not-applicable', 'No selected OpenAPI document changed', 'api-compatibility')
    return combine(checks, require_all=True, mode='api-compatibility')
