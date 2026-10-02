"""Focused regression and negative-control tests for literal API contract checks."""
import pytest

from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.core.classification.intensity import classify_file_intensity
from drift_gate.core.engine import run
from drift_gate.core.evaluation.contracts import _routes, route_delta
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Policy


def code(patch, path="src/routes/users.py"):
    return ChangedFile(path=path, status="modified", patch=patch)


POLICY = Policy.from_dict({"rules": [{
    "id": "api-doc",
    "when": {"any_changed": ["src/routes/**"], "min_change_intensity": "route-contract-change"},
    "require": {"groups": [{"name": "API docs", "any_changed": ["docs/api/**"],
                            "content": "api-routes"}]},
    "severity": "blocker",
}]})


@pytest.mark.parametrize("patch,path", [
    ('+message = "@app.get(\'/sample\')"\n', "src/routes/users.py"),
    ('+const example = "app.post(\'/sample\')";\n', "src/routes/users.js"),
    ('+# @app.get(\'/sample\')\n', "src/routes/users.py"),
])
def test_route_examples_do_not_trigger_a_contract(patch, path):
    source = enrich_semantic_signals([code(patch, path)])[0]
    assert classify_file_intensity(source) != "route-contract-change"
    assert route_delta([source]) == (set(), set())
    assert run([source], policy=POLICY).result == "pass"


@pytest.mark.parametrize("method", ["head", "options"])
@pytest.mark.parametrize("syntax,path", [
    ("@app.{method}('/health')", "src/routes/users.py"),
    ("router.{method}('/health', handler)", "src/routes/users.js"),
])
def test_head_and_options_are_classified_and_require_matching_docs(method, syntax, path):
    source = enrich_semantic_signals([code("+" + syntax.format(method=method) + "\n", path)])[0]
    pair = (method.upper(), "/health")
    assert classify_file_intensity(source) == "route-contract-change"
    assert route_delta([source]) == ({pair}, set())
    assert run([source], policy=POLICY).result == "fail"
    documented = ChangedFile(path="docs/api/routes.md", status="modified",
                             patch=f"+{method.upper()} /health\n")
    assert run([source, documented], policy=POLICY).result == "pass"


@pytest.mark.parametrize("method", ["head", "options"])
def test_removed_method_also_requires_a_documented_removal(method):
    source = code(f"-@app.{method}('/health')\n")
    assert classify_file_intensity(source) == "route-contract-change"
    assert route_delta([source]) == (set(), {(method.upper(), "/health")})
    assert run([source], policy=POLICY).result == "fail"
    documented = ChangedFile(path="docs/api/routes.md", status="modified",
                             patch=f"-| {method.upper()} | /health |\n")
    assert run([source, documented], policy=POLICY).result == "pass"


def test_markdown_table_covers_exact_route_replacement():
    source = code("-@app.get('/users')\n+@app.get('/members')\n")
    documented = ChangedFile(path="docs/api/routes.md", status="modified",
                             patch="-GET /users\n+| Method | Path |\n+|---|---|\n+| GET | /members |\n")
    assert _routes(["| Method | Path |", "|---|---|", "| GET | /members |"], docs=True) == {
        ("GET", "/members")}
    assert run(enrich_semantic_signals([source, documented]), policy=POLICY).result == "pass"
    documented.patch = "-GET /users\n+| POST | /members |\n"
    assert run(enrich_semantic_signals([source, documented]), policy=POLICY).result == "fail"
    documented.patch = "+| GET | /members |\n"
    assert run(enrich_semantic_signals([source, documented]), policy=POLICY).result == "fail"


def test_unrelated_table_cells_do_not_form_a_route():
    assert _routes(["| GET | description | /members |", "| POST | /other |"], docs=True) == {
        ("POST", "/other")}


def test_existing_indented_route_and_plain_doc_format_still_work():
    source = code("+    @api.get('/health')\n")
    assert route_delta([source]) == ({("GET", "/health")}, set())
    assert classify_file_intensity(source) == "route-contract-change"
    assert _routes(["GET /health"], docs=True) == {("GET", "/health")}
