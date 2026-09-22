# Development comparison

Baseline: `bffc6550fd0b7da0509fe9ae8838efcf5fe9bc8c` (2026-09-22T06:50:47.444352+00:00)
Candidate: `bffc6550fd0b7da0509fe9ae8838efcf5fe9bc8c` (2026-09-22T07:19:45.423514+00:00)

Same fixtures, challenge suite and harness: **True**
Same Python, platform and dependency versions: **True**

Counts are limited to these synthetic cases; they are not production accuracy.
Pytest counts can change when tests are added. Compare fixed-case results separately.

| Metric | Before | After | Delta (after - before) |
|---|---:|---:|---:|
| pytest passed | 470 | 524 | +54 |
| pytest failed/errors | 1 | 0 | -1 |
| parser smoke passed / 3 | 0 | 3 | +3 |
| challenge passed / 8 | 4 | 8 | +4 |
| path-only passed | 19 | 19 | +0 |
| path-only false_positive_count | 3 | 3 | +0 |
| path-only false_negative_count | 0 | 0 | +0 |
| path-only precision | 0.823529 | 0.823529 | +0 |
| path-only recall | 1 | 1 | +0 |
| path-only f1 | 0.903226 | 0.903226 | +0 |
| patch-aware passed | 22 | 22 | +0 |
| patch-aware false_positive_count | 0 | 0 | +0 |
| patch-aware false_negative_count | 0 | 0 | +0 |
| patch-aware precision | 1 | 1 | +0 |
| patch-aware recall | 1 | 1 | +0 |
| patch-aware f1 | 1 | 1 | +0 |
| semantic-aware passed | 22 | 22 | +0 |
| semantic-aware false_positive_count | 0 | 0 | +0 |
| semantic-aware false_negative_count | 0 | 0 | +0 |
| semantic-aware precision | 1 | 1 | +0 |
| semantic-aware recall | 1 | 1 | +0 |
| semantic-aware f1 | 1 | 1 | +0 |

## Fixed challenge cases

| Case | Before | After | Expected |
|---|---|---|---|
| C01-route-without-docs | fail | fail | fail |
| C02-unrelated-doc-typo | pass | fail | fail |
| C03-related-doc-update | pass | pass | pass |
| C04-deleted-api-file | pass | fail | fail |
| C05-missing-api-patch | pass | fail | fail |
| C06-unverified-approval | pass | fail | fail |
| C07-comment-only | pass | pass | pass |
| C08-implementation-only | pass | pass | pass |

Inspect raw reports and changed source hashes before claiming improvement.
