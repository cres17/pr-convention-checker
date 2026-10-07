"""Shared bounded OpenAPI JSON decoding; YAML is normalized by adapters."""
import json
import math
import re

from drift_gate.core.evaluation.static_routers import UnsupportedContract
from drift_gate.core.evaluation.analysis_session import AnalysisSession


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise UnsupportedContract('duplicate OpenAPI JSON keys')
        result[key] = value
    return result


def _unsupported_number(value):
    raise UnsupportedContract('unsupported_numeric_range: OpenAPI values must be finite')


def load_openapi(text, session=None):
    if text is None:
        raise UnsupportedContract('complete OpenAPI document is unavailable')
    if len(text.encode('utf-8')) > 1_000_000:
        raise UnsupportedContract('OpenAPI document exceeds 1 MB')
    def parse():
        try:
            decoded = json.loads(text, object_pairs_hook=_unique_object,
                                 parse_constant=_unsupported_number)
            stack = [(decoded, 0)]
            nodes = 0
            while stack:
                value, depth = stack.pop()
                nodes += 1
                if nodes > 20_000 or depth > 20:
                    raise UnsupportedContract('OpenAPI nesting/node limit exceeded')
                if isinstance(value, float) and not math.isfinite(value):
                    _unsupported_number(value)
                if isinstance(value, dict):
                    stack.extend((child, depth + 1) for child in value.values())
                elif isinstance(value, list):
                    stack.extend((child, depth + 1) for child in value)
            if (not isinstance(decoded, dict) or not isinstance(decoded.get('openapi'), str)
                or not re.fullmatch(r'3\.[01]\.\d+', decoded['openapi']) or not isinstance(decoded.get('paths'), dict)):
                raise UnsupportedContract('expected OpenAPI 3.0/3.1 with paths')
            return decoded
        except UnsupportedContract:
            raise
        except (ValueError, TypeError, RecursionError) as exc:
            raise UnsupportedContract('invalid OpenAPI JSON') from exc
    return (session or AnalysisSession()).resolve('openapi-document-v3', text, parse)
