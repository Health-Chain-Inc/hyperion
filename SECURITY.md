# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| latest (`main`) | Yes |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

To report a security issue, email **security@healthchain.com** with:

- A description of the vulnerability and its potential impact
- Steps to reproduce or proof-of-concept code
- The version / commit SHA you tested against

You will receive an acknowledgement within 2 business days and a resolution timeline within 5 business days.

We follow coordinated disclosure: we will work with you to understand and fix the issue before any public disclosure, and we will credit you in the release notes unless you prefer to remain anonymous.

## Scope

Issues in scope:
- Remote code execution or privilege escalation in the pipeline or sidecar processes
- Secrets exposure (environment variables, blob storage credentials, engine passwords)
- Authentication bypass in the Azure FHIR or Service Bus integration
- SQL injection via the StarRocks stream-load path

Out of scope:
- Vulnerabilities in third-party dependencies (report those upstream; open a Dependabot PR here)
- Issues that require physical access to the host
- Social engineering