"""JSON value semantics, independent of Python representation.

Decimal tokens are preserved before binary floating point can round them.
Canonical numbers use coefficient/exponent notation without context rounding
or expansion of large exponents. Booleans are not JSON numbers.
"""
import json
import math
from decimal import Decimal
from typing import NoReturn, TypeAlias, cast

Number: TypeAlias = int | float | Decimal
JSONValue: TypeAlias = None | bool | Number | str | list['JSONValue'] | dict[str, 'JSONValue']


def _reject_constant(token: str) -> NoReturn:
    raise ValueError(f'non-finite JSON number: {token}')


def _object(pairs: list[tuple[str, JSONValue]]) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def decode(text: str) -> JSONValue:
    return cast(JSONValue, json.loads(text, parse_float=Decimal, parse_constant=_reject_constant, object_pairs_hook=_object))


def _number(value: Number) -> str:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('non-finite JSON number')
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    if not number.is_finite():
        raise ValueError('non-finite JSON number')
    sign, digits, exponent = number.as_tuple()
    assert isinstance(exponent, int)  # finite Decimal exponents are integral
    if not any(digits):
        return '0'
    coefficient = ''.join(map(str, digits)).rstrip('0')
    exponent += len(digits) - len(coefficient)
    return ('-' if sign else '') + coefficient + (f'e{exponent}' if exponent else '')


def canonical(value: JSONValue) -> str:
    """A valid JSON spelling; equal JSON values have equal spellings."""
    if value is None:
        return 'null'
    if type(value) is bool:
        return 'true' if value else 'false'
    if isinstance(value, (int, float, Decimal)):
        return _number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, list):
        return '[' + ','.join(canonical(item) for item in value) + ']'
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return '{' + ','.join(canonical(key) + ':' + canonical(value[key]) for key in sorted(value)) + '}'
    raise ValueError('value is outside the JSON value domain')


def value_type(value: JSONValue) -> str:
    if value is None:
        return 'null'
    if type(value) is bool:
        return 'boolean'
    if isinstance(value, (int, float, Decimal)):
        spelling = _number(value)  # also rejects non-finite numbers
        exponent = int(spelling.partition('e')[2] or '0')
        return 'integer' if exponent >= 0 else 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, dict):
        return 'object'
    raise ValueError('value is outside the JSON value domain')
