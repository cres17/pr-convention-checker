"""
Local git adapter — git diff로 변경 파일 수집.
core에서 사용 금지.
"""
import subprocess
from typing import List

from drift_gate.core.models.changed_file import ChangedFile

STATUS_MAP = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
}


class GitAdapter:
    def get_changed_files(self, base: str = "HEAD~1") -> List[ChangedFile]:
        """
        git diff --name-status <base>...HEAD 결과를 ChangedFile 목록으로 반환.
        """
        try:
            output = subprocess.check_output(
                ["git", "diff", "--name-status", f"{base}...HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            try:
                output = subprocess.check_output(
                    ["git", "diff", "--name-status", "HEAD~1"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError:
                return []

        return list(_parse_name_status(output))


def _parse_name_status(output: str) -> List[ChangedFile]:
    files = []
    for line in output.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        if parts[0].startswith("R") and len(parts) >= 3:
            files.append(ChangedFile(
                path=parts[2],
                status="renamed",
                previous_path=parts[1],
            ))
        elif len(parts) >= 2:
            files.append(ChangedFile(
                path=parts[1],
                status=STATUS_MAP.get(parts[0], "modified"),
            ))
    return files
