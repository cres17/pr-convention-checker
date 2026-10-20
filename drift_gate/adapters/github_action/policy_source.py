"""Select the policy an Action run is judged by.

A pull request can edit ``.drift-gate.yml`` in the same change it is judged by. Reading the policy from the
checked-out workspace therefore lets the change under review remove or weaken the rule that applies to it.
``base`` (default) judges the PR with the policy at the PR's base commit. A policy that the PR itself changes
is reported, with the weakening reasons the immutable-check path uses (``core/policy/guard.py``).
"""
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from drift_gate.adapters.policy_loader import read_policy, require_check_policy
from drift_gate.core.policy.guard import weakening_reasons
from drift_gate.core.policy.loader import PolicyLoadError, load_policy_from_text

MODES = ('base', 'workspace')


@dataclass
class SelectedPolicy:
    source: str
    policy: object
    origin: str  # base | workspace | workspace-no-base-policy
    notes: list = field(default_factory=list)
    weakening: list = field(default_factory=list)


def select_policy(gh, policy_path, workspace, mode, base_oid):
    """Return the policy to evaluate with. ``policy_path`` may be relative to the workspace."""
    if mode not in MODES:
        raise ValueError(f'POLICY_SOURCE must be one of {MODES}, got {mode!r}')
    path = Path(policy_path)
    if not path.is_absolute():
        path = Path(workspace) / path
    exists = path.exists()
    workspace_source, workspace_policy = read_policy(path) if (exists or mode == 'workspace') else (None, None)
    if mode == 'workspace':
        return SelectedPolicy(workspace_source, workspace_policy, 'workspace',
                              ['policy_source=workspace: the policy in the pull request checkout is used; '
                               'the pull request can change the rules it is judged by'])
    try:
        relative = PurePosixPath(path.resolve().relative_to(Path(workspace).resolve()).as_posix())
    except ValueError as exc:
        raise ValueError('policy_file must be inside the workspace when policy_source is base') from exc
    if not base_oid:
        raise RuntimeError('base commit of the pull request is unknown; cannot read the base policy')
    base_source = gh.get_file_text(str(relative), base_oid)
    if base_source is None:
        return SelectedPolicy(workspace_source, workspace_policy, 'workspace-no-base-policy',
                              [f'{relative} does not exist at the base commit; the pull request policy is used, '
                               'so this run cannot protect against a policy written in the same change'])
    base_policy = load_policy_from_text(base_source)
    require_check_policy(base_policy)
    # A checkout with CRLF conversion (Windows runners) must not look like an edit of the policy.
    changed = workspace_source is None or _lf(workspace_source) != _lf(base_source)
    if workspace_source is None:
        reasons = ['policy file removed by this pull request']
    else:
        reasons = weakening_reasons(base_policy, workspace_policy) if changed else []
    notes = []
    if changed:
        notes.append(f'{relative} is changed by this pull request; it is judged by the base policy')
    if reasons:
        notes.append('the changed policy would weaken the base policy: ' + '; '.join(reasons))
    return SelectedPolicy(base_source, base_policy, 'base', notes, reasons)


def _lf(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


__all__ = ['MODES', 'PolicyLoadError', 'SelectedPolicy', 'select_policy']
