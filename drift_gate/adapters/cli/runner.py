"""
CLI adapter — argparse 기반 진입점.
core를 호출하고 reporter로 출력.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.result import DriftIgnoreDirective
from drift_gate.adapters.git.client import GitAdapter
from drift_gate.adapters.github.client import GitHubAdapter, parse_drift_ignores
from drift_gate.reporters.markdown import MarkdownReporter
from drift_gate.reporters.json_reporter import JsonReporter


def run_cli(argv=None):
    parser = argparse.ArgumentParser(
        prog="drift-gate",
        description="Spec/Contract Drift Gate — 계약 문서 동기화 검사",
    )
    parser.add_argument("--policy", default=".drift-gate.yml", help="정책 파일 경로")
    parser.add_argument("--pr", type=int, help="GitHub PR 번호")
    parser.add_argument("--repo", help="owner/repo 형식")
    parser.add_argument("--base", default="HEAD~1", help="git diff base (로컬 모드)")
    parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    parser.add_argument("--out-md", help="Markdown 리포트 저장 경로")
    parser.add_argument("--out-json", help="JSON 리포트 저장 경로")
    args = parser.parse_args(argv)

    # 변경 파일 수집
    drift_ignores: list = []
    if args.pr and args.repo:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            print("ERROR: GITHUB_TOKEN 환경변수 필요", file=sys.stderr)
            sys.exit(1)
        gh = GitHubAdapter(token=token, repo=args.repo)
        changed_files, pr_body = gh.get_pr_files_and_body(args.pr)
        drift_ignores = parse_drift_ignores(pr_body)
    else:
        git = GitAdapter()
        changed_files = git.get_changed_files(args.base)

    # Core 실행
    result = run(
        changed_files=changed_files,
        drift_ignores=drift_ignores,
        policy_path=args.policy,
    )

    # 출력
    if args.json_output:
        output = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
        print(output)
    else:
        reporter = MarkdownReporter()
        print(reporter.render(result))

    if args.out_md:
        reporter = MarkdownReporter()
        Path(args.out_md).write_text(reporter.render(result), encoding="utf-8")

    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # Exit code
    sys.exit(1 if result.result == "fail" else 0)
