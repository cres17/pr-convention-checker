"""Bounded YAML decoding at the I/O boundary; core consumes plain JSON."""
import json

import yaml


def normalize_openapi_yaml(text):
    if len(text.encode('utf-8')) > 1_000_000:
        raise ValueError('OpenAPI YAML exceeds 1 MB')

    class Loader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            keys = set()
            for key_node, _ in node.value:
                key = self.construct_object(key_node, deep=False)
                if key_node.tag == 'tag:yaml.org,2002:merge' or not isinstance(key, str) or key in keys:
                    raise ValueError('OpenAPI YAML has duplicate, merge, or non-string keys')
                keys.add(key)
            return super().construct_mapping(node, deep=deep)

    try:
        depth = 0
        for count, event in enumerate(yaml.parse(text), start=1):
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            if depth > 20 or count > 20_000 or isinstance(event, yaml.AliasEvent):
                raise ValueError('OpenAPI YAML nesting/node/alias limit exceeded')
        decoded = yaml.load(text, Loader=Loader)
        if not isinstance(decoded, dict):
            raise ValueError('OpenAPI YAML root must be a mapping')
        return json.dumps(decoded, sort_keys=True, allow_nan=False)
    except (yaml.YAMLError, TypeError, RecursionError) as exc:
        # Do not include parser snippets: document contents may be sensitive.
        raise ValueError('invalid or unsupported OpenAPI YAML') from exc
