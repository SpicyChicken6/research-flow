# Development and testing

## Setup

Requires Python 3.10+, Node 22+, and Chromium for browser tests. From the source root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[test]'
.venv/bin/python -m playwright install chromium
```

On minimal Linux, use `playwright install --with-deps chromium` if browser system
libraries are missing. Node, Playwright, and Pillow are only needed for tests.

## Run the tests

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/test_*.mjs
.venv/bin/python scripts/build_preview.py
for suite in tests/browser/*_checks.py; do
  .venv/bin/python "$suite" || exit 1
done
```

| Location | Coverage |
| --- | --- |
| `tests/test_*.py` | YAML validation, migrations, saves, conflicts, backups, authentication, CLI startup, updates and current-folder discovery |
| `tests/test_*.mjs` | Graph model, branches, connections, layout and logo animation |
| `tests/browser/` | Dependency stages/freeform, editing, export/reopen, hierarchy, deletion, minimap, animation and authenticated browser save/reload |
| `tests/installed_checks.py` | Installed command, bundled assets and saving outside the source checkout |
| `tests/update_install_checks.py` | Real same-version self-updates in disposable pip and pipx installations, suffix/home targeting and workflow preservation |

Tests use disposable projects. Generated browser reports and screenshots go to
ignored `test-results/`; the portable HTML build goes to ignored `dist/`.

The direct browser suite uses a real CLI server and a TCP port relay. It tests
forwarded-port behavior, not SSH authentication or a particular remote server.
Other browser suites also exercise portable HTML; their server sections use a
Python HTTP bridge. Safari, Firefox and systemd deployment are not covered.

## Build and test an installable package

```bash
.venv/bin/python -m pip install build twine
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*.whl dist/*.tar.gz
```

Install a newly built wheel in a separate environment and check it:

```bash
python3 -m venv /tmp/research-flow-check
/tmp/research-flow-check/bin/python -m pip install dist/research_flow-0.8.7-py3-none-any.whl
.venv/bin/python tests/installed_checks.py /tmp/research-flow-check/bin/research-flow
```

The same check can target a pipx-installed `research-flow` executable. GitHub Actions
runs unit and package-installation jobs on Linux with Python 3.10/3.12, plus browser
tests. See [Actions](https://github.com/SpicyChicken6/research-flow/actions) for results.

To test actual self-updates without fetching repository code, put the built wheel
and compatible PyYAML/pip wheels in one folder, then run:

```bash
.venv/bin/python -m pip install pipx
mkdir -p /tmp/research-flow-update-wheels
cp dist/research_flow-*.whl /tmp/research-flow-update-wheels/
.venv/bin/python -m pip download --only-binary=:all: --dest /tmp/research-flow-update-wheels 'PyYAML>=6.0.2,<7' pip
.venv/bin/python tests/update_install_checks.py /tmp/research-flow-update-wheels/research_flow-*.whl .venv/bin/pipx
```

The harness overrides the source URL only in its test process and installs from
local wheels with network indexes disabled. It never updates your existing app.

## Repository layout

- `server.py`, `updater.py`, `__init__.py`, `__main__.py`: Python server, updater and installed entry points.
- `web/`: interface, graph model, styles and SVG assets.
- `scripts/build_preview.py`: build editable standalone HTML without changing source.
- `examples/`: demonstration workflow used by the preview builder and tests.
- `tests/`: unit, installation and browser regression tests with shared fixtures.
- `docs/`, `deploy/`: user guides, showcase image and optional systemd service.
- `pyproject.toml`, `MANIFEST.in`: dependencies and package contents.
