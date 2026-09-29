from drift_gate.desktop.progress_report import render_markdown


def report(**over):
    item = {
        "id": "a", "title": "로그인 | 화면", "criterion": "x", "included": True,
        "source": {"path": "README.md", "line": 2, "excerpt": "", "sha256": "h"},
        "implementation_status": "implemented", "effective_status": "implemented",
        "evidence": {"path": "src/login.py", "line": 1, "note": "n"},
        "verification_status": "verified", "verification_note": "ok", "stale_evidence": False,
    }
    base = {
        "repository": "/work/shop", "version": 3, "at": "2026-09-29T00:00:00Z", "head": "abcdef1234567890",
        "stale_documents": [], "total": 2, "limitations": "수동 기준입니다.",
        "counts": {"implemented": 1, "partial": 0, "not_implemented": 0, "unknown": 1, "complete": 1, "excluded": 1},
        "items": [item,
                  {**item, "id": "b", "title": "가입", "implementation_status": "unknown",
                   "effective_status": "unknown", "evidence": None, "verification_status": "unverified",
                   "doc_claim": "unbacked", "duplicates": [{"path": "b.md", "line": 1}]},
                  {**item, "id": "c", "title": "제외 항목", "included": False, "effective_status": "excluded"}],
        "doc_claims_unbacked": 1,
    }
    base.update(over)
    return base


def test_markdown_summarizes_counts_items_and_discrepancies():
    text = render_markdown(report(), {"name": "shop", "branch": "ver2", "version": "v1.0.0"})
    assert text.startswith("# 프로젝트 현황 — shop")
    assert "- 브랜치: ver2" in text and "- 코드 위치(HEAD): abcdef123456" in text
    assert "| 완료 확인(구현 확인 + 수동 검증) | 1 / 2 |" in text
    assert "| 로그인 \\| 화면 | 구현 확인 | 수동 확인 | src/login.py:1 | README.md:2 | — |" in text
    assert "문서는 완료 표시, 근거 없음, 다른 문서 1곳에도 있음" in text
    assert "| 제외 항목 | 제외 |" in text
    assert "문서에는 완료로 표시됐지만 코드 근거가 확인되지 않은 항목이 1개" in text
    assert text.rstrip().endswith("수동 기준입니다.")


def test_stale_documents_and_evidence_are_marked_for_recheck():
    stale = report(stale_documents=["README.md"])
    text = render_markdown(stale)
    assert "기준 문서가 변경됐습니다: `README.md`" in text
    assert text.count("재확인 필요") == 2  # both included items
    assert "- 저장소: shop" in text  # name falls back to the folder
