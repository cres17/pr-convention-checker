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
        )
