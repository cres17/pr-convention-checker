"""Static HTML report renderer for local PR review."""
import html
import json
import re

from drift_gate.core.models.result import EvaluationResult, Violation


class HtmlReporter:
    def render(self, result: EvaluationResult, *, policy_source: str = "") -> str:
        violations = "\n".join(
            self._violation_card(violation) for violation in result.violations
        )
        if not violations:
            violations = (
                '<section class="empty">'
                "<h2>No Contract Drift Found</h2>"
                "<p>All configured policy rules passed for this change set.</p>"
                "</section>"
            )

        raw_json = html.escape(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
        )
        change_types = ", ".join(result.change_types) if result.change_types else "-"
        violation_nav = self._violation_nav(result)
        walkthrough = self._walkthrough(result)
        rule_table = self._rule_table(result)
        policy_view = self._policy_source_view(policy_source)
        token_panel = self._token_efficiency_panel(result)

        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Drift Gate Report</title>
  <style>
    :root {{
      --ink: #172033;
      --muted: #5f6b7a;
      --line: #d8dee8;
      --soft: #f5f7fb;
      --panel: #ffffff;
      --good: #0f8a5f;
      --warn: #9a6700;
      --bad: #b42318;
      --accent: #2457d6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--soft);
      font: 14px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 48px; }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: flex-end;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{ margin: 0 0 4px; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 10px; font-size: 18px; }}
    h3 {{ margin: 0 0 8px; font-size: 16px; }}
    p {{ margin: 0; }}
    .muted {{ color: var(--muted); }}
    .status {{
      min-width: 88px;
      padding: 6px 10px;
      border-radius: 999px;
      color: #fff;
      text-align: center;
      font-weight: 700;
    }}
    .status-pass {{ background: var(--good); }}
    .status-warn {{ background: var(--warn); }}
    .status-fail {{ background: var(--bad); }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
      margin: 22px 0;
    }}
    .metric, .card, .empty, details {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric b {{ display: block; margin-top: 4px; font-size: 24px; }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 16px;
      align-items: start;
    }}
    .cards {{ display: grid; gap: 12px; }}
    .card header {{
      display: block;
      padding: 0;
      border: 0;
    }}
    .badge {{
      display: inline-block;
      margin-right: 6px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #eaf0ff;
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
    }}
    .notice {{
      border-left: 4px solid var(--warn);
      background: #fff8e6;
    }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
    th, td {{ padding: 8px 0; border-top: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ width: 150px; color: var(--muted); font-weight: 600; }}
    code {{
      padding: 1px 5px;
      border-radius: 4px;
      background: #edf1f7;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12px;
    }}
    ul {{ margin: 8px 0 0 18px; padding: 0; }}
    .side {{ display: grid; gap: 12px; }}
    .walkthrough ol {{ margin: 8px 0 0 20px; padding: 0; }}
    .walkthrough li {{ margin: 6px 0; }}
    .rule-status {{
      display: inline-block;
      min-width: 76px;
      padding: 2px 8px;
      border-radius: 999px;
      color: white;
      font-size: 12px;
      text-align: center;
      font-weight: 700;
    }}
    .rule-pass {{ background: var(--good); }}
    .rule-fail, .rule-rejected-ignore {{ background: var(--bad); }}
    .rule-skipped, .rule-unmatched {{ background: var(--muted); }}
    .diff-line {{ display: block; padding: 1px 6px; border-radius: 4px; }}
    .diff-add {{ background: #e8f6ef; color: #075e3d; }}
    .diff-del {{ background: #fdeceb; color: #8a1f17; }}
    .diff-hunk {{ background: #edf1f7; color: var(--muted); }}
    .diff-context {{ color: var(--muted); }}
    summary {{ cursor: pointer; font-weight: 700; }}
    pre {{
      max-height: 440px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      margin: 12px 0 0;
    }}
    .copy-btn {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin-left: 8px;
      padding: 2px 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--muted);
      font-size: 11px;
      cursor: pointer;
      vertical-align: middle;
      transition: background 0.15s, color 0.15s;
    }}
    .copy-btn:hover {{ background: var(--soft); color: var(--accent); border-color: var(--accent); }}
    .copy-btn.copied {{ background: #e8f6ef; color: var(--good); border-color: var(--good); }}
    @media (max-width: 820px) {{
      header {{ align-items: flex-start; flex-direction: column; }}
      .layout {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Drift Gate Report</h1>
      <p class="muted">Deterministic contract drift review for the current change set.</p>
    </div>
    <div class="status status-{html.escape(result.result)}">{html.escape(result.result.upper())}</div>
  </header>

  <section class="metrics">
    <div class="metric"><span>Change Types</span><b>{html.escape(change_types)}</b></div>
    <div class="metric"><span>Blockers</span><b>{result.blocker_count}</b></div>
    <div class="metric"><span>Major</span><b>{result.major_count}</b></div>
    <div class="metric"><span>Skipped Rules</span><b>{len(result.skipped_rules)}</b></div>
    <div class="metric"><span>Scanned Files</span><b>{result.scan_metrics.scanned_files}</b></div>
    <div class="metric"><span>Runtime</span><b>{result.scan_metrics.runtime_seconds:.3f}s</b></div>
  </section>

  {walkthrough}
  {self._temporal_warnings(result)}
  {rule_table}

  <section class="layout">
    <div class="cards">
      {violations}
    </div>
    <aside class="side">
      {violation_nav}
      {self._side_panel(result)}
      {token_panel}
      <details>
        <summary>Raw JSON</summary>
        <pre>{raw_json}</pre>
      </details>
      {policy_view}
    </aside>
  </section>
</main>
<script>
  function copyText(btn, text) {{
    navigator.clipboard.writeText(text).then(function() {{
      btn.textContent = '✓ Copied';
      btn.classList.add('copied');
      setTimeout(function() {{
        btn.textContent = '⧉ Copy';
        btn.classList.remove('copied');
      }}, 1800);
    }}).catch(function() {{
      btn.textContent = 'Failed';
      setTimeout(function() {{ btn.textContent = '⧉ Copy'; }}, 1500);
    }});
  }}
</script>
</body>
</html>"""

    def _violation_card(self, violation: Violation) -> str:
        anchor = self._anchor_id(violation.rule_id)
        checklist = "".join(
            f'<li>{html.escape(item)}'
            f'<button class="copy-btn" onclick="copyText(this,{html.escape(json.dumps(item))})">&#x29c9; Copy</button>'
            f"</li>"
            for item in violation.checklist
        )
        if not checklist:
            checklist = "<li>Update the required contract documentation.</li>"
        diff_snippet = self._diff_snippet(violation)
        semantic_evidence = self._semantic_evidence(violation)
        enrichment = self._enrichment(violation)

        return f"""<article class="card" id="{anchor}">
  <header>
    <span class="badge">{html.escape(violation.severity)}</span>
    <span class="badge">{html.escape(violation.change_intensity)}</span>
    <h2>{html.escape(violation.rule_id)}</h2>
    <p>{html.escape(violation.message or "Contract drift rule was not satisfied.")}</p>
  </header>
  <table>
    <tr><th>Trigger files</th><td>{self._trigger_files(violation)}</td></tr>
    <tr><th>Matched patterns</th><td>{self._trigger_patterns(violation)}</td></tr>
    <tr><th>Missing docs</th><td>{self._missing_requirements(violation)}</td></tr>
    <tr><th>Cross-file relation</th><td>{self._cross_file_relations(violation)}</td></tr>
    <tr><th>Blast radius</th><td>{self._blast_radius(violation)}</td></tr>
    <tr><th>Change type</th><td><code>{html.escape(violation.change_type)}</code></td></tr>
    <tr><th>Confidence</th><td><code>{html.escape(violation.confidence)}</code></td></tr>
  </table>
  {semantic_evidence}
  {enrichment}
  {diff_snippet}
  <h3>Suggested Fix</h3>
  <ul>{checklist}</ul>
  <h3>Override</h3>
  {self._override_block(violation)}
</article>"""

    def _violation_nav(self, result: EvaluationResult) -> str:
        if not result.violations:
            return ""
        items = "".join(
            "<li>"
            f"<a href=\"#{self._anchor_id(violation.rule_id)}\">"
            f"{html.escape(violation.rule_id)}"
            "</a>"
            f" <span class=\"muted\">{html.escape(violation.severity)}</span>"
            "</li>"
            for violation in result.violations
        )
        return f"""<nav class="card">
  <h2>Violation Navigation</h2>
  <ul>{items}</ul>
</nav>"""

    def _side_panel(self, result: EvaluationResult) -> str:
        skipped = "".join(
            f"<li><code>{html.escape(rule.rule_id)}</code>: {html.escape(rule.reason or 'no reason')}</li>"
            for rule in result.skipped_rules
        ) or "<li>None</li>"
        rejected = "".join(
            f"<li><code>{html.escape(rule.rule_id)}</code>: {html.escape(rule.reason)}</li>"
            for rule in result.rejected_ignores
        ) or "<li>None</li>"
        return f"""<section class="card">
  <h2>Rule Summary</h2>
  <p>Gate decision: <code>{html.escape(result.result)}</code></p>
  <h3>Applied Ignores</h3>
  <ul>{skipped}</ul>
  <h3>Rejected Ignores</h3>
  <ul>{rejected}</ul>
</section>"""

    def _temporal_warnings(self, result: EvaluationResult) -> str:
        if not result.temporal_warnings:
            return ""
        items = "".join(
            "<li>"
            f"<code>{html.escape(warning.rule_id)}</code> ignored "
            f"{warning.ignored_count} time(s), threshold {warning.threshold}"
            "</li>"
            for warning in result.temporal_warnings
        )
        return f"""<section class="card notice">
  <h2>Temporal Gate Warnings</h2>
  <ul>{items}</ul>
</section>"""

    def _rule_table(self, result: EvaluationResult) -> str:
        if not result.rule_decisions:
            return ""
        rows = []
        for decision in result.rule_decisions:
            status_class = "rule-" + decision.status
            link = (
                f'<a href="#{self._anchor_id(decision.rule_id)}">'
                f"{html.escape(decision.rule_id)}</a>"
                if decision.status in {"fail", "rejected-ignore"}
                else html.escape(decision.rule_id)
            )
            matched = ", ".join(decision.matched_patterns) or "-"
            rows.append(
                "<tr>"
                f"<td>{link}</td>"
                f"<td><span class=\"rule-status {status_class}\">{html.escape(decision.status)}</span></td>"
                f"<td>{html.escape(decision.severity)}</td>"
                f"<td>{html.escape(decision.reason)}</td>"
                f"<td>{html.escape(matched)}</td>"
                "</tr>"
            )
        return f"""<section class="card">
  <h2>Rule Pass/Fail</h2>
  <table>
    <thead><tr><th>Rule</th><th>Status</th><th>Severity</th><th>Reason</th><th>Matched glob</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>"""

    def _policy_source_view(self, policy_source: str) -> str:
        if not policy_source:
            policy_source = "Policy source was not provided to this report."
        return f"""<details>
  <summary>Policy Source</summary>
  <pre>{html.escape(policy_source)}</pre>
</details>"""

    def _walkthrough(self, result: EvaluationResult) -> str:
        if not result.violations:
            return """<section class="card walkthrough">
  <h2>Review Walkthrough</h2>
  <ol>
    <li>Confirm the change types are expected.</li>
    <li>Use the raw JSON panel if you need reproducible evidence.</li>
    <li>No missing contract documents were detected.</li>
  </ol>
</section>"""

        first = result.violations[0]
        missing = ", ".join(
            group.name for group in first.unsatisfied_groups if group.name
        ) or "required contract docs"
        blast = ", ".join(first.blast_radius[:3]) or "contract consumers"
        return f"""<section class="card walkthrough">
  <h2>Review Walkthrough</h2>
  <ol>
    <li>Start with <a href="#{self._anchor_id(first.rule_id)}"><code>{html.escape(first.rule_id)}</code></a>, the highest-priority triggered rule in this report.</li>
    <li>Check the matched glob and diff snippet to confirm the changed contract boundary.</li>
    <li>Review blast radius: {html.escape(blast)}.</li>
    <li>Update {html.escape(missing)} or add a justified <code>drift-ignore</code>.</li>
  </ol>
</section>"""

    def _trigger_files(self, violation: Violation) -> str:
        if not violation.trigger_files:
            return "-"
        return "<br>".join(self._format_file(file) for file in violation.trigger_files)

    def _format_file(self, file) -> str:
        current = f"<code>{html.escape(file.path)}</code> ({html.escape(file.status)})"
        if file.previous_path:
            return current + f" from <code>{html.escape(file.previous_path)}</code>"
        return current

    def _trigger_patterns(self, violation: Violation) -> str:
        if not violation.trigger_patterns:
            return "-"
        return ", ".join(
            f"<code>{html.escape(pattern)}</code>"
            for pattern in violation.trigger_patterns
        )

    def _missing_requirements(self, violation: Violation) -> str:
        if not violation.unsatisfied_groups:
            return "-"
        groups = []
        for group in violation.unsatisfied_groups:
            required = ", ".join(f"<code>{html.escape(item)}</code>" for item in group.required)
            groups.append(f"<strong>{html.escape(group.name)}</strong>: {required}")
        return "<br>".join(groups)

    def _blast_radius(self, violation: Violation) -> str:
        if not violation.blast_radius:
            return "-"
        return "<ul>" + "".join(
            f"<li>{html.escape(item)}</li>" for item in violation.blast_radius
        ) + "</ul>"

    def _cross_file_relations(self, violation: Violation) -> str:
        if not violation.cross_file_relations:
            return "-"
        return ", ".join(
            f"<code>{html.escape(name)}</code>"
            for name in violation.cross_file_relations
        )

    def _diff_snippet(self, violation: Violation) -> str:
        lines = []
        for file in violation.trigger_files:
            if not file.patch:
                continue
            for raw in file.patch.splitlines():
                if raw.startswith(("+++", "---", "diff --git", "index ")):
                    continue
                if raw.startswith(("+", "-", "@@")) or (raw.startswith(" ") and lines):
                    lines.append(raw)
                if len(lines) >= 24:
                    break
            if len(lines) >= 24:
                break
        if not lines:
            return ""
        snippet = "\n".join(self._format_diff_line(line) for line in lines)
        return f"""<details>
    <summary>Diff Snippet</summary>
    <pre>{snippet}</pre>
  </details>"""

    def _semantic_evidence(self, violation: Violation) -> str:
        items = []
        for file in violation.trigger_files:
            for signal in file.semantic_signals:
                items.append(f"{file.path}: signal {signal}")
            for evidence in file.semantic_evidence:
                items.append(f"{file.path}: {evidence}")
        if not items:
            return ""
        rendered = "".join(f"<li>{html.escape(item)}</li>" for item in sorted(set(items)))
        return f"""<details>
    <summary>Semantic Evidence</summary>
    <ul>{rendered}</ul>
  </details>"""

    def _enrichment(self, violation: Violation) -> str:
        sections = []
        if violation.changed_contract_summary:
            sections.append(f"<h3>Changed Contract Summary</h3><p>{html.escape(violation.changed_contract_summary)}</p>")
        if violation.missing_docs_explanation:
            sections.append(f"<h3>Missing Docs Explanation</h3><p>{html.escape(violation.missing_docs_explanation)}</p>")
        if violation.docs_update_draft:
            sections.append(
                "<details><summary>Docs Update Draft</summary>"
                f"<pre>{html.escape(violation.docs_update_draft)}</pre></details>"
            )
        if violation.false_positive_note:
            sections.append(f"<h3>False Positive Candidate</h3><p>{html.escape(violation.false_positive_note)}</p>")
        return "".join(sections)

    def _format_diff_line(self, line: str) -> str:
        css_class = "diff-context"
        if line.startswith("+"):
            css_class = "diff-add"
        elif line.startswith("-"):
            css_class = "diff-del"
        elif line.startswith("@@"):
            css_class = "diff-hunk"
        return f'<span class="diff-line {css_class}">{html.escape(line)}</span>'

    def _token_efficiency_panel(self, result: EvaluationResult) -> str:
        m = result.enrichment_metrics
        if m is None:
            return ""
        cost = m.estimated_cost_usd()
        return f"""<section class="card">
  <h2>Token Efficiency</h2>
  <table>
    <tr><th>Model</th><td><code>{html.escape(m.model)}</code></td></tr>
    <tr><th>Input tokens</th><td>{m.input_tokens}</td></tr>
    <tr><th>Output tokens</th><td>{m.output_tokens}</td></tr>
    <tr><th>Cache write tokens</th><td>{m.cache_creation_input_tokens}</td></tr>
    <tr><th>Cache read tokens</th><td>{m.cache_read_input_tokens}</td></tr>
    <tr><th>Saved tokens</th><td>{m.saved_input_tokens} ({m.estimated_savings_pct}%)</td></tr>
    <tr><th>Estimated cost</th><td>${cost['total_usd']:.6f} USD (saved ${cost['saved_usd']:.6f})</td></tr>
  </table>
</section>"""

    def _override_block(self, violation: Violation) -> str:
        snippet = f"drift-ignore: {violation.rule_id}\nreason: <explain why>"
        escaped = html.escape(snippet)
        js_snippet = html.escape(json.dumps(snippet))
        return (
            f'<p class="muted">Only if intentional, add the following to your PR description:'
            f'<button class="copy-btn" onclick="copyText(this,{js_snippet})">&#x29c9; Copy</button>'
            f'</p>'
            f"<pre>{escaped}</pre>"
        )

    def _anchor_id(self, rule_id: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", rule_id).strip("-")
        return f"rule-{slug or 'violation'}"
