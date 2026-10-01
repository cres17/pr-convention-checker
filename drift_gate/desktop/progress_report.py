"""Markdown rendering of a project-progress report (no I/O)."""

from __future__ import annotations

STATUS_LABELS = {
    "implemented": "구현 확인",
    "partial": "부분 구현",
    "not_implemented": "미구현 확인",
    "unknown": "근거 없음·재확인",
    "excluded": "제외",
}
_MAX_CELL = 160


def _cell(value: object) -> str:
    text = " ".join(str(value if value is not None else "").split())
    if len(text) > _MAX_CELL:
        text = text[: _MAX_CELL - 1] + "…"
    return text.replace("|", "\\|") or "—"


def _status(item: dict, stale_documents: list[str]) -> str:
    if not item.get("included", True) or item.get("effective_status") == "excluded":
        return STATUS_LABELS["excluded"]
    if item.get("stale_evidence") or stale_documents:
        return "재확인 필요"
    status = item.get("effective_status") or item["implementation_status"]
    label = "근거 없음" if status == "unknown" else STATUS_LABELS.get(status, "근거 없음")
    return label


_CHANGE_LABELS = (
    ("gained", "새로 구현 확인"),
    ("regressed", "회귀(구현 확인 → 아님)"),
    ("excluded", "범위에서 제외"),
    ("reincluded", "다시 포함"),
    ("added", "추가"),
    ("removed", "삭제"),
)


def change_text(counts: dict) -> str:
    """One line such as "새로 구현 확인 2 · 회귀(구현 확인 → 아님) 1"; empty when nothing changed."""
    return " · ".join(f"{label} {counts[key]}" for key, label in _CHANGE_LABELS if counts.get(key))


def render_markdown(report: dict, project: dict | None = None, history: dict | None = None) -> str:
    """Team-shareable summary. Only states what the saved baseline and evidence support."""
    project = project or {}
    counts = report["counts"]
    total = report["total"]
    stale_docs = report.get("stale_documents", [])
    name = project.get("name") or report["repository"].rstrip("/\\").split("/")[-1].split("\\")[-1]
    meta = [
        ("저장소", name),
        ("브랜치", project.get("branch")),
        ("프로젝트 버전", project.get("version")),
        ("코드 위치(HEAD)", (report.get("head") or "")[:12] or None),
        ("기준 버전", f"v{report['version']}"),
        ("분석 시각", report["at"]),
    ]
    lines = [f"# 프로젝트 현황 — {name}", ""]
    lines += [f"- {label}: {value}" for label, value in meta if value]
    lines += ["", "## 요약", "", "| 구분 | 개수 |", "|---|---|"]
    lines.append(f"| 완료 확인(구현 확인 + 수동 검증) | {counts['complete']} / {total} |")
    for key in ("implemented", "partial", "not_implemented", "unknown"):
        lines.append(f"| {STATUS_LABELS[key]} | {counts[key]} / {total} |")
    lines.append(f"| 제외 | {counts['excluded']} |")
    kinds = report.get("document_kinds", {})
    labels = {"current": "현재 목표", "future": "향후 계획", "past": "과거 결과", "reference": "참고"}
    if kinds:
        lines += ["", "## 문서 범위", "", "현재 목표의 포함 항목만 현황에 집계합니다.", "", "| 문서 | 종류 |", "|---|---|"]
        lines += [f"| {_cell(path)} | {labels[kind]} |" for path, kind in kinds.items()]
    if report.get("stale_context_documents"):
        lines += ["", "> 참고 범위 문서 변경: " + ", ".join(_cell(d) for d in report["stale_context_documents"]) + ". 현재 목표의 집계에는 영향을 주지 않습니다."]
    if stale_docs:
        lines += ["", "> 기준 문서가 변경됐습니다: " + ", ".join(f"`{d}`" for d in stale_docs)
                  + ". 기능 후보를 다시 추출해 확정하기 전까지 이전 확인은 집계에서 제외했습니다."]
    unbacked = report.get("doc_claims_unbacked", 0)
    if unbacked:
        lines += ["", f"> 문서에는 완료로 표시됐지만 코드 근거가 확인되지 않은 항목이 {unbacked}개 있습니다."]
    since = (history or {}).get("since_save")
    snapshots = (history or {}).get("snapshots") or []
    if since:
        text = change_text(since["counts"])
        lines += ["", f"> 마지막 저장(기준 v{since['version']}) 이후 변화: {text or '완료 확인 수만 변경'}"]
    if snapshots:
        lines += ["", "## 진행 이력", "", "| 기준 | 저장 시각 | 완료 확인 | 구현 확인 | 지난 저장 대비 |", "|---|---|---|---|---|"]
        for row in snapshots[:10]:
            counts = row["counts"]
            lines.append(
                f"| v{row['version']} | {_cell(row['at'])} | {counts.get('complete', 0)} / {row['total']} "
                f"| {counts.get('implemented', 0)} | {_cell(change_text(row.get('changes') or {}) if row.get('changes') else '첫 기록')} |"
            )
    lines += ["", "## 기능별 현황", "",
              "| 기능 | 상태 | 검증 | 코드 근거 | 문서 출처 | 비고 |", "|---|---|---|---|---|---|"]
    for item in report["items"]:
        evidence = item.get("evidence")
        source = item["source"]
        notes = []
        if item.get("doc_claim") == "unbacked":
            notes.append("문서는 완료 표시, 근거 없음")
        if item.get("duplicates"):
            notes.append(f"다른 문서 {len(item['duplicates'])}곳에도 있음")
        lines.append("| " + " | ".join([
            _cell(item["title"]),
            _status(item, stale_docs),
            "수동 확인" if item.get("verification_status") == "verified" else "미검증",
            _cell(f"{evidence['path']}:{evidence['line']}") if evidence else "—",
            _cell(f"{source['path']}:{source['line']}" if source.get("line") else source["path"]),
            _cell(", ".join(notes)),
        ]) + " |")
    lines += ["", "---", "", report.get("limitations", ""), ""]
    return "\n".join(lines)
