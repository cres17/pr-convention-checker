"""Run the design's acceptance matrix A01-A17 (detailed design section 18) and record the evidence.

Each row names the regression tests that exercise its pass condition locally and, separately,
the evidence that only an external path can supply (remote CI artifacts, installed apps, human
labels). Local tests passing is reported as ``local-tests-pass``; it never upgrades a row whose
pass condition needs external evidence. Results are written once and never overwrite an earlier run.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
T = 'drift_gate/tests/'

MATRIX = [
    {'id': 'A01', 'target': 'facts constructor', 'condition': 'must above may is rejected; no successful IR',
     'tests': [T + 'test_typed_facts.py::test_inconsistent_bounds_and_certain_delta_overlap_are_rejected',
               T + 'test_typed_facts.py::test_unknown_requires_typed_reason_codes']},
    {'id': 'A02', 'target': 'no-delta', 'condition': 'equal must sets with a route only in may are not promoted to N/A',
     'tests': [T + 'test_typed_facts.py::test_equal_lower_sets_cannot_prove_no_delta',
               T + 'test_obligation_planner.py::test_open_upper_bound_is_not_no_delta_and_assessment_cannot_lie']},
    {'id': 'A03', 'target': 'mixed planner', 'condition': 'env unchanged, route changed, stale doc keeps API F',
     'tests': [T + 'test_obligation_planner.py::test_design_mixed_contract_matrix',
               T + 'test_enterprise_correctness.py::test_explicit_mixed_groups_keep_known_api_failure',
               T + 'test_enterprise_correctness.py::test_mixed_python_contracts_never_disappear']},
    {'id': 'A04', 'target': 'open scope', 'condition': 'known API T with unsupported source: root U, coverage open',
     'tests': [T + 'test_profile_discovery.py::test_unsupported_language_is_not_vacuous_closed_discovery',
               T + 'test_obligation_planner.py::test_open_domains_without_candidates_have_mandatory_guards',
               T + 'test_scope_analysis.py::test_service_with_unread_languages_is_not_certified_whole']},
    {'id': 'A05', 'target': 'known violation', 'condition': 'known F with an unknown child stays F, coverage open',
     'tests': [T + 'test_obligation_planner.py::test_all_documents_keep_known_false_with_unknown_sibling',
               T + 'test_proof_evaluation.py::test_contract_proof_keeps_known_false_and_mandatory_open_guards']},
    {'id': 'A06', 'target': 'OR alternative', 'condition': 'T document with another alternative unavailable: T, scope open',
     'tests': [T + 'test_obligation_planner.py::test_document_alternatives_keep_unknown_coverage_even_with_positive_witness',
               T + 'test_proof_evaluation.py::test_decisive_witness_preserves_unused_unknown_coverage']},
    {'id': 'A07', 'target': 'service identity', 'condition': 'same method/path in two services are not merged',
     'tests': [T + 'test_scope_analysis.py::test_same_route_in_two_services_is_two_facts_and_moves_are_not_merged']},
    {'id': 'A08', 'target': 'manifest absence', 'condition': 'unreadable input is not converted to absent',
     'tests': [T + 'test_input_snapshot.py::test_present_empty_missing_unavailable_and_not_collected_are_distinct',
               T + 'test_git_collection.py::test_review_uses_collected_patches_and_rejects_unreadable_source',
               T + 'test_obligation_planner.py::test_unreadable_or_deleted_document_is_not_known_missing']},
    {'id': 'A09', 'target': 'closure', 'condition': 'deleted import and unchanged consumer are in the impact scope',
     'tests': [T + 'test_scope_analysis.py::test_unchanged_consumer_and_deleted_edge_are_in_the_impact_scope',
               T + 'test_scope_analysis.py::test_js_import_forms_are_edges_or_open_boundaries']},
    {'id': 'A10', 'target': 'trusted checker', 'condition': 'a candidate weakening checker/policy cannot pass on its own',
     'tests': [T + 'test_trust_boundary.py::test_candidate_that_edits_the_checker_needs_review_even_when_it_passes',
               T + 'test_trust_boundary.py::test_weakened_candidate_engine_cannot_turn_a_trusted_fail_into_a_pass',
               T + 'test_trust_boundary.py::test_moving_ref_after_the_trusted_run_cannot_rebind_its_verdict',
               T + 'test_git_immutable.py::test_weakened_candidate_is_rejected'],
     'external': {'need': 'CI trusted-engine job verdict from an installed pinned engine, and a required-status-check '
                          'rule on the default branch (a repository setting outside the code)',
                  'evidence': ['CI run 37903285344 trusted-engine job: pass on d6d2f7f',
                               'required-status-check rule: not verified'],
                  'state': 'partial'}},
    {'id': 'A11', 'target': 'expiry/cache', 'condition': 'date, approval and profile changes change the key; '
                                                          'past waivers are not reused',
     'tests': [T + 'test_org_and_cache.py::test_every_key_input_invalidates',
               T + 'test_enterprise_correctness.py::test_expiry_is_replayable_and_inclusive_on_expiry_date',
               T + 'test_enterprise_correctness.py::test_expiring_ignore_without_context_is_not_silently_authorized',
               T + 'test_trust_boundary.py::test_stored_waiver_is_admitted_only_with_a_verifiable_signature']},
    {'id': 'A12', 'target': 'cancel', 'condition': 'a worker succeeding after cancel cannot reopen the run',
     'tests': [T + 'test_run_lifecycle.py::test_operator_cancel_discards_late_reply',
               T + 'test_run_lifecycle.py::test_reply_racing_a_cancel_is_rejected',
               T + 'test_run_lifecycle.py::test_every_state_event_pair_keeps_closed_runs_closed']},
    {'id': 'A13', 'target': 'publication', 'condition': 'head A->B->A and older attempts never become latest',
     'tests': [T + 'test_run_lifecycle.py::test_head_aba_cannot_resurrect_old_attempt',
               T + 'test_run_lifecycle.py::test_cli_latest_pointer_fences_concurrent_head_change',
               T + 'test_github_publication.py::test_head_change_before_or_during_write_marks_stale'],
     'external': {'need': 'real provider behaviour (the tests use a fake GitHub provider)',
                  'evidence': ['docs/assessment/run-lifecycle-implementation-2026-10-08/live-pr1 (PR #1, manual session, '
                               'code of 5cd00ed; not re-run since)'],
                  'state': 'partial'}},
    {'id': 'A14', 'target': 'write timeout', 'condition': 'lost response stays unknown; no blind re-send',
     'tests': [T + 'test_github_publication.py::test_lost_create_response_is_resolved_by_key_not_by_reposting',
               T + 'test_run_lifecycle.py::test_lost_response_reconciliation_table'],
     'external': {'need': 'real provider fault injection (the tests use a fake GitHub provider)',
                  'evidence': ['live-pr1 cases C and D: response dropped after sending / request not sent, against '
                               'GitHub for PR #1 (code of 5cd00ed)'],
                  'state': 'partial'}},
    {'id': 'A15', 'target': 'schema direction', 'condition': 'per-direction verdicts agree with an independent oracle',
     'tests': [T + 'test_decision_models.py::test_direction_specific_schema_rules',
               T + 'test_decision_models.py::test_composite_inclusion_is_sound_against_jsonschema',
               T + 'test_decision_models.py::test_review_counterexamples_are_never_reported_compatible']},
    {'id': 'A16', 'target': 'installed app', 'condition': 'empty cache and blocked network: real analysis matches',
     'tests': [T + 'test_packaged_cli.py::test_package_cli_verifier_through_the_cli_entry'],
     'external': {'need': 'Desktop build artifacts per OS: packaged UI check, packaged CLI evidence check, DMG and '
                          'installer',
                  'evidence': ['Desktop run 37756285887 (a4b0219): Windows, macOS arm64 and Intel succeeded; later '
                               'commits change the engine and need their own run'],
                  'state': 'partial'}},
    {'id': 'A17', 'target': 'holdout', 'condition': 'new repositories, unsupported and skipped cases keep all four axes '
                                                     'and every denominator',
     'tests': [T + 'test_holdout_evaluation.py::test_freeze_pin_run_and_errors_stay_in_denominators',
               T + 'test_holdout_evaluation.py::test_labels_for_another_frozen_input_are_refused',
               T + 'test_holdout_evaluation.py::test_holdout_runs_the_product_inspection_path'],
     'external': {'need': 'collected holdout cases and independent (human) labels',
                  'evidence': [], 'state': 'missing'}},
]


def run_tests(node_ids, junit):
    completed = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--junitxml', str(junit),
                                *node_ids], cwd=ROOT, capture_output=True, text=True)
    outcomes = {}
    for case in ET.parse(junit).getroot().iter('testcase'):
        module = case.get('classname', '').replace('.', '/') + '.py'
        name = case.get('name', '')
        state = ('failed' if case.find('failure') is not None or case.find('error') is not None
                 else 'skipped' if case.find('skipped') is not None else 'passed')
        key = f"{module}::{name.split('[')[0]}"
        previous = outcomes.get(key)
        # A parametrised test passes only if every parameter passed.
        outcomes[key] = state if previous in (None, state) else ('failed' if 'failed' in (previous, state) else 'skipped')
    return completed.returncode, outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='Output JSON (never overwritten)')
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f'{args.out} exists; results are never overwritten')
    node_ids = sorted({test for row in MATRIX for test in row['tests']})
    with tempfile.TemporaryDirectory(prefix='driftgate-acceptance-') as temporary:
        code, outcomes = run_tests(node_ids, Path(temporary) / 'junit.xml')
    rows = []
    for row in MATRIX:
        states = {test: outcomes.get(test, 'not-collected') for test in row['tests']}
        local = ('local-tests-pass' if all(s == 'passed' for s in states.values()) else
                 'local-tests-fail' if any(s in ('failed', 'not-collected') for s in states.values()) else
                 'local-tests-skipped')
        external = row.get('external')
        status = local if external is None or local != 'local-tests-pass' else \
            f"local-tests-pass; external evidence {external['state']}"
        rows.append({**row, 'test_outcomes': states, 'local': local, 'status': status})
    report = {'schema': 'acceptance-matrix-v1', 'design': 'drift-gate-enterprise-detailed-design-2026-10-07 section 18',
              'run_at': datetime.now(timezone.utc).isoformat(), 'python': sys.version.split()[0],
              'pytest_exit_code': code, 'rows': rows,
              'interpretation': 'local regression evidence per row; rows with external requirements are not complete '
                                'until that evidence exists'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
    for row in rows:
        print(f"{row['id']}  {row['status']}")
    sys.exit(0 if all(row['local'] == 'local-tests-pass' for row in rows) else 1)


if __name__ == '__main__':
    main()
