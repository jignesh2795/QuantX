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

GitHub Private Vulnerability Reporting is enabled for this repository. On 2026-11-10, the repository owner confirmed that the setting was enabled, the **Report a vulnerability** entry was visible to non-admin reporters, and the repository notification and account notification preferences were checked. These are owner-confirmed observations; the private-reporting status endpoint was not independently read back by the validation environment. Do not interpret this as a response-time or remediation guarantee.

### Reporting through GitHub

1. Open the repository's **Security → Advisories** area.
2. Select **Report a vulnerability** and follow GitHub's private reporting flow.
3. Include the affected revision, impact, prerequisites, and a minimal reproduction where safe.
4. Allow maintainers to coordinate investigation before public disclosure.

GitHub may route a repository administrator to create a draft security advisory rather than display the non-admin reporting form. For notification delivery, repository administrators/security managers should watch the repository for all activity or subscribe to **Security alerts**, with repository notifications enabled. Email preferences can be reviewed at [GitHub notification settings](https://github.com/settings/notifications).

See GitHub's official [repository configuration instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository) and its [private reporting guide](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).

This repository does not publish a dedicated security email address or promise a response SLA, bounty, or disclosure timeline. Do not assume one exists.

## Security reports versus operational incidents

Use this policy for vulnerabilities in QuantX source code, packaged artifacts, repository automation, or documented project services. Broker account incidents, exchange outages, disputed fills, or account-specific operational events are not QuantX software vulnerability reports. Contact the relevant provider through its independently verified support channel; do not publish account identifiers, credentials, or private financial records in this repository.

## Protect sensitive information

Never include broker credentials, API keys, access tokens, session cookies, account identifiers, personal data, or unredacted financial records in a report. Do not test a suspected vulnerability against a real broker account, production system, or third-party service without explicit authorization.

## Scope and disclosure

Do not probe third-party brokers, exchanges, or infrastructure as part of a QuantX security report.

Please coordinate disclosure privately with maintainers. Do not publish a proof of concept or exploit details while a report is under review.
