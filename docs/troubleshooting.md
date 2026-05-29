# Troubleshooting

Common issues and resolutions when using Drift Gate.

---

## "My rule never triggers"

**Symptom**: A rule exists in `.drift-gate.yml` but no violation is reported even when you expect one.

**Checklist**:

1. **Check glob patterns.** Glob matching uses `**` to span directory separators. Make sure the pattern matches the actual file path.
   - Wrong: `routes/*.ts` (only matches files directly in `routes/`)
   - Right: `routes/**/*.ts` or `src/routes/**`

2. **Check `ignore_paths`.** If the changed file path matches an `ignore_paths` entry, it is excluded from both trigger (`when`) and requirement (`require`) evaluation.
   ```yaml
   ignore_paths:
     - "src/internal/**"  # files here are invisible to all rules
   ```

3. **Check `min_change_intensity`.** If the rule has a `min_change_intensity` threshold, the file must contain meaningful changes at that level. A file that only has comment changes will not reach `signature-change` intensity.

4. **Run `drift-gate doctor`** to validate your policy file and check for dead rules.

5. **Run `drift-gate check --explain`** to see which files were classified, what signals were extracted, and why each rule matched or did not match.

---

## "Too many false positives"

**Symptom**: Rules fire on PRs that should not require documentation updates (e.g., test-only changes, comment edits, internal refactors).

**Solutions**:

1. **Add `min_change_intensity`** to the rule's `when:` clause. This prevents the rule from firing on trivial changes.
   ```yaml
   when:
     any_changed: ["src/routes/**"]
     min_change_intensity: route-contract-change
   ```

2. **Narrow `ignore_paths`** to exclude test directories, internal modules, or generated code.
   ```yaml
   ignore_paths:
     - "src/**/__tests__/**"
     - "src/**/*.spec.ts"
     - "src/internal/**"
   ```

3. **Verify `docs-only` / `test-only` behavior.** If all files in a PR are documentation or tests, Drift Gate skips evaluation entirely. If a single non-doc file is present, this optimization does not apply.

4. **Run the benchmark** to measure false positive count across your fixture set:
   ```
   drift-gate eval --compare-baseline
   ```

---

## "drift-ignore not working"

**Symptom**: You added `drift-ignore: rule-id` in the PR description but the violation is still reported.

**Reason**: For `BLOCKER` and `MAJOR` severity violations, a `reason:` line is required on the line immediately following `drift-ignore:`. Without it, the ignore is rejected and the violation is preserved.

**Correct format**:
```
drift-ignore: api-contract-sync
reason: Hotfix — spec PR #456 is already open and will merge before release
```

**Incorrect format** (will be rejected for BLOCKER/MAJOR):
```
drift-ignore: api-contract-sync
```

For `MINOR` and `NIT` severity, a reason is not required. The ignore is applied regardless.

Rejected ignores appear in the report under `rejected_ignores` and are shown in the PR comment.

---

## "Policy file not found"

**Symptom**: Drift Gate fails with an error like `Policy file not found: .drift-gate.yml`.

**In GitHub Actions**:
- The policy file path is resolved relative to `$GITHUB_WORKSPACE`, which is the root of the checked-out repository.
- Make sure `.drift-gate.yml` is committed at the repo root, or set the `policy_file` input in your `action.yml` step to the correct path.
- Check that the `actions/checkout` step runs _before_ the Drift Gate step.

**Locally**:
- Run `drift-gate doctor` to check whether the policy file is detected.
- Ensure you are running the command from the project root, or pass `--policy` with an explicit path.

---

## "Claude enrichment failing"

**Symptom**: The report does not include enhanced checklist items or contract summaries even though `ANTHROPIC_API_KEY` is set.

**Diagnosis**:

1. **API key missing or invalid.** Check that `ANTHROPIC_API_KEY` is set and is a valid key starting with `sk-ant-...`.
2. **Model not available.** The default model is `claude-opus-4-6`. If the key does not have access, set the `MODEL` environment variable to a model your key supports.
3. **Network error in Actions.** Network access to `api.anthropic.com` may be restricted in some enterprise environments.

**Behavior when enrichment fails**: Drift Gate falls back to the deterministic checklist. All gate decisions (pass/warn/fail) are unaffected. Only the checklist quality degrades.

Check the Actions log for a message like:
```
[drift-gate] WARNING: Claude API failed, using fallback checklist (...)
```

---

## "Fork PR not posting comment"

**Symptom**: Drift Gate runs on a fork PR but no comment appears on the pull request.

**Expected behavior**: This is by design. When Drift Gate detects a fork PR (where the PR head repo differs from the base repo), it disables PR comment posting and Claude enrichment. This prevents the `GITHUB_TOKEN` (which has write access to the base repo) from being used in code that runs in the fork's context.

The gate decision and all report artifacts are still produced. The report is available as a GitHub Actions artifact.

---

## "HTML report not opening"

**Symptom**: `drift-gate report --html` generates a file but `--open` does not launch the browser.

**Solutions**:

1. **Use `--open` flag explicitly**:
   ```
   drift-gate report --html --open
   ```

2. **Browser availability.** The `--open` option calls `webbrowser.open()` from the Python standard library. On headless servers or minimal Docker containers, no browser is available. Open the HTML file manually.

3. **Check the output path.** By default the file is written to `drift_gate_report.html` in the current directory. Pass `--out-html <path>` to specify a custom location.

---

## Doctor Command Usage

`drift-gate doctor` performs a comprehensive environment check:

```
drift-gate doctor
```

It checks:
- `.drift-gate.yml` exists and is valid
- Policy rules are well-formed and non-dead (each rule matches at least one fixture)
- `ignore_paths` does not accidentally exclude `require.groups` paths
- Glob patterns are not dangerously broad (e.g., `**` alone)
- Git repository is present and base branch exists
- GitHub Actions configuration, if present
- Benchmark fixtures exist
- Package entrypoints are importable

Run `doctor` when a rule unexpectedly does not trigger, when upgrading the policy schema, or before onboarding a new team member.
