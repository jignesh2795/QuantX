# Security Policy

QuantX is pre-1.0 software. The repository does not currently define a stable-release support window, maintained release branches, or a backport policy. Do not assume that an older development version receives security fixes.

## Supported versions

| Version or branch | Security support |
|---|---|
| Default branch (`main`) | Development line; reports are welcome, but no response-time or remediation SLA is promised. |
| Older development commits or unreleased snapshots | No separate maintenance guarantee. |

Maintainers will identify affected revisions and any fixed revision in a security advisory or release note when a report is handled.

## Reporting a vulnerability

Please do not disclose suspected vulnerabilities in a public issue, pull request, discussion, or commit.

GitHub Private Vulnerability Reporting is a repository setting separate from this `SECURITY.md` file. The repository owner reports that the setting was enabled on 2026-11-10. This owner-reported change has not been independently read back through GitHub's private-reporting status endpoint in this workflow. The reporter-facing form and notification routing also remain to be verified; do not treat the private channel as fully operational until those checks are complete.

### Post-enablement verification before broad public contribution

A repository owner or administrator must:

1. Open the repository's **Security and quality → Advisories** area and verify that **Report a vulnerability** is exposed to non-admin reporters. An administrator may be routed to create a draft security advisory instead of submitting a report.
2. Verify that repository administrators/security managers receive private-report notifications. GitHub documents notifications for administrators/security managers who watch the repository for all activity or subscribe to **Security alerts**, with repository notifications enabled.
3. Check the account's notification preferences at [GitHub notification settings](https://github.com/settings/notifications). For email delivery, enable email notifications for watched repositories.
4. Keep this policy and Issue #190's status accurate; claim an operational private reporting path only after the reporter-facing form and notification route have been verified.

See GitHub's official [repository configuration instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository), its [private reporting guide](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately), and the [REST API status endpoint documentation](https://docs.github.com/en/rest/repos/repos#check-if-private-vulnerability-reporting-is-enabled-for-a-repository).

Until the reporter-facing form and notification route are verified, do not send exploit details, proof-of-concept code, or sensitive evidence through public GitHub issues or pull requests. This repository does not publish a dedicated security email address or another verified private contact route. Do not invent or assume one. If GitHub's private channel is unavailable or notification delivery cannot be established, maintainers must establish and publish a monitored private contact route before broad public contributor recruitment.

When a verified private route is available, include the affected revision, impact, prerequisites, and a minimal reproduction where safe. Allow maintainers to coordinate investigation before public disclosure.

## Security reports versus operational incidents

Use this policy for vulnerabilities in QuantX source code, packaged artifacts, repository automation, or documented project services. Broker account incidents, exchange outages, disputed fills, or account-specific operational events are not QuantX software vulnerability reports. Contact the relevant provider through its independently verified support channel; do not publish account identifiers, credentials, or private financial records in this repository.

## Protect sensitive information

Never include broker credentials, API keys, access tokens, session cookies, account identifiers, personal data, or unredacted financial records in a report. Do not test a suspected vulnerability against a real broker account, production system, or third-party service without explicit authorization.

## Scope and disclosure

Do not probe third-party brokers, exchanges, or infrastructure as part of a QuantX security report.

Please coordinate disclosure privately with maintainers. Do not publish a proof of concept or exploit details while a report is under review. A disclosure timeline and remediation SLA have not yet been established.
