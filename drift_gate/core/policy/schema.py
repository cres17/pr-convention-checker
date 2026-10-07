"""Validate raw policy types before constructing dataclasses (pure)."""

def validate_schema(data):
    def fail(path, message):
        raise ValueError(f'{path}: {message}')

    def mapping(value, fields, path):
        if not isinstance(value, dict):
            fail(path, 'must be a mapping')
        unknown = set(value) - set(fields)
        if unknown:
            fail(path, f'unknown keys: {sorted(map(str, unknown))}')
        for key, check in fields.items():
            if key in value:
                check(value[key], f'{path}.{key}')

    def string(value, path):
        if not isinstance(value, str):
            fail(path, 'must be a string')

    def boolean(value, path):
        if type(value) is not bool:
            fail(path, 'must be a boolean')

    def positive(value, path):
        if type(value) is not int or value < 1:
            fail(path, 'must be a positive integer (not boolean)')

    def array(check):
        def validate(value, path):
            if not isinstance(value, list):
                fail(path, 'must be a list')
            for i, item in enumerate(value):
                check(item, f'{path}[{i}]')
        return validate

    strings = array(string)
    group = lambda v, p: mapping(v, {'name': string, 'any_changed': strings,
        'all_changed': strings, 'required': boolean, 'content': string}, p)
    relation = lambda v, p: mapping(v, {'name': string, 'when_any_changed': strings,
        'require_groups': strings, 'message': string}, p)

    def rule(value, path):
        mapping(value, {'id': string, 'severity': string, 'message': string,
            'allow_ignore': boolean,
            'when': lambda v, p: mapping(v, {'any_changed': strings, 'min_change_intensity': string}, p),
            'require': lambda v, p: mapping(v, {'groups': array(group), 'cross_file': array(relation)}, p)}, path)
        if not value.get('id'):
            fail(path + '.id', 'must be a nonempty string')

    mapping(data, {'rules': array(rule), 'ignore_paths': strings,
        'gate': lambda v, p: mapping(v, {'fail_on_blocker': boolean, 'fail_on_major_count': positive,
            'on_unverified': string}, p),
        'suppression': lambda v, p: mapping(v, {'allow_ignores': boolean,
            'require_codeowners_approval': boolean, 'allowed_rules': strings,
            'repeated_ignore_threshold': positive}, p),
        'enrichment': lambda v, p: mapping(v, {'provider': string, 'mode': string}, p)}, 'policy')
