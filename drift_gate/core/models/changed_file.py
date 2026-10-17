from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ChangedFile:
    path: str
    status: str  # added | modified | deleted | renamed
    previous_path: Optional[str] = None
    patch: str = ""
    semantic_signals: List[str] = field(default_factory=list)
    semantic_evidence: List[str] = field(default_factory=list)
    analysis_method: str = "not-analyzed"
    analysis_reason: str = ""
    # Only key names are retained from document content, never values.
    documented_env_keys: Optional[List[str]] = None
    document_input_state: str = ""  # available | missing | unavailable (adapter evidence)
    # Bounded adapter snapshots; never serialized into reports or history.
    before_source: Optional[str] = field(default=None, repr=False)
    after_source: Optional[str] = field(default=None, repr=False)
    # Adapter-normalized YAML; original text remains in after_source so the
    # execution receipt binds both the raw input and its normalized meaning.
    document_json: Optional[str] = field(default=None, repr=False)
    document_error: str = ""
    before_routes: Optional[List[tuple[str, str]]] = field(default=None, repr=False)
    after_routes: Optional[List[tuple[str, str]]] = field(default=None, repr=False)
    route_analysis_error: str = ""
    # Sample documents only: where removed-key candidates still occur in the repository after
    # the change ({key: {"code"|"config"|"mention": [paths]}}). Key names and paths, never values.
    env_key_references: Optional[dict] = None
    env_reference_scan: str = ""  # "" not requested | complete | unavailable: <reason>

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "status": self.status,
            "previous_path": self.previous_path,
            "patch": self.patch,
            "semantic_signals": self.semantic_signals,
            "semantic_evidence": self.semantic_evidence,
            "analysis_method": self.analysis_method,
            "analysis_reason": self.analysis_reason,
            "documented_env_keys": self.documented_env_keys,
            "document_input_state": self.document_input_state,
            **({"document_error": self.document_error} if self.document_error else {}),
            **({"route_analysis_error": self.route_analysis_error} if self.route_analysis_error else {}),
            **({"env_key_references": self.env_key_references} if self.env_key_references is not None else {}),
            **({"env_reference_scan": self.env_reference_scan} if self.env_reference_scan else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChangedFile":
        return cls(
            path=d["path"],
            status=d.get("status", "modified"),
            previous_path=d.get("previous_path"),
            patch=d.get("patch", ""),
            semantic_signals=d.get("semantic_signals", []),
            semantic_evidence=d.get("semantic_evidence", []),
            documented_env_keys=d.get("documented_env_keys"),
            document_input_state=d.get("document_input_state", ""),
            env_key_references=d.get("env_key_references"),
            env_reference_scan=d.get("env_reference_scan", ""),
        )
