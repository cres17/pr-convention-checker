"""self-audit 명령: 체크리스트와 변경 파일을 대조해 Markdown·HTML·JSON으로 보고한다."""
import json
import sys

from drift_gate.adapters.cli.output import write_stdout as _write_stdout
from drift_gate.adapters.git.client import GitAdapter, GitInputError


def _run_self_audit(args) -> None:
    from pathlib import Path as _Path

    from drift_gate.adapters.docs.checklist import parse_checklist
    from drift_gate.core.self_audit.matcher import DiffEvidence, match_checklist

    checklist_path = _Path(args.checklist)
    if not checklist_path.exists():
        raise GitInputError(f'checklist file not found: {checklist_path}')

    items = parse_checklist(checklist_path)

    # Collect git diff evidence
    changed_files_objs = GitAdapter().get_changed_files(args.base, comparison_mode=args.comparison_mode)
    changed_file_paths = [f.path for f in changed_files_objs]
    patch_text = "\n".join(f.patch for f in changed_files_objs)

    evidence = DiffEvidence.from_raw(
        changed_files=changed_file_paths,
        patch_text=patch_text,
    )
    audit_result = match_checklist(items, evidence)

    output_dict = audit_result.to_dict()

    if args.json_output or args.out:
        json_str = json.dumps(output_dict, ensure_ascii=False, indent=2)
        if args.out:
            _Path(args.out).write_text(json_str, encoding="utf-8")
        if args.json_output:
            _write_stdout(json_str)
        else:
            _write_stdout(_format_self_audit_markdown(audit_result))
    else:
        _write_stdout(_format_self_audit_markdown(audit_result))

    if getattr(args, "out_html", None):
        _Path(args.out_html).write_text(
            _render_self_audit_html(audit_result), encoding="utf-8"
        )

    warnings = audit_result.warnings
    mismatch_count = sum(1 for w in warnings if w.kind == "checklist-code-mismatch")
    missing_count = sum(1 for w in warnings if w.kind == "missing-progress-entry")
    supported = sum(1 for i in audit_result.checklist_items if i.status == "related-evidence-found")
    checked = sum(1 for i in audit_result.checklist_items if i.checked)

    if not args.json_output:
        _write_stdout("")
        _write_stdout(
            f"Self-audit: {supported}/{checked} checked items with related diff references (behavior not verified)"
        )
        if warnings:
            _write_stdout(
                f"Warnings: {mismatch_count} checklist-code-mismatch, "
                f"{missing_count} missing-progress-entry"
            )

    sys.exit(0)


def _format_self_audit_markdown(audit_result) -> str:
    lines = ["# Self-Audit Report", ""]
    supported = [i for i in audit_result.checklist_items if i.status == "related-evidence-found"]
    unsupported = [i for i in audit_result.checklist_items if i.status == "no-related-evidence"]
    unchecked = [i for i in audit_result.checklist_items if i.status == "unchecked"]

    lines.append(
        f"**{len(supported)} with related evidence** / **{len(supported)+len(unsupported)} checked** "
        f"/ {len(unchecked)} unchecked"
    )
    lines.append("")

    if unsupported:
        lines.append("## Unsupported Checked Items")
        lines.append("")
        for item in unsupported:
            lines.append(f"- [x] {item.text} *(line {item.line_number})*")
        lines.append("")

    if audit_result.warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in audit_result.warnings:
            lines.append(f"- **{w.kind}**: {w.message}")
            if w.details:
                lines.append(f"  - {w.details}")
        lines.append("")

    return "\n".join(lines)


def _render_self_audit_html(audit_result) -> str:
    import html as _html
    supported = [i for i in audit_result.checklist_items if i.status == "related-evidence-found"]
    unsupported = [i for i in audit_result.checklist_items if i.status == "no-related-evidence"]
    unchecked = [i for i in audit_result.checklist_items if i.status == "unchecked"]

    def _item_rows(items, badge_class, badge_label):
        if not items:
            return "<tr><td colspan='3'><em>None</em></td></tr>"
        rows = ""
        for item in items:
            ev = ", ".join(_html.escape(e) for e in item.evidence) or "—"
            rows += (
                f"<tr>"
                f"<td><span class='badge {badge_class}'>{badge_label}</span></td>"
                f"<td>{_html.escape(item.text)}</td>"
                f"<td class='ev'>{ev}</td>"
                f"</tr>"
            )
        return rows

    warnings_html = ""
    if audit_result.warnings:
        wrows = "".join(
            f"<tr><td><code>{_html.escape(w.kind)}</code></td>"
            f"<td>{_html.escape(w.message)}</td>"
            f"<td>{_html.escape(w.details)}</td></tr>"
            for w in audit_result.warnings
        )
        warnings_html = f"""
  <div class="card">
    <h2 style="margin-top:0">Warnings ({len(audit_result.warnings)})</h2>
    <table>
      <thead><tr><th>Kind</th><th>Message</th><th>Details</th></tr></thead>
      <tbody>{wrows}</tbody>
    </table>
  </div>"""

    all_rows = (
        _item_rows(supported, "green", "related reference")
        + _item_rows(unsupported, "red", "unsupported")
        + _item_rows(unchecked, "gray", "unchecked")
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Drift Gate — Self-Audit Report</title>
  <style>
    body {{ font: 14px/1.5 system-ui, sans-serif; margin: 32px; background: #f8fafc; color: #172033; }}
    h1 {{ margin-bottom: 4px; }}
    .card {{ background: #fff; border: 1px solid #d8dee8; border-radius: 8px; padding: 24px; margin-bottom: 24px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #d8dee8; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f5f7fb; font-weight: 600; }}
    .badge {{ display: inline-block; border-radius: 4px; padding: 1px 7px; font-size: 12px; font-weight: 600; }}
    .green {{ background: #c6f6d5; color: #276749; }}
    .red {{ background: #fed7d7; color: #9b2c2c; }}
    .gray {{ background: #e2e8f0; color: #4a5568; }}
    .ev {{ font-size: 12px; color: #555; word-break: break-all; }}
    .summary {{ font-size: 1.1em; margin-bottom: 8px; }}
  </style>
</head>
<body>
  <h1>Drift Gate — Self-Audit Report</h1>
  <div class="card">
    <p class="summary">
      <strong>{len(supported)}</strong> related references &nbsp;/&nbsp;
      <strong>{len(supported) + len(unsupported)}</strong> checked &nbsp;/&nbsp;
      {len(unchecked)} unchecked
    </p>
    <table>
      <thead><tr><th>Status</th><th>Item</th><th>Evidence</th></tr></thead>
      <tbody>{all_rows}</tbody>
    </table>
  </div>
  {warnings_html}
</body>
</html>"""
