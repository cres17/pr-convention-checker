"""Bounded, captured repository search for removed environment key names."""
import re
import subprocess
import tempfile
from dataclasses import replace
from pathlib import PurePosixPath

import yaml

from drift_gate.adapters.docs.content import local_document_reader
from drift_gate.core.change_paths import triggers
from drift_gate.core.evaluation.environment import environment_facts
from drift_gate.core.evaluation.removed_environment import (
    js_environment_keys,
    removed_environment_keys,
)
from drift_gate.utils.glob_matcher import matches_any

MAX_FILES = 2000
MAX_BYTES = 8_000_000


def candidate_keys(files, policy):
    if not policy.check_removed_keys:
        return set()
    keys = set()
    for rule in policy.rules:
        if any(g.content == 'env-keys' for g in rule.require.groups):
            keys.update(removed_environment_keys([f for f in files if triggers(f, rule.when.any_changed)]))
    return keys - set(policy.exclude_removed_keys)



def _document(path, policy):
    patterns = [p for r in policy.rules for g in r.require.groups if g.content == 'env-keys'
                for p in (g.any_changed or g.all_changed)]
    return path.startswith(('docs/', 'doc/')) or path.lower().endswith(('.md', '.rst')) or matches_any(path, patterns)


def _yaml_usage(value, key, *, compose=False, workflow=False, parent=''):
    if isinstance(value, dict):
        for name, child in value.items():
            if name == 'environment' and compose:
                if isinstance(child, dict) and key in child:
                    return True
                if isinstance(child, list) and any(isinstance(s, str) and re.match(rf'^{re.escape(key)}(?:=|$)', s) for s in child):
                    return True
            if name == 'env':
                if workflow and isinstance(child, dict) and key in child:
                    return True
                if isinstance(child, list) and any(isinstance(row, dict) and row.get('name') == key for row in child):
                    return True
            if name == 'secretKeyRef' and isinstance(child, dict) and child.get('key') == key:
                return True
            if _yaml_usage(child, key, compose=compose, workflow=workflow, parent=str(name)):
                return True
    elif isinstance(value, list):
        return any(_yaml_usage(v, key, compose=compose, workflow=workflow, parent=parent) for v in value)
    elif isinstance(value, str):
        if compose and re.search(r'(?<!\$)\$\{' + re.escape(key) + r'(?::?[-+?][^}]*)?\}', value):
            return True
        if workflow and re.search(r'\$\{\{\s*(?:secrets|env)\.' + re.escape(key) + r'\s*\}\}', value):
            return True
    return False


def config_uses(path, source, key):
    name = PurePosixPath(path).name
    escaped = re.escape(key)
    # Comment-only occurrences are mentions, never configuration witnesses.
    text = '\n'.join(line for line in source.splitlines() if not line.lstrip().startswith('#'))
    if name.startswith('Dockerfile') or path.endswith(('.sh', '.bash', '.zsh')):
        if re.search(r'(?<![\\$])\$(?:' + escaped + r'(?![\w])|\{' + escaped + r'(?::?[-+?][^}]*)?\})', text):
            return True
        if name.startswith('Dockerfile'):
            return bool(re.search(r'^\s*(?:ENV|ARG)\s+' + escaped + r'(?=\s|=|$)', text, re.M))
        return bool(re.search(r'(?:^|[;\s])(?:export\s+)?' + escaped + r'=', text, re.M)
                    or re.search(r'^\s*export\s+' + escaped + r'(?=\s|$)', text, re.M))
    if not path.endswith(('.yml', '.yaml')):
        return False
    # Helm templates may not be YAML-decodable. A bounded indentation witness
    # covers env/name and secretKeyRef/key, never an arbitrary name/key field.
    try:
        if len(source) > 1_000_000 or re.search(r'(^|[ :\[,])[*&][\w]', source, re.M):
            return False
        depth = 0
        for index, event in enumerate(yaml.parse(source)):
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            if depth > 40 or index > 20000 or isinstance(event, yaml.AliasEvent):
                return False
        value = yaml.safe_load(source)
    except (yaml.YAMLError, RecursionError, ValueError):
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if re.match(r'^\s*(?:-\s*)?(?:env|secretKeyRef):\s*$', line):
                indent = len(line) - len(line.lstrip())
                for child in lines[i+1:]:
                    if child.strip() and len(child) - len(child.lstrip()) <= indent and not child.lstrip().startswith('-'):
                        break
                    field = 'name' if 'env:' in line else 'key'
                    if re.fullmatch(r'\s*(?:-\s*)?' + field + r':\s*[\'\"]?' + escaped + r'[\'\"]?\s*(?:#.*)?', child):
                        return True
        return False
    return _yaml_usage(value, key, compose=name.startswith(('docker-compose', 'compose.')),
                       workflow=path.startswith('.github/workflows/'))


def collect_usage(keys, policy, paths, read_text, *, complete=True, max_files=MAX_FILES, max_bytes=MAX_BYTES):
    evidence = {key: {'state': 'absent', 'paths': []} for key in sorted(keys)}
    ranks = {'absent': 0, 'incomplete': 1, 'mention': 2, 'config': 3, 'code': 4}
    total = 0
    for index, path in enumerate(sorted(paths)):
        if _document(path, policy):
            continue
        if index >= max_files:
            complete = False
            break
        try:
            source = read_text(path)
            if source is None:
                continue
            total += len(source.encode('utf-8'))
            if total > max_bytes:
                complete = False
                break
        except (OSError, ValueError, RuntimeError, UnicodeError):
            complete = False
            continue
        found = {key for key in keys if re.search(r'(?<![\w])' + re.escape(key) + r'(?![\w])', source)}
        if not found:
            continue
        code = set()
        if path.endswith('.py'):
            facts = environment_facts(source)
            if not facts.uncertain:
                code = facts.keys
        elif path.endswith(('.js', '.jsx', '.ts', '.tsx')):
            code = javascript_code_uses(path, source) or set()
        for key in sorted(found):
            state = 'code' if key in code else 'config' if config_uses(path, source, key) else 'mention'
            row = evidence[key]
            if ranks[state] > ranks[row['state']]:
                row['state'], row['paths'] = state, [path]
            elif state == row['state'] and len(row['paths']) < 20:
                row['paths'].append(path)
    if not complete:
        for row in evidence.values():
            if row['state'] == 'absent':
                row['state'] = 'incomplete'
    return evidence


def attach_local_usage(files, policy, root):
    if not policy.check_removed_keys or not any(g.content == 'env-keys' for r in policy.rules for g in r.require.groups):
        return files
    files = attach_javascript_removals(files)
    keys = candidate_keys(files, policy)
    if not keys:
        return files
    try:
        # Output is spooled and bounded before decoding. Values/source never
        # enter this output, reports or history. No shell or external diff tools.
        from drift_gate.adapters.git.client import _git, _working_state
        before = (_working_state(root), _git(['diff', '--no-ext-diff', '--no-textconv', 'HEAD', '--'], root))
        with tempfile.TemporaryFile() as output:
            args = ['git', '-c', 'grep.threads=1', 'grep', '--no-textconv', '-I', '-l', '-z', '-w']
            for key in sorted(keys):
                args += ['-e', key]
            result = subprocess.run([*args, '--'], cwd=root, stdout=output, stderr=subprocess.DEVNULL, timeout=30)
            if result.returncode not in (0, 1) or output.tell() > 1_000_000:
                raise ValueError('repository search unavailable')
            output.seek(0)
            paths = output.read().decode('utf-8').strip('\0').split('\0') if result.returncode == 0 else []
        untracked = before[0][2].decode('utf-8').strip('\0')
        if untracked:
            paths = sorted(set(paths) | set(untracked.split('\0')))
        usage = collect_usage(keys, policy, paths, local_document_reader(root))
        after = (_working_state(root), _git(['diff', '--no-ext-diff', '--no-textconv', 'HEAD', '--'], root))
        if before != after:
            raise ValueError('repository changed during usage search')
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, UnicodeError):
        usage = {key: {'state': 'incomplete', 'paths': []} for key in sorted(keys)}
    return [replace(f, env_key_usage=usage) for f in files]


def attach_immutable_usage(files, policy, reader, revision):
    if not policy.check_removed_keys or not any(g.content == 'env-keys' for r in policy.rules for g in r.require.groups):
        return files
    files = attach_javascript_removals(files)
    keys = candidate_keys(files, policy)
    if not keys:
        return files
    usage = collect_usage(keys, policy, reader.catalog(revision), lambda p: reader.text(revision, p))
    return [replace(f, env_key_usage=usage) for f in files]


def javascript_code_uses(path, source):
    """Require an AST witness before a JavaScript mention can clear a warning."""
    from drift_gate.adapters.grammar_resources import get_parser
    language = 'tsx' if path.endswith('.tsx') else 'typescript' if path.endswith('.ts') else 'javascript'
    try:
        tree = get_parser(language).parse(source.encode('utf-8')).root_node
        if tree.has_error:
            return None
        candidates = js_environment_keys(source)
        keys, pending, count = set(), [tree], 0
        while pending:
            node = pending.pop()
            count += 1
            if count > 20000:
                return None
            if node.text == b'process' and node.type in {'identifier', 'shorthand_property_identifier_pattern'}:
                parent = node.parent
                if (parent is None or parent.type != 'member_expression'
                    or parent.child_by_field_name('object') != node):
                    return set()  # a shadowed, rebound or escaped process is not a certified reader
            if node.type in {'member_expression', 'subscript_expression'}:
                obj = node.child_by_field_name('object')
                prop = node.child_by_field_name('property') or node.child_by_field_name('index')
                if obj is not None and prop is not None and obj.type == 'member_expression':
                    receiver = obj.child_by_field_name('object')
                    field = obj.child_by_field_name('property')
                    if (receiver is not None and field is not None and receiver.type == 'identifier'
                        and receiver.text == b'process' and field.text == b'env'):
                        raw = prop.text.decode('utf-8')
                        key = raw[1:-1] if prop.type == 'string' else raw
                        parent = node.parent
                        written = (parent is not None and parent.type == 'assignment_expression'
                                   and parent.child_by_field_name('left') == node)
                        deleted = parent is not None and parent.type == 'unary_expression' and parent.text.startswith(b'delete ')
                        if key in candidates and not written and not deleted:
                            keys.add(key)
            pending.extend(node.named_children)
        return keys
    except Exception:  # unavailable grammars cannot certify a source delta
        return None


def attach_javascript_removals(files):
    output = []
    for file in files:
        if (file.path.endswith(('.js', '.jsx', '.ts', '.tsx'))
            and (file.status == 'added' or file.before_source is not None)
            and (file.status == 'deleted' or file.after_source is not None)):
            before = javascript_code_uses(file.path, '' if file.status == 'added' else file.before_source)
            after = javascript_code_uses(file.path, '' if file.status == 'deleted' else file.after_source)
            if before is not None and after is not None:
                file = replace(file, removed_env_key_candidates=sorted(before - after))
        output.append(file)
    return output
