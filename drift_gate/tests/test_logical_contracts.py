"""Logical-contract counterexamples and normal controls, not PR accuracy."""
from copy import deepcopy
import json

import pytest

from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
from drift_gate.adapters.inspection import inspect
from drift_gate.adapters.mcp.tools import _compact_result
from drift_gate.core.engine import run
from drift_gate.core.evaluation.api_schema import extract_responses, UnsupportedContract
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.guard import weakening_reasons
from drift_gate.core.policy.loader import load_policy_from_dict, PolicyLoadError
from drift_gate.reporters.markdown import MarkdownReporter
from drift_gate.reporters.html import HtmlReporter


def raw_policy(mode="api-schema", action="fail", paths=None, all_docs=False):
    return {"rules": [{"id": "response-contract", "severity": "blocker",
        "when": {"any_changed": ["src/**"]}, "require": {"groups": [{"name": "API",
        "all_changed" if all_docs else "any_changed": paths or ["openapi.json"], "content": mode}]}}],
        "gate": {"on_unverified": action}}


def policy(**kwargs):
    return load_policy_from_dict(raw_policy(**kwargs))


def source(fields="id: int\n    label: str", model="Order", path="/orders", method="get"):
    return f"from fastapi import FastAPI\nfrom pydantic import BaseModel\napp = FastAPI()\nclass {model}(BaseModel):\n    {fields}\n@app.{method}('{path}', response_model={model})\ndef orders():\n    return {{}}\n"


def changed(before=None, after=None, status="modified"):
    before = source() if before is None else before
    after = source("id: int") if after is None else after
    return ChangedFile("src/api.py", status, patch="-" + before.replace("\n", "\n-") + "\n+" + after.replace("\n", "\n+"),
                       before_source=before, after_source=after)


def openapi(fields=None, method="get", path="/orders", component=False):
    fields = fields if fields is not None else {"id": {"type": "integer"}}
    schema = {"type": "object", "properties": fields,
              "required": [name for name, spec in fields.items() if "default" not in spec]}
    document = {"openapi": "3.1.0", "paths": {path: {method: {"responses": {"200": {"content": {"application/json": {"schema": schema}}}}}}}}
    if component:
        document["components"] = {"schemas": {"BriefOrder": schema}}
        document["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"] = {"$ref": "#/components/schemas/BriefOrder"}
    return json.dumps(document)


def document(text=None, path="openapi.json", status="modified"):
    return ChangedFile(path, status, patch="+contract updated\n", after_source=openapi() if text is None else text)


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_names_never_depend_on_array_order(reverse):
    raw = raw_policy()
    groups = raw["rules"][0]["require"]["groups"]
    groups[0]["required"] = False
    groups.append({"name": "API", "all_changed": ["src/**"], "required": False})
    if reverse:
        groups.reverse()
    with pytest.raises(PolicyLoadError, match="unique"):
        load_policy_from_dict(raw)


@pytest.mark.parametrize("mutation", ["any-all", "empty", "relations", "reference", "gate"])
def test_ambiguous_policy_is_an_input_error(mutation):
    raw = raw_policy()
    required = raw["rules"][0]["require"]
    if mutation == "any-all":
        required["groups"][0]["all_changed"] = ["other.json"]
    elif mutation == "empty":
        required["groups"][0]["any_changed"] = []
    elif mutation in {"relations", "reference"}:
        relation = {"name": "sync", "when_any_changed": ["src/**"], "require_groups": ["missing" if mutation == "reference" else "API"]}
        required["cross_file"] = [relation, deepcopy(relation)] if mutation == "relations" else [relation]
    else:
        raw["gate"]["on_unverified"] = "pass"
    with pytest.raises(PolicyLoadError):
        load_policy_from_dict(raw)


def test_independent_group_order_preserves_decision():
    raw = raw_policy()
    raw["rules"][0]["require"]["groups"].append({"name": "release", "all_changed": ["CHANGELOG.md"], "content": "paths"})
    files = [changed(), document(), document("release note", "CHANGELOG.md")]
    first = run(files, policy=load_policy_from_dict(raw))
    raw["rules"][0]["require"]["groups"].reverse()
    second = run(files, policy=load_policy_from_dict(raw))
    assert (first.result, first.rule_decisions[0].decision, first.rule_decisions[0].verification) == (second.result, second.rule_decisions[0].decision, second.rule_decisions[0].verification)


def test_direct_core_call_rejects_duplicate_programmatic_policy():
    from drift_gate.core.policy.validator import PolicyValidationError
    candidate = policy()
    candidate.rules[0].require.groups.append(deepcopy(candidate.rules[0].require.groups[0]))
    with pytest.raises(PolicyValidationError, match="unique"):
        run([changed()], policy=candidate)


@pytest.mark.parametrize("action,expected", [("fail", "fail"), ("warn", "warn")])
def test_missing_snapshots_are_unknown_not_proved_violations(action, expected):
    file = ChangedFile("src/api.py", "modified", patch="-@app.get('/orders', response_model=FullOrder)\n+@app.get('/orders', response_model=BriefOrder)\n")
    result = run([file, document("unrelated text")], policy=policy(action=action))
    assert result.result == expected
    assert not result.violations
    assert result.rule_decisions[0].decision == "undetermined"
    assert result.rule_decisions[0].verification == "unverified"
    assert result.to_dict()["summary"]["undetermined_rules"] == 1
    assert "Verification limits" in MarkdownReporter().render(result)
    assert "complete before/after" in HtmlReporter().render(result)
    compact = _compact_result(result, [file], token_budget=200)
    assert compact["verification_limits"][0]["decision"] == "undetermined"


def test_legacy_auto_reports_its_path_fallback_but_explicit_paths_are_verified():
    file = ChangedFile("src/api.py", "modified", patch="-response_model=FullOrder\n+response_model=BriefOrder\n")
    doc = document("irrelevant prose", "docs/api/other.md")
    auto = run([file, doc], policy=policy(mode="auto", paths=["docs/api/**"]))
    paths = run([file, doc], policy=policy(mode="paths", paths=["docs/api/**"]))
    assert auto.result == paths.result == "pass"
    assert auto.rule_decisions[0].verification == "unverified"
    assert paths.rule_decisions[0].verification == "verified"
    assert "Legacy auto fallback" in auto.rule_decisions[0].satisfied_groups[0].evidence


@pytest.mark.parametrize("component", [False, True])
def test_same_url_field_removal_requires_matching_response_schema(component):
    correct = run([changed(), document(openapi(component=component))], policy=policy())
    stale = run([changed(), document(openapi({"id": {"type": "integer"}, "label": {"type": "string"}}))], policy=policy())
    unrelated = run([changed(), document(openapi(path="/billing"))], policy=policy())
    assert correct.result == "pass"
    assert stale.result == unrelated.result == "fail"
    assert len(stale.violations) == 1
    assert stale.rule_decisions[0].verification == "verified"


def test_model_name_change_with_equal_contract_does_not_require_doc_change():
    result = run([changed(after=source(model="BriefOrder"))], policy=policy())
    assert result.result == "pass"
    assert result.rule_decisions[0].verification == "not-applicable"


@pytest.mark.parametrize("after_fields,doc_fields", [
    ("id: str", {"id": {"type": "string"}}),
    ("id: int = 1", {"id": {"type": "integer", "default": 1}}),
])
def test_field_type_and_required_default_are_contract_changes(after_fields, doc_fields):
    file = changed(before=source("id: int"), after=source(after_fields))
    assert run([file, document(openapi())], policy=policy()).result == "fail"
    assert run([file, document(openapi(doc_fields))], policy=policy()).result == "pass"


@pytest.mark.parametrize("operation", ["add", "delete", "rename-path", "method"])
def test_contract_identity_and_deletion(operation):
    if operation == "add":
        file, doc = changed(before="", status="added"), document()
    elif operation == "delete":
        file, doc = changed(after="", status="deleted"), document(json.dumps({"openapi": "3.1.0", "paths": {}}))
    elif operation == "rename-path":
        file, doc = changed(after=source("id: int", path="/members")), document(openapi(path="/members"))
    else:
        file, doc = changed(after=source("id: int", method="post")), document(openapi(method="post"))
    assert run([file, doc], policy=policy()).result == "pass"
    assert run([file, document(openapi({"id": {"type": "integer"}, "label": {"type": "string"}}))], policy=policy()).result == "fail"


@pytest.mark.parametrize("after", [
    source("id: list[int]"), source("id: int = Field(0)"), source("id: int = None"),
    source().replace("BaseModel):", "Parent):"),
    source().replace("app = FastAPI()", "app = FastAPI(root_path='/prefix')"),
    source().replace("app = FastAPI()", "app = APIRouter(prefix='/prefix')"),
    source().replace("response_model=Order", "response_model=External"),
    source().replace("'/orders'", "PATH"),
    source() + "app.include_router(other)\n", source() + "Order = other\n",
    source() + "int = str\n", source().replace("class Order", "@custom\nclass Order"),
    source() + "app.router.prefix = '/hidden'\n", source() + "other = app\n",
    source().replace("@app.get", "@registered_get"), source() + "app.get('/hidden')(orders)\n",
    source() + "from elsewhere import *\n",
    source() + "(Order := Other)\n", source() + "app.routes[:] = []\n", source() + "del Order\n",
])
def test_unsupported_code_never_becomes_empty_or_paths_success(after):
    result = run([changed(after=after), document()], policy=policy(action="warn"))
    assert result.result == "warn"
    assert result.rule_decisions[0].decision == "undetermined"
    assert not result.violations


@pytest.mark.parametrize("text", ["not json", "[]", '{"openapi":"3.1.0","paths":{},"paths":{}}',
    openapi().replace('"integer"', '"integer", "enum": [1]'),
    openapi().replace('"integer"', '"integer", "default": NaN')])
def test_unreadable_or_unsupported_docs_are_unknown(text):
    result = run([changed(), document(text)], policy=policy(action="warn"))
    assert result.result == "warn"
    assert result.rule_decisions[0].decision == "undetermined"


def test_known_violation_is_retained_alongside_unknown_group():
    raw = raw_policy(action="warn")
    raw["rules"][0]["require"]["groups"].append({"name": "release", "all_changed": ["CHANGELOG.md"], "content": "paths"})
    result = run([changed(), document("bad json")], policy=load_policy_from_dict(raw))
    assert result.result == "fail"
    assert result.rule_decisions[0].decision == "violated"
    assert result.rule_decisions[0].verification == "partial"
    assert [g.name for g in result.violations[0].unsatisfied_groups] == ["release"]
    assert result.to_dict()["summary"]["undetermined_rules"] == 0
    assert result.to_dict()["summary"]["unverified_rules"] == 1


def test_each_all_document_must_cover_complete_contract_and_partial_is_visible():
    result = run([changed(), document(openapi(path="/billing")), document("broken", "other.json")],
                 policy=policy(paths=["openapi.json", "other.json"], all_docs=True, action="warn"))
    assert result.result == "fail"
    assert result.rule_decisions[0].verification == "partial"


def test_current_unchanged_openapi_can_already_satisfy_contract(tmp_path):
    (tmp_path / "openapi.json").write_text(openapi())
    files = attach_env_documents([changed()], policy(), local_document_reader(tmp_path))
    assert files[-1].status == "unchanged"
    result = inspect(changed_files=files, policy=policy())
    assert result.result == "pass"
    assert "before_source" not in json.dumps(result.to_dict())
    assert "after_source" not in json.dumps(result.to_dict())


def test_receipt_digest_changes_when_snapshot_changes_without_patch_change():
    first = inspect(changed_files=[changed(), document()], policy=policy())
    second = inspect(changed_files=[changed(after=source("id: str")), document()], policy=policy())
    assert first.execution["input_sha256"] != second.execution["input_sha256"]


def test_guard_rejects_unknown_gate_weakening():
    assert "weakened unverified-content gate" in weakening_reasons(policy(), policy(action="warn"))


def test_extract_contract_never_runs_module_code():
    text = source() + "raise RuntimeError('do not execute')\n"
    assert extract_responses(text)[("GET", "/orders")]["id"]["type"] == "integer"
    with pytest.raises(UnsupportedContract):
        extract_responses(None)


def test_unknown_antecedent_does_not_invent_a_proved_violation():
    raw = raw_policy(mode="paths", paths=["docs/a.md"], action="warn")
    raw["rules"][0]["when"]["min_change_intensity"] = "route-contract-change"
    file = ChangedFile("src/api.py", "modified", patch="", analysis_method="unavailable")
    result = run([file], policy=load_policy_from_dict(raw))
    assert result.result == "warn"
    assert not result.violations
    assert result.rule_decisions[0].decision == "undetermined"


def test_any_alternative_suffices_and_all_keeps_known_failure_with_unknown():
    fields = {"id": {"type": "integer"}}
    files = [changed(), document(openapi(fields)), document("broken", "other.json")]
    assert run(files, policy=policy(paths=["openapi.json", "other.json"], action="warn")).result == "pass"
    files[0].after_source = source("id: str")
    result = run(files, policy=policy(paths=["openapi.json", "other.json"], all_docs=True, action="warn"))
    assert result.rule_decisions[0].decision == "violated"
    assert result.rule_decisions[0].verification == "partial"


def test_openapi_boolean_default_cannot_impersonate_integer_one():
    file = changed(before=source("id: int"), after=source("id: int = 1"))
    result = run([file, document(openapi({"id": {"type": "integer", "default": True}}))], policy=policy(action="warn"))
    assert result.result == "warn"
    assert result.rule_decisions[0].decision == "undetermined"


@pytest.mark.parametrize("all_docs,expected", [(False, "undetermined"), (True, "violated")])
def test_env_documents_apply_the_same_three_valued_contract(all_docs, expected):
    file = ChangedFile("src/config.py", "modified", patch="+value = os.getenv('NEW_KEY')\n")
    docs = [ChangedFile(".env.example", "modified", documented_env_keys=[]),
            ChangedFile("config/sample.env", "modified", documented_env_keys=None)]
    result = run([file, *docs], policy=policy(mode="env-keys", action="warn",
        paths=[".env.example", "config/sample.env"], all_docs=all_docs))
    assert result.rule_decisions[0].decision == expected
    assert result.rule_decisions[0].verification == ("partial" if all_docs else "unverified")


@pytest.mark.parametrize("mode", ["api-routes", "env-keys"])
def test_strict_modes_do_not_treat_unrecognized_content_as_paths(mode):
    file = ChangedFile("src/api.py", "modified", patch="+response_model = External\n")
    result = run([file, document("unrelated")], policy=policy(mode=mode, action="warn"))
    assert result.result == "warn"
    assert result.rule_decisions[0].decision == "undetermined"
