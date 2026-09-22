# Content verification and approved exceptions

> **Known limitations (ver2):** the [post-development audit](generalization-audit-2026-09-22.md) found false positives in strings and inline comments, missed HEAD/OPTIONS changes, and rejection of valid Markdown tables and nested OpenAPI YAML. Explicit content modes only run after the rule triggers; they do not guarantee complete detection.

## Group content modes

`require.groups[].content` supports:

| Mode | Behavior |
|---|---|
| `auto` (default) | Uses endpoint evidence for literal HTTP route deltas when required paths start with `docs/api/`, `docs/spec.`, or `openapi`. Other changes retain path-based requirements. |
| `paths` | Requires changed document paths only; use for compatibility with free-form documents. |
| `api-routes` | Requires added and removed HTTP method/path pairs to appear on the corresponding sides of the documentation diff. If no supported literal route delta can be established, the requirement remains unsatisfied. |
| `env-keys` | Requires newly introduced static environment-variable keys in the current sample document, even when the document is unchanged. Values are not retained by the content reader. |

All modes retain the rule's configured severity. Only `env-keys` can satisfy a
requirement from an unchanged document. Deleted documents do not satisfy a
requirement, and the previous name of a moved document is not treated as an
existing document.

## Environment key example

```yaml
rules:
  - id: payment-env-example
    when:
      any_changed: ["src/config/**"]
      min_change_intensity: config-key-added
    require:
      groups:
        - name: Sample environment keys
          all_changed: [".env.example"]
          content: env-keys
    severity: blocker
```

For `os.getenv('PAYMENT_TIMEOUT')`, `os.environ.get('PAYMENT_TIMEOUT')`,
`os.environ['PAYMENT_TIMEOUT']`, or the equivalent `process.env` dot/bracket
access, a sample entry `PAYMENT_TIMEOUT=...` satisfies the key requirement.
Adding `OTHER_KEY=...` or a comment does not. Both the CLI and GitHub/MCP checks
load explicitly configured sample documents. Local reads use the working tree;
GitHub reads use the collected PR head SHA.

Environment document paths must be explicit repository-relative paths. Globs,
absolute paths and parent traversal are rejected by policy validation. Readers
reject oversized files and local paths resolving outside the repository. The
new evidence field contains key names, not document values. Ordinary changed
file patches still follow the existing report behavior.

The detector recognizes static Python/JavaScript accesses. Dynamic variable
names, aliases, framework-specific settings models and validation constraints
are not fully analyzed. Strings resembling accesses can trigger false positives, and refactoring an
existing key access can incorrectly require documentation even when no new key
is introduced. This is not a runtime configuration validator.

## HTTP route example

If the source diff changes `@app.get('/users')` to
`@app.get('/members')`, a supported Markdown document should remove
`GET /users` and add `GET /members`. Changing a payment document's spelling
does not satisfy this requirement. Removing a route also requires removal of
the matching documented pair.

The content matcher recognizes literal `object.get/post/put/patch/delete/head/options`
calls, including Python decorators. However, the preceding intensity classifier
misses HEAD/OPTIONS in the audit; these methods are not reliably supported end to end. Documentation evidence is an HTTP method
followed by a path, such as `GET /members`. Nested OpenAPI YAML structure,
router prefixes, computed paths, multiline registration calls and full request/
response schema equivalence are not implemented. A changed OpenAPI filename
alone is not proof of endpoint content. Use `paths` when the document format
does not provide supported evidence, or use `api-routes` to require recognizable evidence once the rule triggers.
The documentation diff check does not subtract pairs re-added on the other side;
a stale route removed then re-added can incorrectly pass.

The default `auto` mode strengthens recognized route changes. Teams relying on
free-form release notes should keep those groups in `paths` mode. Existing
path-only policies should review this default before adopting the update.

## Analysis diagnostics

`scan_metrics.analysis_notes` records each enriched file's method and reason:

- `grammar+heuristic`: grammar parsing completed without recorded recovery for
  the changed fragments; heuristic signals are still part of the result.
- `heuristic`: unsupported file type, incomplete fragment, or grammar fallback.
- `unavailable`: missing patch or a binary/large-file skip marker.

A rule with `min_change_intensity` does not pass merely because its input could
not be analyzed. An unavailable input creates a requirement for analysis
evidence, subject to that rule's severity. Path-only rules without an intensity
threshold retain their path requirements. A failed parser can fall back to
heuristics; this is reported, not claimed as successful AST analysis.

## Verified CODEOWNERS approval

When `suppression.require_codeowners_approval: true` is configured, PR-body
`approved-by:` text is only an assertion and cannot authorize an exemption.
The GitHub adapter checks:

1. CODEOWNERS from the PR base revision, using `.github/`, root, then `docs/`
   search order and the last matching rule.
2. A current-head-commit `APPROVED` review from an eligible owner for every
   trigger path. PR-author self-approval is excluded.
3. Reviewer write access. Team owners additionally require active membership
   and team repository write access.
4. Later review dismissal or change requests, and whether the PR moved during
   collection or verification.

The implementation supports common `*`, `**`, `?`, rooted/directory patterns,
`@user` and `@org/team`. `docs/*` covers direct children, while `docs/` covers
descendants. Unsupported syntax, email-based ownership, missing permissions or
API errors do not produce verified proof. Normal owner approval still permits
exceptions; the feature does not reject every exemption indiscriminately.

GitHub approval metadata is attached only by the verification adapter. Reading
`approval_verified` from user JSON cannot manufacture trust. Local checks lack
GitHub approval evidence and reject approval-required exceptions. Audit entries
record verification and the approved commit. Exception reasons and expiry
dates remain independently enforced. Adjacent ignore directives cannot borrow
one another's reason or expiry.

Repository policy and CODEOWNERS changes still need the team's own review and
branch protection. This tool does not configure repository permissions.

Behavior and endpoint references: [GitHub CODEOWNERS documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners),
[pull request reviews API](https://docs.github.com/en/rest/pulls/reviews).
External integration has been tested with controlled API responses in this
change; it has not been exercised against a real organization's permissions.

## Dependency and rollout notes

The parser runtime is pinned to the versions used in the baseline environment.
The composite Action installs the package with those dependencies, rather than
installing only PyYAML. Grammar acquisition can require network/cache access on
first use. The current local verification uses Python 3.11; cross-platform CI
results must be checked after pushing the change.

See [development results](development-results-2026-09-22.md) for measured
before/after results and the remaining roadmap.
