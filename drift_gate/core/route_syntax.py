"""Shared, deliberately bounded recognition of literal HTTP route registrations."""
import re

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
METHOD_PATTERN = "|".join(HTTP_METHODS)

# A registration must start at the beginning of a code line (after indentation).
# This excludes assignments containing examples such as message = "@app.get('/x')".
PYTHON_DECORATOR = re.compile(rf"^\s*@\w+\.({METHOD_PATTERN})\s*\(", re.I)
OBJECT_CALL = re.compile(rf"^\s*\w+\.({METHOD_PATTERN})\s*\(", re.I)
LITERAL_ROUTE = re.compile(
    rf"^\s*@?\w+\.({METHOD_PATTERN})\s*\(\s*(['\"])(/[^'\"\n]*)\2", re.I
)


def route_registration_method(line: str) -> str | None:
    """Return the method of a supported decorator or object call, if any."""
    match = PYTHON_DECORATOR.match(line) or OBJECT_CALL.match(line)
    return match.group(1).upper() if match else None


def literal_route(line: str) -> tuple[str, str] | None:
    """Return a literal method/path pair from a supported registration line."""
    match = LITERAL_ROUTE.match(line)
    return (match.group(1).upper(), match.group(3)) if match else None
