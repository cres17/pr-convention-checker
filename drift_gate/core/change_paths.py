"""Path roles: both endpoints trigger; only extant destinations satisfy."""
from drift_gate.utils.glob_matcher import matches_any


def change_paths(file):
    return tuple(dict.fromkeys(p for p in (file.previous_path, file.path) if p))


def is_ignored(file, patterns):
    return all(matches_any(path, patterns) for path in change_paths(file))


def triggers(file, patterns):
    return file.status != 'unchanged' and any(matches_any(p, patterns) for p in change_paths(file))
