# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, **please do not open a public GitHub issue**.

Instead, report it privately by emailing the maintainer directly (see the GitHub profile for contact details).

We will acknowledge receipt within 48 hours and aim to resolve the issue within 7 days.

## Sensitive Data Handling

This agent requires the following secrets, which must **never** be committed to the repository:

| Secret | Where to store |
|--------|---------------|
| `OPENAI_API_KEY` | `.env` file (local) or GitHub Repository Secret |
| `SMTP_USER` | `.env` file (local) or GitHub Repository Secret |
| `SMTP_PASSWORD` | `.env` file (local) or GitHub Repository Secret |
| `NOTIFY_EMAIL` | `.env` file (local) or GitHub Repository Secret |

The `.env` file is listed in `.gitignore` and should **never** be committed.
Use `.env.example` as a template – it contains only placeholder values.

## GitHub Actions Secrets

When running via GitHub Actions, all sensitive values are injected at runtime via
**GitHub Repository Secrets** (`Settings → Secrets and variables → Actions`).
No secrets are hardcoded in the workflow file.
