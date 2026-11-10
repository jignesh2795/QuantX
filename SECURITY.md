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

1. Check the repository's **Security** tab for GitHub Private Vulnerability Reporting. If the repository offers **Report a vulnerability**, use that private channel.
2. If private vulnerability reporting is not available, do not publish exploit details or sensitive evidence publicly. Contact the repository owner or maintainers through a trusted private channel that you have independently established with them.
3. Include the affected revision, impact, prerequisites, and a minimal reproduction where safe. Allow maintainers to coordinate investigation before public disclosure.

This repository does not currently publish a dedicated security email address, and this policy does not imply that GitHub private vulnerability reporting has been enabled. No response-time guarantee is currently defined.

## Protect sensitive information

Never include broker credentials, API keys, access tokens, session cookies, account identifiers, personal data, or unredacted financial records in a report. Do not test a suspected vulnerability against a real broker account, production system, or third-party service without explicit authorization.

## Scope and disclosure

Report vulnerabilities that materially affect QuantX source code, packaged artifacts, repository automation, or documented project services. Do not probe third-party brokers, exchanges, or infrastructure as part of a QuantX security report.

Please coordinate disclosure privately with maintainers. Do not publish a proof of concept or exploit details while a report is under review. A disclosure timeline and remediation SLA have not yet been established.
