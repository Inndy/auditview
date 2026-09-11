# Security policy

## Supported versions

Security fixes are made on the default branch and released in the newest PyPI
version. Older releases are not maintained as separate support lines.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. If that
option is unavailable, open a public issue containing only a request for a
private contact channel—do not include exploit details, secrets, or vulnerable
code in the issue.

Include the affected version or commit, impact, reproduction conditions, and a
minimal proof of concept where safe. No response-time SLA is currently offered.

## Threat model

auditview is a single-user local tool with no authentication or authorization
layer. Keep the default `127.0.0.1` bind address and do not expose its HTTP port
to untrusted networks. Anyone who can reach the server can read tracked source
and modify review notes, issues, and marks.

Language-server support is opt-in because analysing an untrusted repository can
execute or load project-controlled tooling, plugins, build scripts, or macros.
Do not use `--lsp` on code you would not trust those installed language servers
to inspect. See the README's "Running safely" section for details.

The `.auditview.db` file may contain source snippets in note snapshots. Treat it
as potentially sensitive and remove it securely when its audit trail is no
longer needed.
