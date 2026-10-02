"""Run the existing local policy engine for a selected Git repository."""

from dataclasses import dataclass
from pathlib import Path
import subprocess
import time

from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
from drift_gate.adapters.git.client import GitAdapter
from drift_gate.adapters.policy_loader import load_policy
from drift_gate.core.engine import run
from drift_gate.core.models.result import EvaluationResult
from drift_gate.core.models.changed_file import ChangedFile


# Text documents only: opening arbitrary file types with the OS could run programs.
OPENABLE_SUFFIXES = frozenset({".md", ".rst", ".txt", ".yml", ".yaml", ".json", ".toml"})


def resolve_document(repository: Path, relative: str) -> Path:
    """Return an existing text document inside the repository, or raise ValueError."""
    if not isinstance(relative, str) or not relative or "\x00" in relative or any(c in relative for c in "*?["):
        raise ValueError("열 수 있는 파일 경로가 아닙니다.")
    raw = Path(relative)
    root = repository.resolve()
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError("저장소 안의 파일만 열 수 있습니다.")
    target = root / raw
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError("저장소 안의 파일만 열 수 있습니다.")
    if not target.is_file():
        raise ValueError(f"{relative} 파일이 아직 없습니다. 새로 만들어 주세요.")
    if target.suffix.lower() not in OPENABLE_SUFFIXES:
        raise ValueError("문서·설정 파일만 앱에서 열 수 있습니다.")
    return target


class PolicyMissingError(ValueError):
    """The repository has no .drift-gate.yml; the desktop offers to create one."""

    def __init__(self, repository: Path):
        super().__init__("저장소 루트에 .drift-gate.yml이 없습니다. 먼저 정책 파일을 준비해 주세요.")
        self.repository = repository


@dataclass(frozen=True)
class DesktopScan:
    repository: Path
    base: str
    changed_file_count: int
    result: EvaluationResult
    files: tuple[ChangedFile, ...] = ()
    policy_source: str = ""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("Git을 찾지 못했습니다. Git을 설치한 뒤 다시 실행해 주세요.") from exc


def scan_repository(path: str | Path, base: str = "HEAD") -> DesktopScan:
    """Inspect one local checkout without changing the process working directory."""
    if not str(path).strip():
        raise ValueError("검사할 Git 저장소 폴더를 선택해 주세요.")
    selected = Path(path).expanduser().resolve()
    if not selected.is_dir():
        raise ValueError("저장소 폴더를 선택해 주세요.")

    root_result = _git(selected, "rev-parse", "--show-toplevel")
    if root_result.returncode != 0:
        raise ValueError("선택한 폴더에서 Git 저장소를 찾지 못했습니다.")
    repository = Path(root_result.stdout.strip()).resolve()
    policy_path = repository / ".drift-gate.yml"
    if not policy_path.is_file():
        raise PolicyMissingError(repository)

    base = base.strip()
    if not base or base.startswith("-"):
        raise ValueError("비교 기준을 입력해 주세요. 예: HEAD 또는 main")
    valid_base = _git(repository, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}")
    if valid_base.returncode != 0:
        raise ValueError(f"비교 기준 '{base}'을(를) 이 저장소에서 찾지 못했습니다.")

    policy = load_policy(policy_path)
    started = time.perf_counter()
    changed_files = enrich_semantic_signals(GitAdapter(repository).get_changed_files(base))
    changed_count = len(changed_files)
    changed_files = attach_env_documents(
        changed_files, policy, local_document_reader(repository)
    )
    result = run(changed_files=changed_files, policy=policy)
    result.scan_metrics.runtime_seconds = time.perf_counter() - started
    return DesktopScan(repository, base, changed_count, result, tuple(changed_files),
                       policy_path.read_text(encoding="utf-8"))
