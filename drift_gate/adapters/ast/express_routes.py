"""Bounded Express registration AST; no imports or execution of user modules.

Default ESM import, direct const app/router declarations, literal routes and
same-module mounts only. All protected references must have an explicit role.
"""
from dataclasses import replace
import re

from drift_gate.adapters.grammar_resources import get_parser
from drift_gate.core.evaluation.static_routers import UnsupportedContract
from drift_gate.core.route_syntax import HTTP_METHODS


def walk(root):
    pending = [root]
    count = 0
    while pending:
        node = pending.pop()
        count += 1
        if count > 20_000:
            raise UnsupportedContract('Express AST node limit exceeded')
        yield node
        pending.extend(reversed(node.named_children))


def text(node):
    return node.text.decode('utf-8') if node is not None else ''


def literal(node):
    if node is None or node.type != 'string' or any(child.type != 'string_fragment' for child in node.named_children):
        raise UnsupportedContract('Express path must be a simple string literal')
    value = text(node)[1:-1]
    # Express path-to-regexp patterns/params need a separate normalization.
    if not re.fullmatch(r'/[A-Za-z0-9_./-]*', value):
        raise UnsupportedContract('Express path patterns are unsupported')
    if '//' in value or any(segment in {'.', '..'} for segment in value.split('/')):
        raise UnsupportedContract('ambiguous Express path normalization')
    return value


def extract_express_routes(source, language='javascript'):
    if source is None:
        raise UnsupportedContract('complete Express source is unavailable')
    if not source.strip():
        return set()
    if len(source.encode('utf-8')) > 1_000_000:
        raise UnsupportedContract('Express source exceeds 1 MB')
    try:
        root = get_parser(language).parse(source.encode('utf-8')).root_node
    except Exception as exc:
        raise UnsupportedContract('Express grammar unavailable') from exc
    if root.has_error:
        raise UnsupportedContract('Express source could not be parsed')
    nodes = list(walk(root))
    allowed, frameworks, receivers, routes, edges = set(), set(), {}, {}, {}
    for statement in root.named_children:
        if statement.type == 'import_statement':
            src = statement.child_by_field_name('source')
            if text(src)[1:-1] == 'express':
                if any(child.type == 'type' for child in statement.children):
                    raise UnsupportedContract('type-only Express imports have no runtime binding')
                clause = next((node for node in statement.named_children if node.type == 'import_clause'), None)
                if clause is None or len(clause.named_children) != 1 or clause.named_children[0].type != 'identifier':
                    raise UnsupportedContract('only a default Express import is supported')
                name = clause.named_children[0]
                frameworks.add(text(name)); allowed.add(name.id)
        if statement.type in {'if_statement', 'for_statement', 'for_in_statement', 'while_statement', 'try_statement', 'switch_statement'}:
            raise UnsupportedContract('conditional module registration is unsupported')
    if len(frameworks) != 1:
        raise UnsupportedContract('one default Express import is required')
    framework = next(iter(frameworks))
    for statement in root.named_children:
        if statement.type != 'lexical_declaration' or not any(child.type == 'const' for child in statement.children):
            continue
        for node in statement.named_children:
            name, value = node.child_by_field_name('name'), node.child_by_field_name('value')
            if name is None or name.type != 'identifier' or value is None or value.type != 'call_expression':
                continue
            func = value.child_by_field_name('function')
            args = value.child_by_field_name('arguments')
            kind = 'app' if text(func) == framework else 'router' if text(func) == framework + '.Router' else None
            if kind:
                if args is None or args.named_children or text(name) in receivers:
                    raise UnsupportedContract('configured or duplicate Express receiver')
                receivers[text(name)] = (kind, statement.start_byte)
                routes[text(name)] = set()
                allowed.add(name.id)
                allowed.update(child.id for child in walk(func) if child.type == 'identifier')
    if not receivers or sum(kind == 'app' for kind, _ in receivers.values()) != 1:
        raise UnsupportedContract('one directly declared Express app is required')

    def member(call):
        func = call.child_by_field_name('function')
        if func is None or func.type != 'member_expression':
            raise UnsupportedContract('unsupported Express call')
        obj, prop = func.child_by_field_name('object'), func.child_by_field_name('property')
        return obj, text(prop), call.child_by_field_name('arguments').named_children

    def registration(call, methods=()):
        obj, method, args = member(call)
        if method in HTTP_METHODS and obj.type == 'call_expression':
            if not args or any(arg.type not in {'identifier', 'arrow_function', 'function_expression'} for arg in args):
                raise UnsupportedContract('Express registration requires ordinary handlers')
            return registration(obj, (*methods, method.upper()))
        if obj.type != 'identifier' or text(obj) not in receivers:
            raise UnsupportedContract('registration receiver is not a declared Express app/router')
        owner = text(obj)
        if call.start_byte <= receivers[owner][1]:
            raise UnsupportedContract('receiver must precede its registration')
        allowed.add(obj.id)
        if method == 'use':
            if methods or len(args) != 2 or args[1].type != 'identifier' or text(args[1]) not in receivers or receivers[text(args[1])][0] != 'router':
                raise UnsupportedContract('Express use supports only a literal prefix and same-module router')
            prefix = literal(args[0])
            if call.start_byte <= receivers[text(args[1])][1]:
                raise UnsupportedContract('mounted router must be declared first')
            if prefix != '/' and prefix.endswith('/'):
                raise UnsupportedContract('trailing mount prefix is unsupported')
            allowed.add(args[1].id)
            edges.setdefault(owner, []).append((text(args[1]), prefix.rstrip('/')))
            return
        if method == 'route':
            if not methods or len(args) != 1:
                raise UnsupportedContract('route() requires chained HTTP methods')
            path = literal(args[0])
        elif method in HTTP_METHODS and not methods:
            if len(args) < 2 or any(arg.type not in {'identifier', 'arrow_function', 'function_expression'} for arg in args[1:]):
                raise UnsupportedContract('Express method requires path and ordinary handlers')
            path, methods = literal(args[0]), (method.upper(),)
        else:
            raise UnsupportedContract('unsupported Express registration method')
        for verb in methods:
            if (verb, path) in routes[owner]:
                raise UnsupportedContract('duplicate Express route identity')
            routes[owner].add((verb, path))

    for statement in root.named_children:
        if statement.type == 'expression_statement' and statement.named_children and statement.named_children[0].type == 'call_expression':
            call = statement.named_children[0]
            # Opaque top-level calls could mutate registrations indirectly.
            registration(call)
    protected = frameworks | set(receivers)
    for node in nodes:
        if node.type == 'identifier' and text(node) in protected and node.id not in allowed:
            raise UnsupportedContract('Express binding is shadowed, reassigned, escaped or used outside registration')
        if node.type == 'call_expression' and text(node.child_by_field_name('function')) in {'eval', 'Function'}:
            raise UnsupportedContract('reflective execution is unsupported')
        if node.type == 'member_expression' and text(node.child_by_field_name('object')) == 'process' and text(node.child_by_field_name('property')) == 'env':
            raise UnsupportedContract('mixed Express/environment contracts require explicit analyzers')
    output, visits = set(), 0
    def expand(owner, prefix, ancestry):
        nonlocal visits
        visits += 1
        if owner in ancestry or len(ancestry) >= 32 or visits > 256:
            raise UnsupportedContract('Express router cycle/expansion limit exceeded')
        for method, path in routes[owner]:
            key = method, prefix + path
            if key in output or len(output) >= 256:
                raise UnsupportedContract('duplicate Express route or expansion limit exceeded')
            output.add(key)
        for child, suffix in edges.get(owner, []):
            expand(child, prefix + suffix, ancestry | {owner})
    app = next(name for name, (kind, _) in receivers.items() if kind == 'app')
    expand(app, '', set())
    return output


def attach_express_routes(files):
    output = []
    for file in files:
        if file.path.endswith(('.js', '.jsx', '.ts', '.tsx')) and (file.before_source is not None or file.after_source is not None):
            language = 'tsx' if file.path.endswith('.tsx') else 'typescript' if file.path.endswith('.ts') else 'javascript'
            try:
                before = extract_express_routes('' if file.status == 'added' else file.before_source, language)
                after = extract_express_routes('' if file.status == 'deleted' else file.after_source, language)
                file = replace(file, before_routes=sorted(before), after_routes=sorted(after), route_analysis_error='')
            except (UnsupportedContract, OSError, RuntimeError) as exc:
                file = replace(file, before_routes=None, after_routes=None,
                               route_analysis_error=str(exc) if isinstance(exc, UnsupportedContract) else 'Express grammar unavailable')
        output.append(file)
    return output
