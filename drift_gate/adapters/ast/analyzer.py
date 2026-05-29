"""Optional semantic signal extraction from patches.

This is a lightweight adapter boundary for future Tree-sitter parsers. Today it
uses conservative patch patterns and only adds signals the core already knows
how to handle.

Language-specific logic is delegated to dedicated adapter classes:
- TypeScript/JavaScript: drift_gate.adapters.ast.typescript_adapter.TypeScriptAdapter
- Python: drift_gate.adapters.ast.python_adapter.PythonAdapter
- Go: drift_gate.adapters.ast.go_adapter.GoAdapter
- Java/Kotlin: drift_gate.adapters.ast.java_kotlin_adapter.JavaKotlinAdapter
- Ruby: drift_gate.adapters.ast.ruby_adapter.RubyAdapter
"""
import re
from typing import Iterable

from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.adapters.ast import TREE_SITTER_AVAILABLE
from drift_gate.adapters.ast.typescript_adapter import TypeScriptAdapter
from drift_gate.adapters.ast.python_adapter import PythonAdapter
from drift_gate.adapters.ast.go_adapter import GoAdapter
from drift_gate.adapters.ast.java_kotlin_adapter import JavaKotlinAdapter
from drift_gate.adapters.ast.ruby_adapter import RubyAdapter

if TREE_SITTER_AVAILABLE:
    from drift_gate.adapters.ast.tree_sitter_python_adapter import TreeSitterPythonAdapter
    from drift_gate.adapters.ast.tree_sitter_typescript_adapter import TreeSitterTypeScriptAdapter

# Module-level compiled patterns for path-wide signals.
TS_ROUTE = re.compile(r"\b(router|app)\.(get|post|put|patch|delete)\s*\(")
PY_ROUTE = re.compile(r"@\w+\.(get|post|put|patch|delete)\s*\(")
API_SCHEMA = re.compile(r"\b(z\.object|response_model|requestBody|responses|parameters|operationId)\b")
OPENAPI_OPERATION = re.compile(r"^\s*(operationId|parameters|requestBody|responses)\s*:", re.IGNORECASE)
CLASS_TYPE = re.compile(r"^\s*(export\s+)?(class|interface|type|enum|data\s+class|sealed\s+class)\s+\w+")
DB_MODEL = re.compile(r"^\s*(model|table|class)\s+\w+|(@Column|@Entity|models\.|db\.Column)")
PUBLIC_EXPORT = re.compile(
    r"^\s*export\s+(default\s+)?(async\s+)?"
    r"(function|class|const|let|var|type|interface|enum)\b"
)
PY_SIGNATURE = re.compile(r"^\s*def\s+\w+\s*\(")
PY_CLI = re.compile(r"\b(add_argument|add_parser)\s*\(")
TS_CLI = re.compile(r"\b(program|commander)\.(command|option)\s*\(")
CLICK_CLI = re.compile(r"\b@click\.(command|option|argument)\s*\(")
CONFIG_SCHEMA = re.compile(r"\b(BaseSettings|SettingsConfigDict|envSchema|configSchema|env_prefix)\b")

_ts_adapter = TreeSitterTypeScriptAdapter() if TREE_SITTER_AVAILABLE else TypeScriptAdapter()
_py_adapter = TreeSitterPythonAdapter() if TREE_SITTER_AVAILABLE else PythonAdapter()
_go_adapter = GoAdapter()
_java_kotlin_adapter = JavaKotlinAdapter()
_ruby_adapter = RubyAdapter()


def enrich_semantic_signals(files: Iterable[ChangedFile]) -> list[ChangedFile]:
    enriched = []
    for file in files:
        signals = set(file.semantic_signals)
        evidence = set(file.semantic_evidence)
        suffix = _suffix(file.path)
        added_lines = list(_added_lines(file.patch))
        if suffix in {".ts", ".tsx", ".js", ".jsx"}:
            _merge(signals, evidence, _typescript_signals(added_lines))
        elif suffix == ".py":
            _merge(signals, evidence, _python_signals(added_lines))
        elif suffix == ".go":
            _merge(signals, evidence, _go_signals(added_lines))
        elif suffix in {".java", ".kt", ".kts"}:
            language = "java" if suffix == ".java" else "kotlin"
            _merge(signals, evidence, _java_kotlin_signals(added_lines, language))
        elif suffix == ".rb":
            _merge(signals, evidence, _ruby_signals(added_lines))
        _merge(signals, evidence, _path_signals(file.path, added_lines))
        enriched.append(
            ChangedFile(
                path=file.path,
                status=file.status,
                previous_path=file.previous_path,
                patch=file.patch,
                semantic_signals=sorted(signals),
                semantic_evidence=sorted(evidence),
            )
        )
    return enriched


def _typescript_signals(lines: list[str]) -> tuple[set[str], set[str]]:
    """Delegate to TypeScriptAdapter for TS/JS signal extraction."""
    return _ts_adapter.extract_signals(lines)


def _python_signals(lines: list[str]) -> tuple[set[str], set[str]]:
    """Delegate to PythonAdapter for Python signal extraction."""
    return _py_adapter.extract_signals(lines)


def _go_signals(lines: list[str]) -> tuple[set[str], set[str]]:
    return _go_adapter.extract_signals(lines)


def _java_kotlin_signals(lines: list[str], language: str) -> tuple[set[str], set[str]]:
    return _java_kotlin_adapter.extract_signals(lines, language=language)


def _ruby_signals(lines: list[str]) -> tuple[set[str], set[str]]:
    return _ruby_adapter.extract_signals(lines)


def _path_signals(path: str, lines: list[str]) -> tuple[set[str], set[str]]:
    lowered = path.lower().replace("\\", "/")
    if lowered in {"pyproject.toml", "package.json"} and any(
        "scripts" in line or "entry_points" in line or "project.scripts" in line
        for line in lines
    ):
        return {"public-cli-change"}, {"package entrypoint or script changed"}
    if any(CONFIG_SCHEMA.search(line) for line in lines):
        return {"env-key-added"}, {"config schema or env settings model changed"}
    if any(part in lowered for part in ("sdk/", "client/", "clients/")) and any(
        PUBLIC_EXPORT.search(line) or PY_SIGNATURE.search(line)
        for line in lines
    ):
        return {"route-contract-change"}, {"SDK/client public contract changed"}
    if any(part in lowered for part in ("openapi", "swagger")) and any(
        OPENAPI_OPERATION.search(line) for line in lines
    ):
        return {"openapi-operation-changed"}, {"OpenAPI operation changed"}
    if any(part in lowered for part in ("prisma/", "models", "schema")) and any(
        DB_MODEL.search(line) for line in lines
    ):
        return {"db-model-schema-changed"}, {"DB model/schema declaration changed"}
    return set(), set()


def _merge(
    signals: set[str],
    evidence: set[str],
    update: tuple[set[str], set[str]],
) -> None:
    new_signals, new_evidence = update
    signals.update(new_signals)
    evidence.update(new_evidence)


def _added_lines(patch: str) -> Iterable[str]:
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            yield line[1:]


def _suffix(path: str) -> str:
    lowered = path.lower()
    for suffix in (".tsx", ".ts", ".jsx", ".js", ".py", ".go", ".java", ".kt", ".kts", ".rb"):
        if lowered.endswith(suffix):
            return suffix
    return ""
