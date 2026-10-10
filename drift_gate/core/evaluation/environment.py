"""Static environment facts with explicit uncertainty; never execute source."""
import ast
from collections import Counter
from dataclasses import dataclass, field
import re
import textwrap

from drift_gate.core.models.facts import (
    ContractFamily, ExactFacts, FactBasis, ReasonCode, UnknownFacts,
)


@dataclass
class EnvironmentFacts:
    keys: set[str] = field(default_factory=set)
    uncertain: bool = False


def environment_fact_outcome(source, *, scope_id, evidence_ref, fragment=False):
    """Typed observation of the current Python profile, without policy changes.

    Patch heuristics never establish exact facts, even when syntactically valid.
    Their inferred names are not retained as definite facts in this new API.
    """
    basis = FactBasis(scope_id, ContractFamily.ENV_KEY, 'python-env-literals', '1', (evidence_ref,))
    result = environment_facts(source, fragment=fragment)
    if fragment:
        return UnknownFacts(basis, frozenset(), (ReasonCode.PATCH_ONLY,))
    if source is None:
        return UnknownFacts(basis, frozenset(), (ReasonCode.MISSING_SOURCE,))
    if result.uncertain:
        return UnknownFacts(basis, result.keys, (ReasonCode.UNSUPPORTED_BINDING,))
    return ExactFacts(basis, result.keys)


def environment_facts(source, *, fragment=False):
    if source is None:
        return EnvironmentFacts(uncertain=True)
    try:
        tree = ast.parse(textwrap.dedent(source) if fragment else source)
    except (SyntaxError, ValueError, RecursionError):
        return EnvironmentFacts(uncertain=True)
    modules, getters, environs = set(), set(), set()
    bindings = Counter()
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split('.')[0]
                bindings[name] += 1
                if node in tree.body:
                    if isinstance(node, ast.Import) and alias.name == 'os':
                        modules.add(name)
                        imported.add(name)
                    elif isinstance(node, ast.ImportFrom) and node.module == 'os' and not node.level:
                        if alias.name == 'getenv':
                            getters.add(name)
                            imported.add(name)
                        elif alias.name == 'environ':
                            environs.add(name)
                            imported.add(name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bindings[node.id] += 1
        elif isinstance(node, ast.arg):
            bindings[node.arg] += 1
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            bindings[node.name] += 1
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bindings[node.rest] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings[node.name] += 1
    # Legacy patch inputs often omit unchanged imports. Only canonical names
    # may be assumed there; aliases need an import witness in the input.
    if fragment:
        modules.add('os')
        getters.add('getenv')
    protected = modules | getters | environs
    ambiguous = {name for name in protected if bindings[name] != int(name in imported)}
    facts = EnvironmentFacts()
    consumed = set()

    def access(node):
        if isinstance(node, ast.Name):
            return ('getter', node.id) if node.id in getters else ('environ', node.id) if node.id in environs else None
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in modules:
            if node.attr in {'getenv', 'environ'}:
                return ('getter' if node.attr == 'getenv' else 'environ', node.value.id)
        return None

    for node in ast.walk(tree):
        key = witness = None
        if isinstance(node, ast.Call):
            target = access(node.func)
            if target and target[0] == 'getter':
                key = node.args[0] if node.args else None
                witness = target[1]
                consumed.add(id(node.func))
            elif isinstance(node.func, ast.Attribute) and node.func.attr == 'get':
                target = access(node.func.value)
                if target and target[0] == 'environ':
                    key = node.args[0] if node.args else None
                    witness = target[1]
                    consumed.add(id(node.func.value))
        elif isinstance(node, ast.Subscript):
            target = access(node.value)
            if target and target[0] == 'environ' and isinstance(node.ctx, ast.Load):
                key, witness = node.slice, target[1]
                consumed.add(id(node.value))
        if witness:
            if witness in ambiguous or not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                facts.uncertain = True
            elif re.fullmatch(r'[A-Z][A-Z0-9_]*', key.value):
                facts.keys.add(key.value)
            else:
                facts.uncertain = True
    if any(access(node) and isinstance(node, (ast.Name, ast.Attribute))
           and isinstance(node.ctx, ast.Load) and id(node) not in consumed for node in ast.walk(tree)):
        facts.uncertain = True  # getter/environ escaped the supported access form
    if any(isinstance(node, ast.ImportFrom) and node.module == 'os'
           and (node not in tree.body or any(alias.name == '*' for alias in node.names)) for node in ast.walk(tree)):
        facts.uncertain = True
    if any(isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
           and node.value.id == 'os' and node.attr in {'getenv', 'environ'}
           and 'os' not in modules for node in ast.walk(tree)):
        facts.uncertain = True
    # Rebinding through attributes, wildcard imports, reflection and aliases
    # makes otherwise literal getters unsuitable as verified evidence.
    if protected and any(
        isinstance(node, ast.ImportFrom) and any(a.name == '*' for a in node.names)
        or isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'exec', 'eval', 'setattr', 'delattr'}
        or isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del))
           and isinstance(node.value, ast.Name) and node.value.id in protected
        for node in ast.walk(tree)
    ):
        facts.uncertain = True
        facts.keys.clear()
    return facts


def environment_delta(files):
    added, removed = set(), set()
    uncertain = False
    from drift_gate.core.patch_lines import changed_lines
    for file in files:
        if file.path.endswith('.py'):
            complete = ((file.status == 'added' or file.before_source is not None)
                        and (file.status == 'deleted' or file.after_source is not None))
            if complete:
                scope = 'selected-module:' + file.path
                old_observation = environment_fact_outcome('' if file.status == 'added' else file.before_source,
                                                         scope_id=scope, evidence_ref='before:' + (file.previous_path or file.path))
                new_observation = environment_fact_outcome('' if file.status == 'deleted' else file.after_source,
                                                         scope_id=scope, evidence_ref='after:' + file.path)
                # The existing aggregate key algorithm is deliberately preserved.
                old = EnvironmentFacts(set(old_observation.must), not isinstance(old_observation, ExactFacts))
                new = EnvironmentFacts(set(new_observation.must), not isinstance(new_observation, ExactFacts))
            else:
                lines = changed_lines(file)
                old = environment_facts('\n'.join(text for marker, text in lines if marker == '-'), fragment=True)
                new = environment_facts('\n'.join(text for marker, text in lines if marker == '+'), fragment=True)
            # An opaque old getter may already refer to a purported new key.
            # Do not promote that set difference to a known obligation.
            if not old.uncertain:
                added.update(new.keys)
            removed.update(old.keys)
            uncertain |= old.uncertain or new.uncertain
        else:
            # Preserve the existing bounded process.env literal contract.
            # Dynamic JS keys and other languages cannot establish absence.
            from drift_gate.core.evaluation.contracts import env_keys_in_code
            lines = changed_lines(file)
            added.update(env_keys_in_code([text for marker, text in lines if marker == '+'], file.path))
            removed.update(env_keys_in_code([text for marker, text in lines if marker == '-'], file.path))
            uncertain |= not file.path.endswith(('.js', '.jsx', '.ts', '.tsx')) or any(
                'process.env[' in text and not re.search(r"process\.env\[\s*['\"][A-Z][A-Z0-9_]*['\"]\s*\]", text)
                for _, text in lines if not text.lstrip().startswith(('//', '/*', '*')))
    return EnvironmentFacts(added - removed, uncertain)
