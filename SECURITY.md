# Security and privacy

This is a personal, single-project editor, not a public or multi-tenant server.

## Intended deployment

Run the server under your own account, bound to 127.0.0.1. For remote use, connect
through VS Code's integrated browser over authenticated Remote-SSH, or an SSH
local-forwarding session. The command-line entrypoint always requires a random
bearer token for project API reads/writes. Each browser tab receives it through the
private access URL; it is kept separately from the workflow and never exported with
YAML/JSON or portable project data. There is no public signup, sharing, or permissions
system.

Host/Origin checks, a required custom request header, lack of permissive CORS,
no-store responses, no-referrer, frame denial, and an explicit static-file allowlist
reduce accidental exposure. They are defense in depth, not a substitute for a
production server, TLS, patching, or OS account isolation. An unauthenticated health
endpoint contains only health and version information; the HTML shell contains no
private project data.

Do not expose this app using a public reverse proxy or by changing its bind address.
Do not give others the private URL, the token file, or your browser session. Your own
server account, root, browser extensions with sufficient access, and trusted frontend
code are inside the trust boundary. Anyone with the token and network access can
read/write the selected workflow. Tokens have no per-operation scopes or expiration.
Restart after rotating a token; a running process holds its token in memory.
Startup prints the private URL, so keep terminal output and service journals private;
anyone allowed to read those logs may obtain the token.

Python's built-in HTTP server is not intended as a hardened production server:
https://docs.python.org/3/library/http.server.html

## Files

Project files, file paths, notes and portable exports may contain confidential data.
Keep them outside the source checkout. `.gitignore` is a convenience, not a complete
secret detector. Review staged files before publishing. Never force-add data or keys.
Backups share the same confidentiality as the original project. The app does not
upload referenced files, execute commands in nodes, or send analytics.

Unknown project metadata is preserved when possible. YAML aliases, duplicate mapping
keys, recursive structures, oversized payloads, invalid parentage and dependency
cycles are rejected. Save uses optimistic revision checks and atomic file replacement
with backups. A small race remains possible with non-cooperating external writers
between the final revision check and replacement. Use one process per workflow and
coordinate external editing; this is not a database lock across all writers.

## Reporting

Do not post real project files, private URLs or tokens in public issues. Report a
problem privately to the repository owner and supply a redacted minimal example.
No independent security audit or production certification has been performed.
