# Security Policy

## Supported Versions

- The latest release: Supported
- `main`: Best-effort support during active development
- Older releases: Not supported (please update first)

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

- `cookies.json` and `session.json` (they hold the login token in plain text)
- `config.json` and the other files in `~/.twitch-drop-farmer`
- Session exports (JSON)
- Logs that were not saved with the app's "Save log" button (it removes tokens and cookies; anything else may not)

Before opening issues, redact all sensitive values, including your Twitch login name and user id.
