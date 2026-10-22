"""
CLI adapter.

Friendly entrypoints:
- drift-gate check
- drift-gate report
- drift-gate init
- drift-gate doctor
- drift-gate demo
- drift-gate eval

For local preflight, running without a command behaves like ``check``.
"""
import json
import os
import sys
import time
import webbrowser
from pathlib import Path

from drift_gate.adapters.bundle_codec import BundleError
from drift_gate.adapters.claude.enricher import ClaudeEnricher
from drift_gate.adapters.cli.common import (  # noqa: F401
    CLIInputError,
    _parse_days,
    _read_json_file,
)
from drift_gate.adapters.cli.doctor_command import (  # noqa: F401
    _broad_glob_warnings,
    _console_entrypoints_ok,
    _dead_rule_warnings,
    _git_ok,
    _run_doctor,
)
from drift_gate.adapters.cli.holdout_command import run as _run_holdout
from drift_gate.adapters.cli.org_command import run as _run_org
from drift_gate.adapters.cli.output import write_stdout as _write_stdout
from drift_gate.adapters.cli.parser import build_parser as _build_parser
from drift_gate.adapters.cli.presets import (  # noqa: F401 -- public compatibility import
    POLICY_PRESETS,
    POLICY_TEMPLATE,
)
from drift_gate.adapters.cli.review_command import (  # noqa: F401
    _collect_python_files,
    _review_reporter_field_gaps,
    _run_docs_check,
    _run_explain,
    _run_history,
    _run_review,
)
from drift_gate.adapters.cli.self_audit_command import (  # noqa: F401
    _format_self_audit_markdown,
    _render_self_audit_html,
    _run_self_audit,
)
from drift_gate.adapters.cli.setup_command import (  # noqa: F401
    _detect_frameworks,
    _format_recommendations,
    _has_any,
    _install_mcp_config,
    _recommend_docs_paths,
    _repo_paths,
    _repo_recommendations,
    _run_init,
    _run_install,
    _run_setup,
    _select_init_preset,
    recommend_preset,
)
from drift_gate.adapters.eval.runner import (
    EvalEngineComparison,
    benchmark_gate_failures,
    compare_engines,
    compare_paths,
    evaluate_paths,
    render_comparison_html,
    render_comparison_markdown,
    render_engine_comparison_html,
    render_engine_comparison_markdown,
    render_markdown,
    require_fixture_paths,
    write_case_reports,
)
from drift_gate.adapters.execution import atomic_json, atomic_text, identity
from drift_gate.adapters.git.client import GitAdapter, GitInputError
from drift_gate.adapters.github.client import GitHubAdapter, parse_drift_ignores
from drift_gate.adapters.history.store import (
    append_result,
    ignored_rule_counts,
    load_records,
)
from drift_gate.adapters.inspection import (
    inspect as run,  # noqa: F401 -- existing patch point; check now captures then inspects
)
from drift_gate.adapters.policy_loader import (
    load_policy,
    read_policy,
    require_check_policy,
)
from drift_gate.core.evaluation.result_guard import ResultValidationError
from drift_gate.core.gating.temporal import apply_temporal_gate
from drift_gate.core.policy.loader import PolicyLoadError
from drift_gate.core.policy.validator import validate
from drift_gate.reporters.html import HtmlReporter
from drift_gate.reporters.json_reporter import JsonReporter
from drift_gate.reporters.markdown import MarkdownReporter


def run_cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv.insert(0, "check")

    parser = _build_parser()
    args = parser.parse_args(argv)

    inspections = {"check": _run_check, "report": _run_check,
                   "review": _run_review, "self-audit": _run_self_audit,
                   "history": _run_history, "bundle": _run_bundle, "run": _run_runs,
                   "publication": _run_publication, "engine": _run_engine, "scope": _run_scope, "migrate": _run_migrate,
                   "holdout": _run_holdout, "org": _run_org,
                   "trusted-check": _run_trusted_check}
    if args.command in inspections:
        args.execution = identity()
        from drift_gate.adapters.engine_artifact import EngineArtifactError
        from drift_gate.adapters.holdout import HoldoutError
        from drift_gate.adapters.run_coordinator import RunTerminated
        from drift_gate.adapters.run_store import RunStoreError
        from drift_gate.core.budget import ResourceLimit
        try:
            inspections[args.command](args)
        except (CLIInputError, GitInputError, PolicyLoadError, OSError, UnicodeError, ResultValidationError,
                BundleError, RunStoreError, RunTerminated, EngineArtifactError, ResourceLimit, HoldoutError) as exc:
            terminated = isinstance(exc, RunTerminated)
            code = (exc.state.replace('-', '_') if terminated else
                    'resource_limit' if isinstance(exc, ResourceLimit) else
                    'result_validation_error' if isinstance(exc, ResultValidationError) else 'input_error')
            from drift_gate.core.gating.enforcement import execution_outcome
            error = {'execution': {**args.execution, 'status': code, 'outcome': execution_outcome(code)},
                     'error': {'code': code, 'message': str(exc),
                               **({'resource': exc.to_dict()} if isinstance(exc, ResourceLimit) else {})}}
            controller = getattr(args, 'run_controller', None)
            if controller is not None:
                try:
                    error['execution']['run'] = controller.view().to_dict()
                    state = error['execution']['run'].get('state') or ''
                    error['execution']['outcome']['publication_state'] = state if state.startswith('publi') else None
                except (RunStoreError, OSError):
                    error['execution']['run'] = {'state': 'unreadable'}
            # holdout and engine --out name write-once artifacts; an error is never written in their place.
            write_once_out = args.command in {'holdout', 'engine'}
            for output in (getattr(args, 'out_json', None), None if write_once_out else getattr(args, 'out', None)):
                if output:
                    atomic_json(output, error)
            for output in (getattr(args, 'out_html', None), getattr(args, 'out_md', None),
                           getattr(args, 'html', None)):
                if output:
                    import html
                    atomic_text(output, '<pre>' + html.escape(json.dumps(error, ensure_ascii=False)) + '</pre>')
            if getattr(args, "json_output", False) or getattr(args, "format", "") == "json":
                _write_stdout(json.dumps(error, ensure_ascii=False))
            print(str(exc), file=sys.stderr)
            # 3: the run closed without a semantic result (cancelled/timed out/recovered).
            sys.exit(3 if terminated else 2)
        return

    if args.command == "demo":
        _run_demo(args)
        return
    if args.command == "eval":
        _run_eval(args)
        return
    if args.command == "init":
        _run_init(args)
        return
    if args.command == "doctor":
        _run_doctor(args)
        return
    if args.command == "explain":
        _run_explain(args)
        return
    if args.command == "docs-check":
        _run_docs_check(args)
        return
    if args.command == "install":
        _run_install(args)
        return
    if args.command == "setup":
        _run_setup(args)
        return
    if args.command == "serve":
        _run_serve(args)
        return


def _run_check(args) -> None:
    if args.comparison_mode is None:
        # A local check of a branch compares against its fork point, so commits the base branch gained
        # later are not reported as this branch's deletions. An explicit commit pair (--head) keeps the
        # literal base: its evidence binds the resolved base OID.
        args.comparison_mode = 'commit' if args.head else 'merge-base'
    lifecycle_options = [name for name, value in (
        ('--timeout-seconds', args.timeout_seconds), ('--retry-of', args.retry_of),
        ('--latest-target', args.latest_target)) if value is not None]
    if lifecycle_options and not args.run_store:
        raise CLIInputError(f'{", ".join(lifecycle_options)} requires --run-store')
    if args.latest_target is not None and not (args.head and args.evidence_store):
        raise CLIInputError('--latest-target requires immutable --head mode and --evidence-store receipts')
    if not args.run_store:
        return _check_body(args, None)
    from drift_gate.adapters.run_coordinator import RunController, RunTerminated
    controller = RunController(args.run_store, run_id=args.execution['run_id'],
                               timeout_seconds=args.timeout_seconds)
    controller.start(retry_of=args.retry_of, data={
        'command': args.command, 'mode': 'immutable-git' if args.head else 'github-pr' if args.pr else 'local-git',
        'base': args.base, 'head': args.head, 'pr': args.pr, 'repo': args.repo,
        'publication_target': args.latest_target, 'evidence_store': bool(args.evidence_store)})
    args.run_controller = controller
    import signal
    previous_handler = None

    def operator_signal(signum, frame):
        raise KeyboardInterrupt

    try:
        previous_handler = signal.signal(signal.SIGTERM, operator_signal)
    except (ValueError, OSError, AttributeError):  # not the main thread / unsupported
        previous_handler = None
    try:
        _check_body(args, controller)
    except SystemExit:
        raise
    except RunTerminated:
        raise
    except KeyboardInterrupt:
        controller.fail('cancelled', 'interrupt', 'interrupted by the operator')
        view = controller.view()
        raise RunTerminated(view.state, 'interrupt', view) from None
    except Exception as exc:
        view = controller.view()
        early = view is not None and lifecycle_stage_index(view.state) < lifecycle_stage_index('analyzing')
        input_error = isinstance(exc, (CLIInputError, GitInputError, PolicyLoadError, UnicodeError, BundleError))
        state = 'rejected-input' if early and input_error else 'internal-error'
        code = ('result_validation_error' if isinstance(exc, ResultValidationError)
                else 'input_error' if input_error else type(exc).__name__)
        controller.fail(state, code, exc)
        raise
    finally:
        if previous_handler is not None:
            signal.signal(signal.SIGTERM, previous_handler)


def lifecycle_stage_index(state):
    from drift_gate.core.execution.lifecycle import STAGES
    return STAGES.index(state) if state in STAGES else len(STAGES)


def _authority_digest(snapshot):
    """Policy, approvals and comparison basis that a latest result depends on."""
    from hashlib import sha256

    from drift_gate.adapters.bundle_codec import decode_json
    from drift_gate.core.models.input_manifest import canonical_bytes
    payload = decode_json(snapshot.payload)
    evidence = snapshot.git_evidence
    basis = {'schema': 'latest-authority-v1', 'policy_source_sha256': sha256(
                 (payload.get('policy_source') or '').encode('utf-8')).hexdigest(),
             'policy': payload['policy'], 'drift_ignores': payload['drift_ignores'],
             'policy_anchor': {'revision': evidence.trusted_revision, 'path': evidence.policy_path,
                               'sha256': evidence.expected_policy_sha256},
             'base_oid': evidence.subject.base_oid, 'comparison_mode': evidence.subject.comparison_mode,
             'evaluation_context': payload['context'], 'contract_proofs': payload['contract_proofs']}
    return sha256(canonical_bytes(basis)).hexdigest()


def _check_body(args, controller) -> None:
    from drift_gate.adapters.git.client import repository_root
    from drift_gate.adapters.inspection import inspect_snapshot

    def stage(state, **data):
        if controller is not None:
            controller.advance(state, **data)

    def bounded(name, function):
        return controller.call(name, function) if controller is not None else function()

    if bool(args.pr) != bool(args.repo):
        raise GitInputError('Specify both --pr and --repo for remote PR inspection')
    if args.head and (args.pr or not args.trusted_policy_ref or not args.trusted_policy_sha256):
        raise GitInputError('Immutable --head requires --trusted-policy-ref and --trusted-policy-sha256; PR API mode is separate')
    if not args.head and (args.trusted_policy_ref or args.trusted_policy_sha256):
        raise GitInputError('Trusted policy options require immutable --head mode')
    # Immutable collection resolves the repository with its isolated Git
    # environment; the legacy root probe would honor caller GIT_DIR/GIT_WORK_TREE.
    root = Path.cwd() if args.pr or args.head else repository_root()
    start = time.perf_counter()
    if args.head:
        from drift_gate.adapters.git.immutable import collect_git_snapshot
        stage('validated')
        from drift_gate.core.budget import InspectionBudget
        budget = InspectionBudget.from_policy(None, clock=time.monotonic)
        args.inspection_budget = budget
        snapshot = bounded('captured', lambda: collect_git_snapshot(root=root, base=args.base, head=args.head,
            trusted_policy_ref=args.trusted_policy_ref, trusted_policy_sha256=args.trusted_policy_sha256,
            policy_path=args.policy or '.drift-gate.yml', comparison_mode=args.comparison_mode,
            contract_proofs=args.contract_proofs, budget=budget))
        captured = snapshot.materialize()
        args.policy_source, policy_for_run = captured['policy_source'], captured['policy']
        changed_files = captured['changed_files']
    else:
        args.policy = str(Path(args.policy).resolve() if args.policy is not None else root / '.drift-gate.yml')
        args.policy_source, args.loaded_policy = read_policy(args.policy)
        require_check_policy(args.loaded_policy)
        validate(args.loaded_policy).raise_if_errors()
        stage('validated')
        args.local_root = root

        def collect():
            files, ignores = _collect_inputs(args)
            if args.loaded_policy and not (args.pr and args.repo):
                from drift_gate.adapters.docs.content import (
                    attach_env_documents,
                    local_document_reader,
                )
                files = attach_env_documents(files, args.loaded_policy, local_document_reader(root))
                from drift_gate.adapters.removed_key_usage import attach_local_usage
                files = attach_local_usage(files, args.loaded_policy, root)
            return files, ignores

        changed_files, drift_ignores = bounded('captured', collect)
        policy_for_run = args.loaded_policy
        from datetime import datetime, timezone

        from drift_gate.adapters.snapshot import capture_inspection
        from drift_gate.core.models.evaluation_context import EvaluationContext
        context = EvaluationContext(datetime.now(timezone.utc).date())
        if args.pr:
            from drift_gate.adapters.execution import digest
            from drift_gate.adapters.github_action.runner import _approval_context
            context = _approval_context(getattr(args, 'approval_head', None), digest(args.policy_source), drift_ignores)
        snapshot = capture_inspection(changed_files=changed_files, policy=policy_for_run,
            drift_ignores=drift_ignores, context=context,
            policy_source=args.policy_source, policy_path=args.policy,
            provenance=getattr(args, 'input_provenance', {}), contract_proofs=args.contract_proofs)
    observation = None
    capture_data = {'input_sha256': snapshot.manifest.input_sha256, 'manifest_sha256': snapshot.manifest.digest,
                    'subject': snapshot.git_evidence.subject.to_dict() if snapshot.git_evidence else None}
    if controller is not None:
        if args.retry_of:
            previous = RunJournalView(args.run_store, args.retry_of)
            previous_input = previous.data.get('input_sha256')
            capture_data['retry_input_relation'] = ('previous-not-captured' if previous_input is None else
                'same-input' if previous_input == snapshot.manifest.input_sha256 else 'different-input')
        if args.latest_target is not None:
            from drift_gate.adapters.run_store import TargetLedger
            observation = TargetLedger(args.run_store, args.latest_target).observe(
                head_oid=snapshot.git_evidence.subject.head_oid, authority_sha256=_authority_digest(snapshot),
                run_id=args.execution['run_id'])
            capture_data['latest_observation'] = observation
    stage('captured', **capture_data)
    stage('planned', rules=len(policy_for_run.rules), changed_files=len(changed_files),
          contract_proofs=args.contract_proofs, plan_scope='policy-and-inputs-fixed-before-engine-call')
    stage('analyzing')
    result = bounded('analyzing', lambda: inspect_snapshot(snapshot, execution=args.execution))
    stage('evaluated', gate_result=result.result)
    runtime_seconds = time.perf_counter() - start
    result.scan_metrics.runtime_seconds = runtime_seconds
    base_result = result.to_dict()  # Projection re-validates the retained IR.
    if controller is not None:
        from drift_gate.adapters.run_coordinator import result_digest
        stage('result-validated', result_sha256=result_digest(base_result), gate_result=result.result)
    bundle = None
    if args.evidence_store:
        from drift_gate.adapters.evidence_bundle import save_bundle
        bundle = save_bundle(result, args.evidence_store)
        result.execution['evidence_bundle'] = bundle.to_dict()
    if controller is not None:
        from drift_gate.adapters.execution import atomic_bytes
        from drift_gate.core.models.input_manifest import canonical_bytes
        raw = canonical_bytes(base_result)
        atomic_bytes(controller.journal.path / 'result.json', raw)
        stage('persisted', result_file='result.json', result_file_sha256=hashlib_sha256(raw),
              receipt_sha256=bundle.to_dict()['receipt_sha256'] if bundle else None)
        if args.latest_target is None:
            stage('publication-skipped', publication={'state': 'publication-skipped', 'reason': 'no-target'})
        else:
            _publish_latest(args, controller, observation, bundle, base_result)
        result.execution['run'] = controller.view().to_dict()
        if 'outcome' in result.execution:
            state = result.execution['run'].get('state') or ''
            result.execution['outcome']['publication_state'] = state if state.startswith('publi') else None
    policy = policy_for_run
    if args.temporal_gate:
        threshold = (
            args.temporal_threshold
            or (policy.suppression.repeated_ignore_threshold if policy else 3)
        )
        records = load_records(
            args.history_path,
            days=_parse_days(args.temporal_window, option="--temporal-window"),
        )
        result = apply_temporal_gate(
            result,
            ignored_rule_counts(records),
            threshold=threshold,
        )
    if getattr(args, "token_estimate", False) and not result.skip:
        result.enrichment_metrics = ClaudeEnricher(
            api_key="",
            model=args.model,
        ).estimate_dry_run(result)
    elif (
        args.anthropic_api_key
        and result.violations
        and not result.skip
        and (policy is None or not policy.enrichment.enabled or policy.enrichment.provider == "claude")
    ):
        result = ClaudeEnricher(
            api_key=args.anthropic_api_key,
            model=args.model,
        ).enrich(result)

    budget = getattr(args, 'inspection_budget', None)
    if budget is not None:
        budget.check_time('report')
        result.execution['budget'] = budget.to_dict()
    markdown = MarkdownReporter().render(result, explain=args.explain)
    json_report = JsonReporter().render(result)
    if budget is not None:
        budget.consume('report_bytes', len(json.dumps(json_report, ensure_ascii=False).encode('utf-8')),
                       stage='report')
    html_report = HtmlReporter().render(
        result,
        policy_source=args.policy_source,
    )

    if args.json_output:
        _write_stdout(json.dumps(json_report, ensure_ascii=False, indent=2))
        untracked = (result.execution or {}).get('untracked_skipped') or []
        if untracked:
            # stdout의 JSON은 그대로 두고, 판정에서 빠진 파일이 있다는 사실만 사람에게 알린다.
            print(f"[drift-gate] WARNING: {len(untracked)} untracked file(s) were not evaluated "
                  "(see execution.untracked_skipped); git add them to include them.", file=sys.stderr)
    else:
        _write_stdout(markdown)
        if result.enrichment_metrics is not None and not args.json_output:
            _write_stdout("")
            prefix = "[dry-run estimate] " if getattr(args, "token_estimate", False) and not args.anthropic_api_key else ""
            _write_stdout(prefix + result.enrichment_metrics.format_report())

    if args.out_md:
        atomic_text(args.out_md, markdown)

    if args.out_json:
        atomic_json(args.out_json, json_report)

    if args.out_html:
        html_path = Path(args.out_html)
        atomic_text(html_path, html_report)
        if args.open:
            _open_file(html_path)
    elif args.open:
        print("ERROR: --open requires --out-html or the report command", file=sys.stderr)
        sys.exit(1)

    if args.record_history:
        append_result(
            result,
            args.history_path,
            source="github-pr" if args.pr else "local",
            pr_number=args.pr,
            commit_sha=_git_commit_sha(),
            changed_file_count=len(changed_files),
            runtime_seconds=runtime_seconds,
            release=os.environ.get("GITHUB_REF_NAME", ""),
        )

    sys.exit(1 if result.result == "fail" else 0)


def hashlib_sha256(raw):
    from hashlib import sha256
    return sha256(raw).hexdigest()


def RunJournalView(root, run_id):
    from drift_gate.adapters.run_store import RunJournal
    view = RunJournal(root, run_id).view()
    if view is None:
        raise CLIInputError('unknown --retry-of run')
    return view


def _publish_latest(args, controller, observation, bundle, base_result):
    """Local compare-and-set of the latest pointer; never rewrites the result."""
    from drift_gate.adapters.evidence_bundle import load_bundle
    from drift_gate.adapters.run_coordinator import result_digest
    from drift_gate.adapters.run_store import RunStoreError, TargetLedger
    ledger = TargetLedger(args.run_store, args.latest_target)
    request = {**{k: observation[k] for k in ('ticket', 'generation', 'head_oid', 'authority_sha256')},
               'run_id': args.execution['run_id'], 'receipt_sha256': bundle.to_dict()['receipt_sha256'],
               'result_sha256': result_digest(base_result)}
    controller.advance('publish-pending', publication={'state': 'publish-pending', 'kind': 'local-latest-pointer',
                                                       'target': args.latest_target},
                       publication_request={'target': args.latest_target, **request})
    try:
        # Re-admit the stored receipt instead of trusting the in-memory object.
        reloaded = load_bundle(bundle.path, expected_receipt_sha256=request['receipt_sha256'])
        completed = controller.view().semantic_completed and reloaded.receipt['status'] == 'completed'
        decision, state = ledger.publish(request, completed=completed)
    except (RunStoreError, OSError, BundleError) as exc:
        try:
            state, _ = ledger.state()
            landed = state.latest is not None and state.latest.run_id == request['run_id']
            outcome, reason = ('published', 'write-error-but-entry-present') if landed else (
                'publication-rejected', f'write-failed-entry-absent: {exc}')
        except (RunStoreError, OSError) as read_error:
            outcome, reason = 'publication-unknown', f'write-and-lookup-failed: {read_error}'
        controller.advance(outcome, publication={'state': outcome, 'reason': reason})
        return
    if decision.accepted:
        outcome = 'published'
    elif decision.reason in {'generation-changed', 'head-or-authority-changed', 'newer-or-same-result-already-latest'}:
        outcome = 'publication-stale'
    else:
        outcome = 'publication-rejected'
    controller.advance(outcome, publication={'state': outcome, 'reason': decision.reason,
                                             'latest': state.to_dict()})


def _run_runs(args):
    from drift_gate.adapters import run_store
    from drift_gate.adapters.run_coordinator import cancel_run
    exit_code = 0
    if args.operation in {'show', 'cancel', 'latest', 'reconcile'} and not args.name:
        raise CLIInputError(f'run {args.operation} requires a name')
    if args.operation == 'show':
        view = run_store.RunJournal(args.run_store, args.name).view()
        if view is None:
            raise CLIInputError('unknown run')
        data = view.to_dict()
    elif args.operation == 'list':
        runs = []
        for run_id in run_store.list_runs(args.run_store):
            try:
                view = run_store.RunJournal(args.run_store, run_id).view()
                runs.append(view.to_dict() if view else {'run_id': run_id, 'state': 'no-events-yet'})
            except (run_store.RunStoreError, OSError) as exc:
                runs.append({'run_id': run_id, 'state': 'unreadable', 'error': str(exc)})
        data = {'runs': runs}
    elif args.operation == 'reconcile':
        data = run_store.reconcile_latest(args.run_store, args.name)
        exit_code = 0 if data['state'] == 'published' else 1
    elif args.operation == 'cancel':
        decision, view = cancel_run(args.run_store, args.name, reason=args.reason)
        data = {'cancelled': decision.accepted, 'reason': decision.reason, 'run': view.to_dict()}
        exit_code = 0 if decision.accepted else 1
    elif args.operation == 'recover':
        data = {'recovered': run_store.recover(args.run_store, stale_after_seconds=args.stale_after)}
    else:
        state, _ = run_store.TargetLedger(args.run_store, args.name).state()
        data = state.to_dict()
    _write_stdout(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def _run_publication(args):
    """Look up the attempt's idempotency key; this command never posts or edits."""
    from drift_gate.adapters.github import publication
    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        raise CLIInputError('GITHUB_TOKEN is required to look up PR comments')
    try:
        record = json.loads(Path(args.record).read_text(encoding='utf-8'))
    except ValueError as exc:
        raise CLIInputError(f'invalid publication record JSON: {exc}') from exc
    if not isinstance(record, dict) or not isinstance(record.get('idempotency_key'), str) \
            or not isinstance(record.get('body_sha256'), str):
        raise CLIInputError('record has no idempotency key and body digest; nothing was attempted')
    if args.out_json and Path(args.out_json).resolve() == Path(args.record).resolve():
        raise CLIInputError('--out-json must not overwrite the original record')
    data = publication.reconcile_record(publication.CommentApi(token, args.repo), pr_number=args.pr, record=record)
    if args.out_json:
        atomic_json(args.out_json, data)
    _write_stdout(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(0 if data['state'] == 'published' else 1)


def _run_migrate(args):
    from drift_gate.adapters.git.immutable import collect_git_snapshot
    from drift_gate.adapters.migration import proof_gate_report, typed_trigger_report
    snapshot = collect_git_snapshot(root=Path.cwd(), base=args.base, head=args.head,
                                    trusted_policy_ref=args.trusted_policy_ref,
                                    trusted_policy_sha256=args.trusted_policy_sha256, policy_path=args.policy)
    data = proof_gate_report(snapshot) if args.kind == 'proof-gate' else typed_trigger_report(snapshot)
    data['subject'] = snapshot.git_evidence.subject.to_dict()
    if args.out_json:
        atomic_json(args.out_json, data)
    _write_stdout(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(0 if data.get('safe_to_switch', data.get('differences', 0) == 0) else 1)


def _run_scope(args):
    from drift_gate.adapters.scope_analysis import analyze_scope
    data = analyze_scope(root=Path.cwd(), base=args.base, head=args.head, trusted_policy_ref=args.trusted_policy_ref,
                         trusted_policy_sha256=args.trusted_policy_sha256, policy_path=args.policy,
                         isolated=args.isolated_workers, cache_dir=args.cache_dir)
    if args.out_json:
        atomic_json(args.out_json, data)
    _write_stdout(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(0 if data['complete'] else 2)


def _run_engine(args):
    from hashlib import sha256

    from drift_gate.adapters import engine_artifact as engines
    if args.operation == 'manifest':
        if not args.ref:
            raise CLIInputError('engine manifest requires --ref')
        manifest = engines.build_manifest(Path.cwd(), args.ref)
        raw = engines.manifest_bytes(manifest)
        if args.out:
            target = Path(args.out)
            if target.exists():
                raise CLIInputError('--out already exists; manifests are never overwritten')
            from drift_gate.adapters.execution import atomic_bytes
            atomic_bytes(target, raw)
        data = {'manifest_sha256': sha256(raw).hexdigest(), 'manifest': manifest}
    else:
        if not args.manifest or not args.manifest_sha256:
            raise CLIInputError('engine attest requires --manifest and --manifest-sha256')
        manifest = engines.load_manifest(args.manifest, args.manifest_sha256)
        from drift_gate.adapters.grammar_resources import get_parser
        get_parser('python')  # load the grammar the engine uses before attesting it
        data = engines.attest(manifest)
    _write_stdout(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(0 if args.operation == 'manifest' or data['loaded_code_matches_manifest'] else 2)


def _run_trusted_check(args):
    from drift_gate.adapters import engine_artifact as engines
    from drift_gate.adapters.trusted_validation import trusted_check
    manifest = engines.load_manifest(args.engine_manifest, args.engine_manifest_sha256)
    data = trusted_check(root=Path.cwd(), base=args.base, head=args.head, policy=args.policy,
                         trusted_policy_ref=args.trusted_policy_ref, trusted_policy_sha256=args.trusted_policy_sha256,
                         manifest=manifest, comparison_mode=args.comparison_mode, execution=args.execution)
    if args.out_json:
        atomic_json(args.out_json, data)
    _write_stdout(json.dumps(data, ensure_ascii=False, indent=2))
    # allow 0, block 1, review (no merge basis without a reviewed reason) 5.
    sys.exit({'allow': 0, 'block': 1, 'review': 5}[data['decision']['action']])


def _run_bundle(args):
    from drift_gate.adapters.evidence_bundle import load_bundle
    if args.engine_manifest or args.engine_manifest_sha256:
        if args.operation != 'replay' or not (args.engine_manifest and args.engine_manifest_sha256):
            raise CLIInputError('certified replay requires replay with --engine-manifest and --engine-manifest-sha256')
        from drift_gate.adapters import engine_artifact as engines
        from drift_gate.adapters.trusted_validation import certified_replay
        manifest = engines.load_manifest(args.engine_manifest, args.engine_manifest_sha256)
        data = certified_replay(args.path, root=Path(args.repo_root).resolve(), manifest=manifest,
                                expected_receipt_sha256=args.expected_receipt_sha256)
        if args.out_json:
            atomic_json(args.out_json, data)
        _write_stdout(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0 if data['certified'] else 2)
    bundle = load_bundle(args.path, expected_receipt_sha256=args.expected_receipt_sha256)
    if args.operation == 'spans':
        from drift_gate.adapters.evidence_spans import bundle_spans
        data = bundle_spans(bundle)
        if args.out_json:
            atomic_json(args.out_json, data)
        _write_stdout(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0 if data['available'] and data['verified'] == data['total'] else 2)
    if args.operation == 'verify':
        data = {'bundle': bundle.to_dict(), 'receipt': bundle.receipt,
                'validation': 'stored-bytes-and-input-binding', 'semantic_truth_certified': False}
        exit_code = 0
    else:
        result = bundle.replay(execution=args.execution)
        data = result.to_dict()
        exit_code = (1 if result.result == 'fail' else 0) if result.execution['bundle_replay']['recorded_result_matches_current'] else 2
    if args.out_json:
        atomic_json(args.out_json, data)
    _write_stdout(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def _run_demo(args) -> None:
    paths = require_fixture_paths(Path(args.fixtures))
    comparison = compare_paths(paths)

    Path(args.html_out).write_text(
        _render_demo_html(comparison),
        encoding="utf-8",
    )
    write_case_reports(comparison, Path(args.case_report_dir))

    _write_stdout(render_comparison_markdown(comparison))
    _write_stdout("")
    _write_stdout(f"Wrote HTML report: {args.html_out}")
    _write_stdout(f"Wrote raw reports: {args.case_report_dir}")
    sys.exit(1 if comparison.candidate.failed else 0)


def _run_eval(args) -> None:
    paths = require_fixture_paths(Path(args.path), recursive=args.recursive)
    report = (
        compare_engines(paths, args.engines.split(","))
        if args.engines
        else compare_paths(paths) if args.compare_baseline else evaluate_paths(paths)
    )
    output = (
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.json_output
        else (
            render_engine_comparison_markdown(report)
            if isinstance(report, EvalEngineComparison)
            else render_comparison_markdown(report)
            if args.compare_baseline
            else render_markdown(report)
        )
    )
    if isinstance(report, EvalEngineComparison) and not args.json_output:
        output = render_engine_comparison_markdown(report)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    if args.html_out:
        if not args.compare_baseline and not args.engines:
            print("ERROR: --html-out requires --compare-baseline or --engines", file=sys.stderr)
            sys.exit(2)
        Path(args.html_out).write_text(
            render_engine_comparison_html(report)
            if isinstance(report, EvalEngineComparison)
            else render_comparison_html(report),
            encoding="utf-8",
        )
    if args.case_report_dir:
        write_case_reports(report, Path(args.case_report_dir))

    _write_stdout(output)
    gate_failures = benchmark_gate_failures(
        report,
        max_fp=args.max_fp,
        max_fn=args.max_fn,
        min_f1=args.min_f1,
        min_f1_delta=args.min_f1_delta,
    )
    for failure in gate_failures:
        print(f"[drift-gate-eval] benchmark gate failed: {failure}", file=sys.stderr)

    failed = report.candidate.failed if hasattr(report, "candidate") else report.failed
    sys.exit(1 if failed or gate_failures else 0)


def _run_serve(args) -> None:
    from drift_gate.adapters.mcp.server import main as serve_main

    serve_main(["--repo", args.repo])


def _render_demo_html(comparison) -> str:
    return render_comparison_html(comparison)


def _open_file(path: Path) -> None:
    webbrowser.open(path.resolve().as_uri())


def _read_policy_source(path: str) -> str:
    policy_path = Path(path)
    if not policy_path.exists():
        return ""
    return policy_path.read_text(encoding="utf-8")


def _load_policy_optional(path: str):
    try:
        policy = load_policy(path)
        for w in policy.load_warnings:
            print(f"[drift-gate] WARNING: {w}", file=sys.stderr)
        return policy
    except Exception:
        return None


def _collect_inputs(args) -> tuple[list, list]:
    if args.pr and args.repo:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise GitInputError('GITHUB_TOKEN is required for GitHub PR mode')
        github = GitHubAdapter(token=token, repo=args.repo)
        changed_files, pr_body = github.get_pr_files_and_body(args.pr)
        from drift_gate.adapters.github.approvals import verify_ignores
        directives = parse_drift_ignores(pr_body)
        policy = args.loaded_policy
        if policy:
            from drift_gate.adapters.execution import digest
            directives = verify_ignores(github, args.pr, directives, policy, changed_files,
                                        policy_sha256=digest(args.policy_source))
            args.approval_head = getattr(github, '_snapshot_head', None)
            changed_files = github.attach_env_documents(args.pr, changed_files, policy)
        args.input_provenance = {"source": "github-pr", "repository": args.repo, "pr_number": args.pr}
        return changed_files, directives

    git = GitAdapter(args.local_root)
    files = git.get_changed_files(args.base, comparison_mode=args.comparison_mode)
    args.input_provenance = {"source": "local-git", **git.provenance}
    return files, []


def _git_commit_sha() -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


if __name__ == "__main__":
    run_cli()
