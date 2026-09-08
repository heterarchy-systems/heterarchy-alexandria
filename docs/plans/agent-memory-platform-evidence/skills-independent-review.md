# Alexandria skills independent review — 2026-09-09 KST

Two read-only `verification_steward` passes reviewed API/scope instructions and
storage/recovery scenarios independently of the writer. Both re-reviewed their
findings after correction and reported no remaining finding within those scopes.
The coordinator accepted the source repairs and ran final canonical CI.

## Findings and closure

| Finding | Correction | Evidence |
| --- | --- | --- |
| `curl` errors hidden by successful `jq` | Operational shell examples use `set -euo pipefail` and `curl -fsS` | Eight transport/HTTP failure executions preserved nonzero status in bash/zsh |
| Synchronous rebuild response loss confused with durable job status | Lost response remains UNKNOWN; current health cannot prove that particular run completed | Independent recovery re-review resolved |
| Null projection freshness and SUCCEEDED job treated too strongly | Inspect nullable freshness, job warnings and affected RAG rows separately | Independent recovery re-review resolved |
| AUTO fallback could be confused with STRICT identity rules | No substitution rule explicitly applies to STRICT/explicit scopes and Context writes | Independent API re-review resolved |
| Cycle source drift guidance omitted source-fence errors | Repair indicated source/index readiness and obtain fresh dry-run | Independent API re-review resolved |
| Verify selector validation happened after the request boundary | Exactly-one model validator; domain guard retained | Schema rejection and actual HTTP 422 regressions; independent source re-review resolved |
| Managed-spec initial output failures could escape HTTP mapping | Reused existing Obsidian save mappings after specific managed/checkpoint mappings | HTTP 409 conflict/recovery/checkpoint regressions; independent source re-review resolved |

The reviews also checked exact-path skill updates without invented report/date
identity, scheduler retry after missing source, stored source with pending vector
and unrelated queue work, missing composite availability, and managed-spec hash
field mapping. No source/API deployment or live mutation was part of this review.

## Executed evidence

- Skill quick validation: all four skill folders passed.
- Twelve shell examples passed bash/zsh syntax checks; eight relative links resolved.
- Four queued-job success/failure executions passed using a local curl stub.
- Eight synchronous rebuild connection/HTTP failure executions returned failure.
- Recall example, cycle plan hash and managed-spec envelope hash mappings validated
  against current schemas. No network requests were used for shell validation.
- Bounded implementation worker: 28 focused PostgreSQL tests passed, Ruff passed,
  Pyrefly zero errors. Worker reported four initial expected regression failures.
- Coordinator final root `make ci`: exit 0, 950 PostgreSQL tests in 97.19 seconds,
  34 benchmark-tool tests, Ruff format/lint, Pyrefly zero errors (75 non-error
  warnings not shown), seven Python mechanical gates, Rust rules/format/tests,
  and native FFI parity all passed.
- CodeGraph was synchronized and `git diff --check` passed.

Full log: [skills-review-ci.log](skills-review-ci.log).
SHA-256: `7cfc3ef3703e2345da9c0f2c3d2f37e921076fa3225ae727ae1e225207f35e5a`.

Independent reviewers' ambient raw pytest attempts failed at PostgreSQL DNS
setup; those attempts are not counted as test passes. The worker's canonical
temporary PostgreSQL run and coordinator's full root CI provide executable
evidence. Fault-injection HTTP tests prove error mapping, while earlier real
Vault/managed-spec lifecycle tests remain included in the aggregate suite.

## Boundaries

This closes the bounded skill review and two discovered interface defects.
It does not claim a fresh live deployment, plugin reload, release-native seal or
general semantic quality assessment. Existing dirty work is preserved; no commit
or push was made for this review. The earlier Alexandria storage receipt remains
historical evidence from before these boundary repairs.
