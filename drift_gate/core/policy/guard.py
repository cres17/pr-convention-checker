"""Compare candidate obligations against a separately selected policy (pure)."""
from drift_gate.core.classification.intensity import INTENSITY_ORDER


def weakening_reasons(trusted, candidate):
    errors = []
    levels = {'nit': 0, 'minor': 1, 'major': 2, 'blocker': 3}
    by_id = {r.id: r for r in candidate.rules}
    for old in trusted.rules:
        new = by_id.get(old.id)
        if new is None:
            errors.append(f'{old.id}: removed trusted rule')
            continue
        if not set(old.when.any_changed).issubset(new.when.any_changed):
            errors.append(f'{old.id}: narrowed trigger')
        if INTENSITY_ORDER[new.when.min_change_intensity] > INTENSITY_ORDER[old.when.min_change_intensity]:
            errors.append(f'{old.id}: raised intensity threshold')
        if levels[new.severity] < levels[old.severity]:
            errors.append(f'{old.id}: lowered severity')
        if (old.severity in ('major', 'minor') and new.severity == 'blocker'
            and not candidate.gate.fail_on_blocker):
            errors.append(f'{old.id}: promoted severity is disabled by the blocker gate')
        groups = {g.name: g for g in new.require.groups}
        conditional_groups = {name for relation in old.require.cross_file
                              for name in relation.require_groups}
        for group in old.require.groups:
            if not group.required and group.name not in conditional_groups:
                continue
            current = groups.get(group.name)
            if (current is None or (group.required and not current.required)
                or current.content != group.content
                or (not group.any_changed and bool(current.any_changed))
                or not set(group.all_changed).issubset(current.all_changed)
                or (group.any_changed and (not current.any_changed or
                    not set(current.any_changed).issubset(group.any_changed)))):
                errors.append(f'{old.id}: weakened group {group.name}')
        if old.require.cross_file != new.require.cross_file:
            errors.append(f'{old.id}: cross-file obligations changed; explicit migration required')
        if not old.allow_ignore and new.allow_ignore:
            errors.append(f'{old.id}: enabled exceptions')
    if trusted.gate.fail_on_blocker and not candidate.gate.fail_on_blocker:
        errors.append('disabled blocker gate')
    if candidate.gate.fail_on_major_count > trusted.gate.fail_on_major_count:
        errors.append('raised failure threshold')
    if trusted.gate.on_unverified == 'fail' and candidate.gate.on_unverified != 'fail':
        errors.append('weakened unverified-content gate')
    if set(candidate.ignore_paths) - set(trusted.ignore_paths):
        errors.append('added excluded paths')
    if trusted.suppression != candidate.suppression:
        errors.append('exception policy changed; explicit migration required')
    return errors
