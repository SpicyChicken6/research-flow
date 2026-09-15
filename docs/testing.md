# Release verification

## Current-directory discovery — 0.8.2

Local verification passed: 78 Python tests, 92 JavaScript tests, and 21 direct-browser
checks. A fresh pipx installation passed the installed-app checks for an explicit
path, an empty launch directory, and an existing workflow with an arbitrary `.yml`
filename. Opening that existing file preserved its original bytes until Save.

Regression coverage also checks multiple YAML files, invalid YAML, nonrecursive
discovery, case-insensitive YAML extensions, and ignoring `XDG_DATA_HOME` for the
new default. Explicit project selection works even in an ambiguous directory.
Both package formats pass metadata validation. Linux CI tests installation from
the wheel and source archive on Python 3.10 and 3.12; see the commit's Actions run.

## Installable app — 0.8.1

Local checks passed on macOS with Python 3.13: all 73 Python tests, 92 JavaScript
tests, and the 21 direct-browser checks. The wheel and source archive both passed
`twine check`. A fresh pipx wheel installation and a separate source-archive
installation each passed `tests/installed_checks.py` from a temporary directory
outside the source checkout. `python -m research_flow --version` also passed.

Installation checks cover all bundled web assets, explicit YAML paths containing
spaces, the default external data path, authenticated saving, unauthorized reads,
stale revisions, backups, token persistence, and graceful shutdown. The wheel
contents were inspected: only the three Python modules, seven web assets, and
package metadata are included. No workflow data, exports or credentials are bundled.

GitHub CI repeats wheel installation through pipx and source-archive installation
on Linux with Python 3.10 and 3.12. Check the commit's Actions run for its results.

## First-upload review — September 15, 2026

The source archive was reviewed before its first upload. The 47-file release
manifest matched the archive; a credential-pattern scan found no credentials, and
the included screenshot and example project contained demonstration content.
This was a focused code and packaging review, not an exhaustive security audit.

Two validation issues were reproduced and fixed: the browser accepted non-string
task IDs/statuses through implicit coercion, and extremely large Python integers
raised an uncaught overflow rather than a validation error. Regression tests now
cover both cases.

Current local verification on macOS, Python 3.13, Node 25.9.0, Playwright 1.63.0,
and Chromium 153:

| Suite | Result |
| --- | --- |
| Python unit/integration tests after fixes | 73 passed |
| JavaScript unit tests after fixes | 92 passed |
| Existing browser checks | 333 assertions passed |
| Authenticated transport harness | 17 assertions passed |
| Direct browser-to-CLI-server check | 21 assertions passed |
| Shell syntax and standalone build | Passed |

The direct browser check exercised native HTTP through a TCP port relay, token
removal from the URL, tab storage, save/reload, backups, and rejection of an
unauthenticated tab. This resolves the earlier local-browser verification gap
described below. It does not test a real SSH connection or the target Linux host.
GitHub Actions results are recorded separately by GitHub for each pushed commit.

## Original bundle's observed results

These results were obtained in the preparation environment, not on the owner's
remote Linux machine and not in GitHub Actions.

| Suite | Result |
| --- | --- |
| Python unit/integration tests | 72 tests passed |
| JavaScript unit tests | 90 tests passed |
| Existing workflow/browser checks | 333 assertions passed (88 essential, 48 motion, 82 hierarchy, 115 branch/minimap/delete) |
| New authenticated transport harness | 17 assertions passed |
| Launcher / shell / standalone build | Passed version, shell syntax, and non-mutating build checks |
| Direct browser-to-CLI-server test | Blocked by managed browser policy; NOT a passing end-to-end test |

Environment: Linux, Python 3.13.5, Node 22.16.0, Chromium 144.0.7559.96, Git 2.47.3.
The included CI configuration targets Python 3.10/3.12 and Node 22. It has not run
on GitHub because this source has not been published from this session.

## What was actually tested

The Python suite uses disposable local files and real loopback HTTP requests. New
coverage includes headless CLI startup from a different working directory, default
external data initialization, refusing accidental replacement, private persistent
token files, symlink/mode rejection, bearer authentication, exact Host/Origin checks,
static asset restrictions, saves, stale revisions, backups, and graceful SIGTERM.

One CLI test forwards actual TCP traffic through a local relay with different local
and remote ports. This verifies the forwarding topology and configured browser-port
handling, not SSH authentication/encryption or the real remote host.

The retained browser suites render the actual portable application and exercise
the graph, blank insertion, hierarchy, deletion dialog, global minimap, child
membership, focus, reparenting, undo/redo, export/reopen, reduced motion and final
square divider. Server-mode sections use an explicit Python fetch bridge.

`tests/transport_checks.py` uses Chromium with `set_content`, a real local Python
HTTP server, and an explicit fetch bridge. It verifies the authenticated app-to-API
contract and writes to disposable YAML on disk. A test environment adapter is used
for the bootstrap URL/history/session-storage interfaces. This does NOT verify
native browser transport, real tab storage across navigation, or SSH connectivity.
The 8 connection helper unit tests separately cover those API calls with controlled
inputs, including storage failures; they are not browser implementation tests.

`tests/linux_browser_checks.py` is included to exercise the direct browser path,
actual CLI process, port relay, URL fragment removal, native tab storage, reload and
saved YAML. It could not finish here: Chromium reported
`net::ERR_BLOCKED_BY_ADMINISTRATOR` on localhost navigation. No browser policy was
disabled. It remains a real failing/incomplete verification, not a skipped success.
Its error reporting redacts private URL tokens. Run it in an unrestricted development
or CI environment before relying on the deployment.

## Reproduce

From the source root with development requirements installed:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/test_*.mjs
python scripts/build_preview.py
python -m playwright install chromium
python tests/essential_checks.py
python tests/logo_motion_checks.py
python tests/children_checks.py
python tests/branch_update_checks.py
python tests/transport_checks.py
python tests/linux_browser_checks.py
```

On minimal Linux, Playwright may require its `install --with-deps chromium` step
and administrator approval for system libraries. The application itself does not
need Node or a browser installed on the server.

## Remaining checks

The systemd user-service template has not been installed on the target server.
Safari, Firefox, real-device touch and the exact local Avenir rendering are not
verified. No independent security audit was performed. The authenticated GitHub
publishing step could not be run here; the current connector has no repository
creation operation and no accessible Research Flow repository was found.

Before entering important work on the remote host, add a disposable step, save,
reload through the actual SSH tunnel, and confirm that its title persists. Keep
existing project files and their backups when installing this release.
