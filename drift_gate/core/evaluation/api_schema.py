"""Bounded static FastAPI response contracts compared with OpenAPI JSON.

Same-file FastAPI/APIRouter declarations support bounded literal composition.
Known route identities retain local shape uncertainty. This never imports or
executes application code. Unknown routing invalidates the combined scope.
"""
import ast
import math
import re
from collections import Counter
from dataclasses import dataclass

from drift_gate.core.evaluation.static_routers import StaticRouters, UnsupportedContract
from drift_gate.core.evaluation.analysis_session import AnalysisSession
from drift_gate.core.evaluation.openapi_document import load_openapi

from drift_gate.core.evaluation.content_result import ContentCheck, checked, unknown, combine
from drift_gate.utils.glob_matcher import matches_any

METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
TYPES = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}


@dataclass(frozen=True)
class UnknownResponse:
    reason: str


def _isolated_shape(model):
    """Only plain annotations/defaults can have route-local uncertainty."""
    if model.decorator_list or model.keywords or len(model.bases) != 1 or not isinstance(model.bases[0], ast.Name) or model.bases[0].id != "BaseModel":
        return False
    for node in model.body:
        if isinstance(node, ast.Pass):
            continue
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            return False
        if node.value is not None and not isinstance(node.value, ast.Constant):
            return False
        for part in ast.walk(node.annotation):
            if not isinstance(part, (ast.Name, ast.Load, ast.Subscript, ast.Tuple, ast.Constant, ast.BinOp, ast.BitOr)):
                return False
            if isinstance(part, ast.Name) and part.id not in set(TYPES) | {"list", "dict", "tuple", "set"}:
                return False
    return True


def _primitive_fields(model):
    if model.decorator_list:
        raise UnsupportedContract("decorated response models are unsupported")
    if len(model.bases) != 1 or not isinstance(model.bases[0], ast.Name) or model.bases[0].id != "BaseModel" or model.keywords:
        raise UnsupportedContract("model inheritance or configuration is unsupported")
    fields = {}
    for node in model.body:
        if isinstance(node, ast.Pass) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            continue
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name) or not isinstance(node.annotation, ast.Name) or node.annotation.id not in TYPES:
            raise UnsupportedContract("only directly annotated primitive response fields are supported")
        name = node.target.id
        if name.startswith("_") or name in fields or name in TYPES:
            raise UnsupportedContract("private, duplicate, or primitive-shadowing response fields are unsupported")
        field = {"type": TYPES[node.annotation.id], "required": node.value is None}
        if node.value is not None:
            if not isinstance(node.value, ast.Constant) or type(node.value.value) not in {str, int, float, bool}:
                raise UnsupportedContract("computed or nullable field defaults are unsupported")
            expected = {"str": str, "int": int, "float": float, "bool": bool}[node.annotation.id]
            if type(node.value.value) is not expected:
                raise UnsupportedContract("field default and annotation must agree")
            if isinstance(node.value.value, float) and not math.isfinite(node.value.value):
                raise UnsupportedContract("non-finite field defaults are unsupported")
            field["default"] = node.value.value
        fields[name] = field
    return fields


def _extract_contracts(source, *, routes_only=False):
    """Return {(HTTP method, path): primitive schema}, or raise unsupported."""
    if source is None:
        raise UnsupportedContract("complete before/after Python source is unavailable")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise UnsupportedContract("Python source could not be parsed") from exc
    if any(isinstance(node, ast.ImportFrom) and node.level and node.module in {"fastapi", "pydantic"}
           for node in ast.walk(tree)):
        raise UnsupportedContract("relative framework/model imports are unsupported")
    # Module control flow can change name resolution before a model/decorator
    # executes. Do not interpret its bindings as the imported primitive types.
    if any(isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
                             getattr(ast, "TryStar", ast.Try), ast.With, ast.AsyncWith, ast.Match)) for node in tree.body):
        raise UnsupportedContract("conditional module declarations are unsupported")
    imports = {(node.module, alias.name) for node in tree.body if isinstance(node, ast.ImportFrom) and not node.level
               for alias in node.names if alias.asname is None}
    if any(isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names) for node in ast.walk(tree)):
        raise UnsupportedContract("wildcard imports are unsupported")
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    bindings = Counter()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings[node.name] += 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]] += 1
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store):
                        bindings[name.id] += 1
    if any(bindings[name] > 1 for name in set(classes) | {"BaseModel", "FastAPI", "APIRouter"}) or any(bindings[name] for name in set(TYPES) | {"list", "dict", "tuple", "set"}):
        raise UnsupportedContract("shadowed model, framework, or primitive names are unsupported")
    routing = StaticRouters(tree, imports)
    receivers = set(routing.receivers)
    if any(bindings[name] != 1 for name in receivers):
        raise UnsupportedContract("reassigned app/router is unsupported")
    protected = receivers | set(classes)
    allowed_receivers = {id(target) for node in tree.body if isinstance(node, ast.Assign)
                         for target in node.targets if isinstance(target, ast.Name) and target.id in receivers}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in protected and isinstance(node.ctx, (ast.Store, ast.Del)) and id(node) not in allowed_receivers:
            raise UnsupportedContract("non-declaration binding or deletion of a model/app is unsupported")
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            for target in targets:
                if isinstance(target, (ast.Attribute, ast.Subscript)):
                    root = target
                    while isinstance(root, (ast.Attribute, ast.Subscript)):
                        root = root.value
                    if isinstance(root, ast.Name) and root.id in protected:
                        raise UnsupportedContract("app/router/model attribute mutation is unsupported")
            value = getattr(node, "value", None)
            if isinstance(value, ast.Name) and value.id in protected:
                raise UnsupportedContract("app/router/model aliases are unsupported")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"setattr", "delattr", "exec", "eval"}:
            raise UnsupportedContract("reflective mutation is unsupported")
        if isinstance(node, ast.Call):
            direct_route = (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                            and node.func.value.id in receivers and node.func.attr in METHODS | {"include_router"})
            root = node.func
            while isinstance(root, (ast.Attribute, ast.Subscript)):
                root = root.value
            if isinstance(node.func, ast.Attribute) and isinstance(root, ast.Name) and root.id in protected and not direct_route:
                raise UnsupportedContract("opaque app/router/model method calls are unsupported")
            if not direct_route and any(isinstance(arg, ast.Name) and arg.id in protected
                                        for arg in [*node.args, *(kw.value for kw in node.keywords)]):
                raise UnsupportedContract("app/router/model escapes to an opaque call")
    responses = {name: {} for name in receivers}
    route_decorators = []
    for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute) or decorator.func.attr not in METHODS:
                raise UnsupportedContract("unresolved function decorators are unsupported")
            if function not in tree.body or not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id not in receivers:
                raise UnsupportedContract("only top-level routes on directly declared apps/routers are supported")
            if len(function.decorator_list) != 1:
                raise UnsupportedContract("additional handler decorators are unsupported")
            if len(decorator.args) != 1 or not isinstance(decorator.args[0], ast.Constant) or not isinstance(decorator.args[0].value, str) or not decorator.args[0].value.startswith("/"):
                raise UnsupportedContract("route path must be a literal absolute path")
            if re.search(r"\{[^}]*:", decorator.args[0].value):
                raise UnsupportedContract("path converters are outside the static routing subset")
            if routes_only:
                if any(kw.arg != 'response_model' for kw in decorator.keywords):
                    raise UnsupportedContract('route options outside the routing subset')
                key = (decorator.func.attr.upper(), decorator.args[0].value)
                receiver = decorator.func.value.id
                if key in responses[receiver] or routing.receivers[receiver].line >= function.lineno:
                    raise UnsupportedContract('duplicate or forward-declared route')
                responses[receiver][key] = {}
                route_decorators.append(decorator)
                continue
            if len(decorator.keywords) != 1 or decorator.keywords[0].arg != "response_model" or not isinstance(decorator.keywords[0].value, ast.Name):
                raise UnsupportedContract("route must declare only a same-file response_model")
            model = classes.get(decorator.keywords[0].value.id)
            if model is None or ("pydantic", "BaseModel") not in imports:
                raise UnsupportedContract("external or aliased response model is unsupported")
            key = (decorator.func.attr.upper(), decorator.args[0].value)
            receiver = decorator.func.value.id
            if model.lineno >= function.lineno or routing.receivers[receiver].line >= function.lineno:
                raise UnsupportedContract("model/receiver must be declared before its route")
            if key in responses[receiver]:
                raise UnsupportedContract("duplicate method/path identity")
            try:
                fields = _primitive_fields(model)
            except UnsupportedContract as exc:
                if not _isolated_shape(model):
                    raise
                fields = UnknownResponse(str(exc))
            responses[receiver][key] = fields
            route_decorators.append(decorator)
    if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
           and isinstance(node.func.value, ast.Name) and node.func.value.id in receivers
           and node.func.attr in METHODS and node not in route_decorators for node in ast.walk(tree)):
        raise UnsupportedContract("route registration outside a supported decorator is unsupported")
    return routing.expand(responses)


def extract_responses(source):
    """Strict compatibility API: incomplete response shapes remain unsupported."""
    responses = _extract_contracts(source)
    for fields in responses.values():
        if isinstance(fields, UnknownResponse):
            raise UnsupportedContract(fields.reason)
    return responses


def extract_routes(source):
    """Complete registered route identities in the same bounded router scope."""
    return set(_extract_contracts(source, routes_only=True))


def response_changes(files, session=None):
    session = session or AnalysisSession()
    before, after = {}, {}
    for file in files:
        if not file.path.endswith(".py"):
            raise UnsupportedContract("api-schema triggers must be Python modules")
        old_text = "" if file.status == "added" else file.before_source
        new_text = "" if file.status == "deleted" else file.after_source
        old = session.resolve("python-response-v2", old_text, lambda: _extract_contracts(old_text))
        new = session.resolve("python-response-v2", new_text, lambda: _extract_contracts(new_text))
        if before.keys() & old.keys() or after.keys() & new.keys():
            raise UnsupportedContract("duplicate route identity across modules")
        before.update(old)
        after.update(new)
    changes = {}
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if key not in after:
            changes[key] = None  # Identity is known even if the removed shape was opaque.
        elif isinstance(old, UnknownResponse) or isinstance(new, UnknownResponse):
            changes[key] = new if isinstance(new, UnknownResponse) else old
        elif old != new:
            changes[key] = new
    return changes


def response_delta(files, session=None):
    changes = response_changes(files, session)
    for shape in changes.values():
        if isinstance(shape, UnknownResponse):
            raise UnsupportedContract(shape.reason)
    return changes


def _object_schema(document, schema):
    if not isinstance(schema, dict):
        raise UnsupportedContract("OpenAPI response schema is missing")
    if "$ref" in schema:
        ref = schema["$ref"]
        prefix = "#/components/schemas/"
        if not isinstance(ref, str) or not ref.startswith(prefix) or "/" in ref[len(prefix):] or set(schema) != {"$ref"}:
            raise UnsupportedContract("only direct local component references are supported")
        schema = document.get("components", {}).get("schemas", {}).get(ref[len(prefix):])
    if not isinstance(schema, dict) or schema.get("type") != "object" or set(schema) - {"type", "properties", "required", "title", "description"}:
        raise UnsupportedContract("OpenAPI must describe a plain response object")
    properties, required = schema.get("properties", {}), schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list) or any(not isinstance(name, str) for name in required) or not set(required) <= properties.keys():
        raise UnsupportedContract("invalid OpenAPI object fields")
    fields = {}
    for name, spec in properties.items():
        if not isinstance(spec, dict) or spec.get("type") not in TYPES.values() or set(spec) - {"type", "default", "title", "description"}:
            raise UnsupportedContract("OpenAPI field is outside the primitive subset")
        field = {"type": spec["type"], "required": name in required}
        if "default" in spec:
            value = spec["default"]
            allowed = {"string": {str}, "integer": {int}, "number": {int, float}, "boolean": {bool}}[spec["type"]]
            if type(value) not in allowed or (isinstance(value, float) and not math.isfinite(value)):
                raise UnsupportedContract("OpenAPI field default does not match its primitive type")
            field["default"] = spec["default"]
        fields[name] = field
    return fields


def _operation_matches(document, method, path, expected):
    item = document["paths"].get(path, {})
    if not isinstance(item, dict) or "$ref" in item:
        raise UnsupportedContract("invalid or referenced OpenAPI path item")
    # An absent operation and a present but invalid null operation differ.
    if method.lower() not in item:
        return expected is None
    operation = item[method.lower()]
    if not isinstance(operation, dict) or "$ref" in operation:
        raise UnsupportedContract("invalid or referenced OpenAPI operation")
    if expected is None:
        return False
    return _object_schema(document, operation.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema")) == expected


def _document_check(text, delta, session=None):
    try:
        document = load_openapi(text, session)
        checks = []
        for (method, path), expected in sorted(delta.items()):
            label = f"{method} {path}"
            if isinstance(expected, UnknownResponse):
                checks.append(unknown(f"{label}: source response shape: {expected.reason}", "api-schema"))
                continue
            try:
                matches = _operation_matches(document, method, path, expected)
                checks.append(checked(matches, f"{label}: response schema {'matches' if matches else 'differs'}", "api-schema"))
            except (UnsupportedContract, AttributeError, TypeError) as exc:
                checks.append(unknown(f"{label}: {exc}", "api-schema"))
        return combine(checks, require_all=True, mode="api-schema")
    except (AttributeError, TypeError, RecursionError) as exc:
        raise UnsupportedContract("invalid or unsupported OpenAPI JSON") from exc


def api_schema_requirement(group, triggers, files, session=None):
    mode = "api-schema"
    try:
        delta = response_changes(triggers, session)
    except UnsupportedContract as exc:
        return unknown(str(exc), mode)
    if not delta:
        return ContentCheck("satisfied", "not-applicable", "No response contract delta in the supported static subset", mode)
    patterns = group.any_changed or group.all_changed
    candidates = [file for file in files if file.status != "deleted" and matches_any(file.path, patterns)]
    results = []
    for pattern in patterns:
        checks = []
        for file in candidates:
            if not matches_any(file.path, [pattern]):
                continue
            try:
                if file.document_input_state == "missing":
                    checks.append(combine([unknown(shape.reason, mode) if isinstance(shape, UnknownResponse)
                        else checked(False, "OpenAPI document is missing", mode) for shape in delta.values()], require_all=True, mode=mode))
                else:
                    if file.document_error:
                        raise UnsupportedContract(file.document_error)
                    if file.path.lower().endswith(('.yml', '.yaml')) and file.document_json is None:
                        raise UnsupportedContract('OpenAPI YAML requires safe adapter decoding')
                    checks.append(_document_check(file.document_json if file.document_json is not None else file.after_source, delta, session))
            except UnsupportedContract as exc:
                checks.append(unknown(str(exc), mode))
        if not checks:
            checks.append(combine([unknown(shape.reason, mode) if isinstance(shape, UnknownResponse)
                else checked(False, "OpenAPI document is missing", mode) for shape in delta.values()], require_all=True, mode=mode))
        # One complete document per alternative; fragments are never combined.
        results.append(combine(checks, require_all=False, mode=mode))
    outcome = combine(results, require_all=bool(group.all_changed), mode=mode)
    labels = ", ".join(f"{method} {path}" for method, path in sorted(delta))
    return ContentCheck(outcome.decision, outcome.verification, f"{outcome.reason}; changed response contracts: {labels}", mode)
