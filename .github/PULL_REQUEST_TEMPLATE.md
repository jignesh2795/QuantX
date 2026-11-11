## Summary

Describe the change and the problem it solves.

## Change type

- [ ] Bug fix
- [ ] Feature or behavior change
- [ ] Architecture change
- [ ] Documentation or repository hygiene
- [ ] Tests or validation tooling

## Scope and invariants

- [ ] The diff is limited to the stated issue or workstream.
- [ ] Universal core remains free of broker SDKs and market-specific rules.
- [ ] Financial calculations continue to use `Decimal`; no float money was introduced.
- [ ] Unknown or missing evidence remains fail-closed; UNKNOWN is not treated as zero or PASS.
- [ ] No credentials, personal data, or sensitive financial records are included.
- [ ] No real broker orders, production API calls, sandbox activity, or LIVE execution were performed.

## Validation

Record exact commands, revision, exit codes, and relevant results. Do not report a check as passing if it was skipped, incomplete, or run against a different revision.

- [ ] Focused tests (where applicable)
- [ ] Full test suite (where required)
- [ ] Changed-file Ruff check and format (where Python files changed)
- [ ] Strict mypy (where production Python files changed)
- [ ] `git diff --check`
- [ ] Documentation links and examples checked (where applicable)

Validation evidence:

```text
Revision:
Commands:
Results:
```

## Reviewer notes

List known limitations, deferred work, and any remaining UNKNOWN evidence.
