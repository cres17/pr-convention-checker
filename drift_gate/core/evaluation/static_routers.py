"""Bounded same-module routing graph. No imports or application execution."""
import ast
from dataclasses import dataclass


class UnsupportedContract(ValueError):
    pass


def literal_prefix(keywords):
    if not keywords:
        return ''
    if (len(keywords) != 1 or keywords[0].arg != 'prefix'
            or not isinstance(keywords[0].value, ast.Constant)
            or not isinstance(keywords[0].value.value, str)):
        raise UnsupportedContract('only literal router prefixes are supported')
    prefix = keywords[0].value.value
    if prefix and (not prefix.startswith('/') or prefix.endswith('/')):
        raise UnsupportedContract('router prefix must start with / and must not end with /')
    return prefix


@dataclass(frozen=True)
class Receiver:
    kind: str
    prefix: str
    line: int


class StaticRouters:
    def __init__(self, tree, imports):
        self.receivers = {}
        self.edges = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call) or not isinstance(node.value.func, ast.Name):
                continue
            kind = node.value.func.id
            if kind not in {'FastAPI', 'APIRouter'}:
                continue
            if (('fastapi', kind) not in imports or node.value.args or len(node.targets) != 1
                    or not isinstance(node.targets[0], ast.Name)):
                raise UnsupportedContract('aliased app/router declaration is unsupported')
            if kind == 'FastAPI' and node.value.keywords:
                raise UnsupportedContract('configured FastAPI declaration is unsupported')
            prefix = literal_prefix(node.value.keywords)
            self.receivers[node.targets[0].id] = Receiver(kind, prefix, node.lineno)
        self._collect_edges(tree)

    def _collect_edges(self, tree):
        accepted = set()
        last_route = max((n.lineno for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.decorator_list), default=0)
        for node in tree.body:
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            if not isinstance(call.func, ast.Attribute) or call.func.attr != 'include_router':
                continue
            if (not isinstance(call.func.value, ast.Name) or call.func.value.id not in self.receivers
                    or len(call.args) != 1 or not isinstance(call.args[0], ast.Name)
                    or call.args[0].id not in self.receivers):
                raise UnsupportedContract('include_router requires same-module declared receivers')
            parent, child = call.func.value.id, call.args[0].id
            if self.receivers[child].kind != 'APIRouter':
                raise UnsupportedContract('only APIRouter children are supported')
            if node.lineno <= max(last_route, self.receivers[parent].line, self.receivers[child].line):
                raise UnsupportedContract('include_router must follow all route and receiver declarations')
            self.edges.setdefault(parent, []).append((child, literal_prefix(call.keywords), node.lineno))
            accepted.add(id(call))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {'mount', 'add_api_route', 'api_route', 'route'}:
                raise UnsupportedContract('dynamic or mounted routing is unsupported')
            if node.func.attr == 'include_router' and id(node) not in accepted:
                raise UnsupportedContract('conditional or nested include_router is unsupported')
        for edges in self.edges.values():
            for child, _, line in edges:
                if any(nested_line >= line for _, _, nested_line in self.edges.get(child, [])):
                    raise UnsupportedContract('child router composition must precede parent inclusion')

    def expand(self, routes):
        apps = [name for name, receiver in self.receivers.items() if receiver.kind == 'FastAPI']
        if len(apps) > 1 or (not apps and len(self.receivers) > 1):
            raise UnsupportedContract('a module must have one application or one standalone router')
        roots = apps or list(self.receivers)
        output = {}
        visits = 0

        def visit(name, prefix, ancestry):
            nonlocal visits
            visits += 1
            if name in ancestry or len(ancestry) >= 32 or visits > 256:
                raise UnsupportedContract('router cycle or expansion limit exceeded')
            own_prefix = prefix + self.receivers[name].prefix
            for (method, path), fields in routes.get(name, {}).items():
                key = method, own_prefix + path
                if key in output:
                    raise UnsupportedContract('duplicate method/path identity after router composition')
                if len(output) >= 256:
                    raise UnsupportedContract('router expansion limit exceeded')
                output[key] = fields
            for child, extra, _ in self.edges.get(name, []):
                visit(child, own_prefix + extra, ancestry | {name})
        for root in roots:
            visit(root, '', set())
        return output
