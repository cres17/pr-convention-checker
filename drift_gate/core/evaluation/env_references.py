"""Classify where a removed environment key still occurs (pure; adapters supply the text).

``code``     a supported language reads the key (Python ``os`` access, JS ``process.env``/``import.meta.env``)
``config``   a configuration or deployment file uses the key in an environment-variable form
``mention``  the name occurs, but not in a recognised use (comments, other languages, prose)

Only ``code`` proves the key is still used. ``config`` and ``mention`` are reported as
warnings: a matching form may still belong to another service, and a bare name proves nothing.
"""
from pathlib import PurePosixPath
import re

from drift_gate.core.evaluation.environment import environment_facts

KINDS = ('code', 'config', 'mention')
JS_SUFFIXES = ('.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs')


def _uncommented(text):
    return '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))


def _shell_forms(key):
    k = re.escape(key)
    return [rf'^\s*export\s+{k}\b', rf'^\s*{k}=', rf'\$\{{{k}(?:[:?+-][^}}]*)?\}}', rf'\${k}\b']


def _config_forms(path, key):
    """Environment-variable forms per file kind; ``None`` when the file kind has none."""
    k = re.escape(key)
    name = PurePosixPath(path).name.lower()
    posix = path.replace('\\', '/').lower()
    if name.startswith('.env'):
        return [rf'^\s*(?:export\s+)?{k}\s*=']
    if name.startswith('dockerfile') or name.endswith('.dockerfile'):
        return [rf'^\s*(?:ENV|ARG)\s+{k}\b', rf'\$\{{?{k}\b']
    if name.endswith(('.sh', '.bash', '.zsh')):
        return _shell_forms(key)
    if name.endswith(('.yml', '.yaml')):
        if posix.startswith('.github/workflows/') or '/.github/workflows/' in posix:
            return [rf'\$\{{\{{\s*(?:secrets|env|vars)\.{k}\s*\}}\}}', rf'^\s*{k}\s*:']
        if 'compose' in name:
            return [rf'^\s*-?\s*["\']?{k}["\']?\s*[:=]', rf'\$\{{{k}(?:[:?+-][^}}]*)?\}}', rf'\${k}\b']
        # Kubernetes / Helm env lists and secret references.
        return [rf'^\s*-?\s*name:\s*["\']?{k}["\']?\s*$', rf'^\s*key:\s*["\']?{k}["\']?\s*$']
    return None


def classify_reference(path, text, key):
    """Return ``code``, ``config`` or ``mention`` for one file containing ``key`` (``None`` if absent)."""
    if text is None or not re.search(rf'(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])', text):
        return None
    if path.endswith('.py'):
        return 'code' if key in environment_facts(text).keys else 'mention'
    if path.endswith(JS_SUFFIXES):
        from drift_gate.core.evaluation.contracts import env_keys_in_code
        if key in env_keys_in_code(text.splitlines(), path) or re.search(
                rf'\bimport\.meta\.env\.{re.escape(key)}\b', text):
            return 'code'
        return 'mention'
    forms = _config_forms(path, key)
    if forms and any(re.search(form, _uncommented(text), re.M) for form in forms):
        return 'config'
    return 'mention'


def reference_outcome(references):
    """Strongest observed use for one key: code > config > mention > absent."""
    references = references or {}
    for kind in KINDS:
        if references.get(kind):
            return kind
    return 'absent'
