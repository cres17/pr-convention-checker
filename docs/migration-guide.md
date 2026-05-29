# Migration Guide

This guide covers upgrading from earlier Drift Gate configurations to the current version.

---

## From v0.x (path-only) to current (semantic signals + intensity)

### What Changed

The original Drift Gate only matched file paths. The current version adds:
- **Semantic signals**: extracted from diff content (added lines) using language-aware heuristics
- **Change intensity**: a ranked scale from `comment-only` to `public-cli-change`
- **`min_change_intensity`** in rule `when:` clauses to reduce false positives
- **`drift-ignore` expiry** and per-rule allow/deny governance

### Step 1: Audit Your Existing Rules

For each rule in your `.drift-gate.yml`, ask:
- Does it fire on PRs that only changed comments or test files?
- Does it fire when internal/private code changes but no public contract changed?

If yes, the rule is a false positive candidate. Add `min_change_intensity` to filter it.

### Step 2: Add `min_change_intensity` to Existing Rules

**Before (v0.x)**:
```yaml
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**"]
    require:
      groups:
        - name: "API docs"
          any_changed: ["docs/api/**"]
    severity: blocker
```

**After (current)**:
```yaml
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**"]
      min_change_intensity: route-contract-change  # only real route changes
    require:
      groups:
        - name: "API docs"
          any_changed: ["docs/api/**"]
    severity: blocker
```

Intensity levels for common use cases:
- API rules: `route-contract-change`
- DB rules: `db-schema-change`
- Auth rules: `auth-policy-change`
- Env/config rules: `config-key-added`
- CI/deploy rules: `ci-secret-change`
- Public CLI rules: `public-cli-change`

### Step 3: Update `ignore_paths`

Previously, `ignore_paths` only affected trigger matching. Now it affects both trigger (`when`) and requirement (`require`) matching. Ensure you are not accidentally excluding paths used in `require.groups`.

**Bad** (breaks require matching):
```yaml
ignore_paths:
  - "docs/**"   # This prevents docs/api/** from counting as satisfying require!
```

**Good**:
```yaml
ignore_paths:
  - "src/internal/**"   # Only exclude paths that should not trigger rules
```

### Step 4: Review drift-ignore Directives

Existing `drift-ignore` comments in PR descriptions continue to work. However:
- For `BLOCKER` and `MAJOR` rules, a `reason:` line is now required. Without it, the ignore is **rejected** and the violation remains.
- The new `expires:` field (optional) lets you set an expiry date for the ignore.

If your team has been using `drift-ignore` without reasons, add them before upgrading.

---

## From Shell-Script-Based Action to drift_gate Package

If you were using the original shell-script action, replace your workflow step:

**Before**:
```yaml
- name: Check drift
  run: |
    python check_drift.py --pr ${{ github.event.pull_request.number }}
```

**After**:
```yaml
- uses: your-org/pr-convention-checker@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    repo: ${{ github.repository }}
    pr_number: ${{ github.event.pull_request.number }}
    policy_file: .drift-gate.yml
```

Or using the CLI directly:
```yaml
- name: Run drift-gate
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    REPO: ${{ github.repository }}
    PR_NUMBER: ${{ github.event.pull_request.number }}
  run: python -m drift_gate.adapters.github_action.runner
```

---

## `.drift-gate.yml` Schema Changes

### Gate Configuration

The `gate:` section is now required for meaningful behavior. Add it if missing:

```yaml
gate:
  fail_on_blocker: true
  fail_on_major_count: 2
```

### `require.groups` Format

The older flat `require.files` format is no longer supported. Use `require.groups`:

**Before**:
```yaml
require:
  files: ["docs/spec.md", "CHANGELOG.md"]
```

**After**:
```yaml
require:
  groups:
    - name: "API spec"
      any_changed: ["docs/spec.md", "docs/api/**"]
    - name: "Changelog"
      all_changed: ["CHANGELOG.md"]
```

The `any_changed` key means at least one file in the list was changed. The `all_changed` key means all files in the list must have been changed.

---

## Re-Running the Baseline After Migration

After updating your policy, run the benchmark to verify no regressions:

```
drift-gate eval --compare-baseline
```

Or with threshold enforcement:
```
drift-gate eval --compare-baseline --max-fp 0 --max-fn 0 --min-f1 1.0
```

If existing fixtures no longer match the updated rules, update the fixtures to reflect the new expected behavior. Fixture files live in `drift_gate/tests/fixtures/`.

---

## Checklist Summary

- [ ] Reviewed all rules for false positive candidates
- [ ] Added `min_change_intensity` to API, DB, auth, CI, and env rules
- [ ] Verified `ignore_paths` does not exclude `require.groups` paths
- [ ] Updated `drift-ignore` directives in open PRs to include `reason:` lines
- [ ] Replaced shell-script action with `drift_gate` package step
- [ ] Updated `require.groups` format if using old `require.files` syntax
- [ ] Added `gate:` section to `.drift-gate.yml`
- [ ] Re-ran `drift-gate eval --compare-baseline` and confirmed no regressions
