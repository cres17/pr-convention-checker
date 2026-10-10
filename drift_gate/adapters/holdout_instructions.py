"""Reviewer instructions embedded in every blind review packet."""

REVIEW_INSTRUCTIONS = """You are labelling the correct outcome of one contract rule for one change set.
You see the rule (trigger paths and required documents) and the changed files only.
You do not see Drift Gate's output or any stored expectation; do not try to infer them.

For each item with kind "rule" answer one label:
  satisfied      - the rule applies and the required documents reflect the code change
  violated       - the rule applies and a required document is missing or contradicts the change
  not-applicable - the change does not trigger the rule's duty (for example no contract change)
  undecidable    - the given files are not enough to decide; say what is missing
For each item with kind "pr-action" answer pass, warn or fail for the whole change under the policy gate.

Write a short rationale that names the files and lines you relied on.
Declare reviewer_kind honestly: "human" for a person, "llm-proxy" for any model output.
One JSON object per line: {"item_id", "reviewer_id", "reviewer_kind", "label", "rationale"}.
"""
