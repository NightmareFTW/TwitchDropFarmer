# Security Policy

## Supported Versions

- `2.0.x`: Supported
- `main`: Best-effort support during active development
- Older versions: Not supported

## Reporting a Vulnerability

Please report security issues responsibly.

1. Prefer a private GitHub Security Advisory report for this repository.
2. If private reporting is unavailable, open a minimal issue titled `[SECURITY] Private report request`.
3. Do not publish exploit details, proof-of-concept code, tokens, cookies, session files, or user-identifying logs in public.

Include in your report:

- Affected version and platform
- Clear reproduction steps
- Impact assessment
- Suggested fix or mitigation (if available)

## Response Targets

- First acknowledgement: within 72 hours
- Triage decision: within 7 days
- Fix timeline: depends on severity and complexity

## Operational Safety Notes

This project processes local authentication/session artifacts. Do not commit or share:

- `cookies.json`
- `campaign_cache.json`
- Session exports (JSON)
- `crash.log` or logs with tokens/cookies

Before opening issues, redact all sensitive values.
