"""Text from paths, policies, ignore reasons and model output stays inert in the PR comment,
and an oversized report is shortened without breaking the Markdown structure."""
import re

from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Policy
from drift_gate.core.models.result import DriftIgnoreDirective
from drift_gate.reporters import markdown_text
from drift_gate.reporters.markdown import COMMENT_MAX_CHARS, MarkdownReporter

HOSTILE_MESSAGE = "# Approved by @octocat [click](http://evil.example/x) ![i](http://evil.example/a.png) <img src=x> `tick"
HOSTILE_PATH = "src/routes/`a`|b```.ts"


def policy(rules):
    return Policy.from_dict({"rules": rules, "gate": {"fail_on_blocker": True, "fail_on_major_count": 2}})


def rule(rule_id, pattern, message, severity="blocker"):
    return {"id": rule_id, "when": {"any_changed": [pattern]},
            "require": {"groups": [{"name": "docs **bold**", "any_changed": [f"docs/{rule_id}.md"]}]},
            "severity": severity, "message": message}


def fences_are_balanced(markdown):
    """CommonMark-style fence tracking: every opened fence is closed by a fence at least as long."""
    open_fence = None
    for line in markdown.split("\n"):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if not match:
            continue
        run_text, rest = match.groups()
        if open_fence is None:
            if "`" in rest and run_text[0] == "`":
                continue        # an inline code span that happens to start a line
            open_fence = run_text
        elif run_text[0] == open_fence[0] and len(run_text) >= len(open_fence) and not rest.strip():
            open_fence = None
    return open_fence is None


def hostile_report():
    files = [ChangedFile(path=HOSTILE_PATH, status="modified",
                         patch="@@ -1 +1 @@\n-old\n+```\n+new\n+````diff")]
    drift_ignores = [DriftIgnoreDirective(rule_id="minor-one", reason="see [x](http://evil.example) cc @octocat\n# fake")]
    result = run(changed_files=files, drift_ignores=drift_ignores,
                 policy=policy([rule("hostile", "src/routes/**", HOSTILE_MESSAGE),
                                rule("minor-one", "src/routes/**", "minor", severity="minor")]))
    return result, MarkdownReporter().render(result)


def test_hostile_text_does_not_reach_the_comment_as_markdown():
    result, md = hostile_report()
    assert [v.rule_id for v in result.violations] == ["hostile"]
    assert "@octocat" not in md                      # a zero-width character breaks the mention
    assert not re.search(r"(?<!\\)\]\(http", md)     # no live link or image
    assert "<img" not in md and "<script" not in md
    assert not re.search(r"(?m)^#{1,6} Approved", md)  # the message cannot become a heading
    assert fences_are_balanced(md)
    assert md.count("<details>") == md.count("</details>")


def test_inline_helpers_keep_values_inside_their_span():
    assert markdown_text.code("a`b") == "``a`b``"
    assert markdown_text.code("`x`") == "`` `x` ``"
    assert markdown_text.code("p|q", table=True) == "`p\\|q`"
    assert markdown_text.fenced("x\n```\ny", "diff").startswith("````diff\n")
    assert markdown_text.text("line one\n# two") == "line one # two"
    assert markdown_text.text("1. item") == "1\\. item"
    assert markdown_text.text("snake_case_name") == "snake_case_name"
    assert markdown_text.text("_em_ *b*") == "\\_em\\_ \\*b\\*"


def oversized_result(count=400):
    rules = [rule(f"rule-{i}", f"src/area{i}/**", "m" * 300) for i in range(count)]
    files = [ChangedFile(path=f"src/area{i}/file.ts", status="modified",
                         patch="@@ -1 +1 @@\n" + "\n".join(f"+line {j} " + "x" * 80 for j in range(40)))
             for i in range(count)]
    return run(changed_files=files, drift_ignores=[], policy=policy(rules))


def test_oversized_report_is_shortened_to_the_limit_with_balanced_markdown():
    result = oversized_result()
    full = MarkdownReporter().render(result)
    assert len(full) > COMMENT_MAX_CHARS
    shortened = MarkdownReporter().render(result, max_chars=COMMENT_MAX_CHARS)
    assert len(shortened) <= COMMENT_MAX_CHARS
    assert shortened.startswith(MarkdownReporter.MARKER)
    assert "길이 제한" in shortened and "JSON" in shortened
    assert "rule-0" in shortened                        # the highest-severity items stay listed
    assert fences_are_balanced(shortened)
    assert shortened.count("<details>") == shortened.count("</details>")


def test_small_report_is_not_changed_by_the_limit():
    result = oversized_result(count=2)
    assert MarkdownReporter().render(result, max_chars=COMMENT_MAX_CHARS) == MarkdownReporter().render(result)


def test_limit_smaller_than_the_summary_still_returns_a_valid_report():
    result = oversized_result(count=50)
    tiny = MarkdownReporter().render(result, max_chars=1500)
    assert len(tiny) <= 1500 and tiny.startswith(MarkdownReporter.MARKER)
    assert "`FAIL`" in tiny and "BLOCKER 50" in tiny
    assert fences_are_balanced(tiny) and tiny.count("<details>") == tiny.count("</details>")
