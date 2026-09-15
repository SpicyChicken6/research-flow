# Research Flow

One project. A clear, editable workflow.

A small browser-based planner for a single research project. Run the Python server
on your Linux machine, reach it through an SSH tunnel, and edit the workflow in your
own browser. The project is a human-readable YAML file, not an application database.

![Research Flow](docs/screenshot.png)

## What stays in the interface

- Place a blank step immediately, then click it to edit.
- Drag and connect steps. Edit, reverse or remove dependency arrows.
- Add smaller child cards, nest branches, collapse them, and move a whole branch.
- Focus a branch or return to Overview. Use the global minimap to navigate.
- Edit goals, status, notes and input/output references. Undo and redo changes.
- Save explicitly, with revision-conflict protection and previous-version backups.

No project library, dashboards, upcoming-step suggestions, AI execution, or account
service. Original logos, the restrained animation, and the latest thin rectangular
title divider are preserved.

## Install the app on Linux

Requires **Python 3.10+** and [pipx](https://pipx.pypa.io/stable/installation/).
Install the released app in its own environment:

```bash
pipx install https://github.com/SpicyChicken6/research-flow/releases/download/v0.8.2/research_flow-0.8.2-py3-none-any.whl
pipx ensurepath
```

If the command is not found, reopen your terminal after `pipx ensurepath`.
Go to your research folder and launch:

```bash
cd ~/research/my-study
research-flow
```

With no `--project`, the app uses the only `.yaml` or `.yml` file in the current
directory. If none exists, it creates `workflow.yaml`. If several exist, it stops
and asks you to select one with `--project`. Discovery does not search subfolders.
The YAML must be a valid Research Flow workflow; unrelated or invalid YAML is never
overwritten. Click **Save** to update the selected file, and keep the server running.

To choose a path explicitly from any directory, use
`research-flow --project /absolute/path/to/workflow.yaml`. Add `--init` to create it
if missing. The terminal's current directory controls automatic discovery; merely
changing VS Code's open workspace does not switch a running app's project.

For a remote server, forward port **8765** through SSH or VS Code Remote-SSH and
open the complete private URL printed by the app. In current VS Code Desktop, use
**Browser: Open Integrated Browser** to open that URL inside the editor.
An exported HTML file uses **Save copy**, not server-side YAML saving.

See [installation and VS Code instructions](docs/install.md) for setup, upgrades,
alternative installation methods, and choosing the YAML file. This repository is
public; access to a running instance still requires its private token.

## Run from a source checkout on a remote Linux server

Requires **Python 3.10+**, `venv`, and PyYAML. Git is needed for source control; Node
and Playwright are only needed to run development tests. No frontend build is needed.

From your research folder, point to the downloaded application's launcher:

```bash
cd ~/research/my-study
bash ~/apps/research-flow/start.sh
```

On its first run, the launcher creates `.venv` and installs the one runtime
dependency. The server opens the only YAML in the current directory, or creates:

```text
./workflow.yaml
```

Application updates do not touch this research directory. To select an **existing**
workflow explicitly instead:

```bash
bash ~/apps/research-flow/start.sh --project /absolute/path/to/your/project.yaml
```

An explicit missing path is not silently created: use `--init` to initialize it.
`--init` never overwrites an existing file.

On your **own computer**, open a second terminal:

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 127.0.0.1:8765:127.0.0.1:8765 YOUR_USER@YOUR_SERVER
```

Leave both terminals running. In your browser, open the **private access URL printed
by the server**, which begins with `http://127.0.0.1:8765/#token=…`.
Do not share that URL. No server-side desktop or browser is needed.

The token is moved out of the address bar and retained in that browser tab's session
storage. Each API read/write requires it. Saving writes to the server-side YAML;
it does not download a replacement HTML in server mode.

For an already running instance, recover its private URL with:

```bash
# Run in the same research folder used to launch the server.
bash ~/apps/research-flow/start.sh --print-url
# For an existing custom workflow, include the same --project used to launch it.
```

The saved token survives restarts. A different browser tab may need the private URL
again. [Remote Linux guide](docs/linux.md) covers alternate ports, an optional user
service, stopping/updating, backups, and troubleshooting.

## Security boundary

The server binds only to **127.0.0.1**. It rejects unexpected Host/Origin headers and
requires a private token for project API access. It serves only an explicit list of
web assets, not arbitrary files from the project directory.

**Use SSH forwarding. Do not expose this directly to the internet or use it as a
multi-user service.** It still uses Python's lightweight `http.server`, not a
hardened production application server. An access token is not a replacement for
TLS, user authorization, or operating-system isolation. Other people with your
server account, root access, or your browser session can access your work.
See [SECURITY.md](SECURITY.md).

## Existing installations

Stop the previous server, unpack this release into a fresh application directory,
and point it at your existing YAML using `--project`. Keep the previous file and its
`.research-flow` backups. Older checklist-style substeps continue to migrate to child
cards when loaded; a read does not rewrite your file. The next explicit Save writes
the normalized structure and keeps the preceding bytes in a backup.

The default changed in **0.8.2** to the current directory. To continue the global
default from 0.8.0/0.8.1, use
`research-flow --project "$HOME/.local/share/research-flow/project.yaml"`
(or your previous `XDG_DATA_HOME` path). Existing files are not moved or deleted.
Services should specify an absolute `--project` path; the supplied systemd template
does this explicitly so the service's working directory does not select its data.

## Data model

```yaml
schema_version: 1
project:
  id: my-project
  name: My research project
tasks:
  - id: analysis
    title: Analyze the dataset
    status: todo
    depends_on: []
  - id: qc
    title: Audit quality
    parent_id: analysis
    status: todo
    depends_on: []
  - id: model
    title: Fit the model
    parent_id: analysis
    status: todo
    depends_on: [qc]
layout:
  positions: {}
```

`parent_id` means “belongs to”; `depends_on` means “requires.” They are distinct.
When you connect an ungrouped step to a child, the UI can adopt it into that child's
branch when unambiguous. It does not regroup old projects on load. Each task has
one optional parent and multiple possible prerequisites. Both cycles are rejected.
Names and positions can change without changing stable IDs.

A single process should serve each workflow file. Saves are atomic replacements
with optimistic revision checks, not database transactions with unrelated editors.
The latest 20 file backups are retained under `.research-flow/backups/<filename>/`
next to the project. YAML comments/formatting are normalized on save. File references
are text; the app does not execute programs or automatically upload referenced files.

## Portable HTML (optional)

```bash
.venv/bin/python scripts/build_preview.py
```

This creates `dist/research-flow.html` with fictional example data. Open it without
a server and use **Save copy** to download an editable HTML containing your changes.
The builder does not alter tracked source. To export a specific project:

```bash
.venv/bin/python scripts/build_preview.py \
  --project /absolute/path/to/project.yaml --output /tmp/my-workflow.html
```

Exports can contain private research notes. They are ignored by Git and should not
be committed to the application repository. Tokens are not part of project data.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/test_*.mjs
.venv/bin/python scripts/build_preview.py
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/essential_checks.py
.venv/bin/python tests/logo_motion_checks.py
.venv/bin/python tests/children_checks.py
.venv/bin/python tests/branch_update_checks.py
.venv/bin/python tests/linux_browser_checks.py
```

No `npm install` is required. The browser suites use disposable data, generate
ignored reports in `test-results/`, and require Chromium. On a minimal server,
Playwright's `install --with-deps chromium` may need administrator permission for
system libraries. CI configuration is included; a successful local run does not
mean CI has run on GitHub. In restricted environments, `tests/transport_checks.py`
provides an explicitly simulated-browser transport check against the real HTTP API;
it is not a substitute for the direct browser test. See [testing notes](docs/testing.md).

## Build an installable distribution

From a development environment in the source checkout:

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*.whl dist/*.tar.gz
```

The wheel includes the Python server and its web assets. Workflow YAML, tokens,
backups, generated exports and test output are excluded. CI installs both the wheel
and source distribution, then verifies saving from outside the checkout.
Downloads are published on [GitHub Releases](https://github.com/SpicyChicken6/research-flow/releases).
The historical `scripts/publish_github.py` helper only creates new private
repositories; it is not an installer or an updater for this existing repository.

## Source layout

```text
web/          Interface, SVG artwork, graph model and animation
server.py     Validation, persistence, loopback HTTP and private access
scripts/      Launcher helpers, validation, standalone build and publishing
examples/     Fictional example and blank starting template
tests/        Model, persistence, interface and Linux regression tests
deploy/       Optional systemd user-service template
docs/         Deployment and testing notes
```

The project-title font is resolved on the **client browser**, not the Linux server.
Avenir uses a locally installed face with a bold treatment; a fallback is used when
unavailable. No font files or external font requests are included. No open-source
license has been selected for this source bundle.
