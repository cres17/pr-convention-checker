from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChangedFile:
    path: str
    status: str  # added | modified | deleted | renamed
    previous_path: Optional[str] = None
    patch: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "status": self.status,
            "previous_path": self.previous_path,
            "patch": self.patch,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChangedFile":
        return cls(
            path=d["path"],
            status=d.get("status", "modified"),
            previous_path=d.get("previous_path"),
            patch=d.get("patch", ""),
        )
