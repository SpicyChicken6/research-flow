# Install Research Flow

Research Flow 0.8.6 installs a `research-flow` command. It runs a small Python server
and serves the existing browser interface. Linux needs Python 3.10+; Node, a source
checkout, and a server-side desktop are not required to run the installed app.

## Install with pipx

Install pipx using your system's package manager or the
[official pipx instructions](https://pipx.pypa.io/stable/installation/).
For example, on Ubuntu/Debian with administrator access:

```bash
sudo apt install pipx python3-venv
```

Then install Research Flow as your regular user:

```bash
pipx install https://github.com/SpicyChicken6/research-flow/releases/download/v0.8.6/research_flow-0.8.6-py3-none-any.whl
pipx ensurepath
```

Reopen the terminal if necessary, then check `research-flow --version`.
The wheel and PyYAML dependency are downloaded during installation. There is no
frontend build and the running app does not fetch external assets.
The package is distributed through GitHub Releases, not PyPI; use the full URL.

## Select where to save

For automatic selection, run inside your research folder on the Linux server:

```bash
cd ~/research/my-study
research-flow
```

- One `.yaml` or `.yml` file in that folder: open it.
- No YAML files: ask before creating a blank `workflow.yaml` there (default: Yes).
- Several YAML files: stop and ask you to choose with `--project`.

When prompted, press Enter or enter `y` to create the file. Enter `n`, or press
Esc or Ctrl+C to cancel without creating files. For scripts or services, use `research-flow --init` to explicitly
allow creation; a noninteractive launch without it exits instead of creating a file.

Discovery only examines this directory, not subfolders. The selected file must
validate as a Research Flow workflow. Invalid or unrelated YAML is not overwritten,
and opening an existing workflow does not rewrite it before you click **Save**.
Changing your shell directory later does not change an already running instance.

To select a path explicitly from any folder:

```bash
research-flow --project "$HOME/research/my-study/workflow.yaml" --init
```

The parent directories are created if necessary. `--init` creates a blank YAML only
when missing; it never overwrites an existing file. Later launches can omit `--init`:

```bash
research-flow --project "$HOME/research/my-study/workflow.yaml"
```

Click **Save** in the interface to write to that exact file on the server.
Use an absolute path to make the destination independent of the launch directory.
Relative `--project` paths are resolved against the terminal's current directory.
Each server instance edits one YAML file.

**Upgrading from 0.8.0/0.8.1:** those versions used a global default data directory.
To continue that workflow, pass
`--project "$HOME/.local/share/research-flow/project.yaml"` (or your previous
`XDG_DATA_HOME` location). Version 0.8.2 does not move or delete it and no longer
uses `XDG_DATA_HOME` to choose the default. Update existing service commands to
include an explicit `--project` path before restarting them.

The app keeps the 20 most recent backups in `.research-flow/backups/<filename>/`
next to your YAML. The access token also lives in that adjacent `.research-flow`
directory. Neither belongs in a public repository.

## Open inside VS Code over Remote-SSH

Connect to the Linux server with VS Code Remote-SSH. In VS Code's settings JSON,
add these settings (merge them into your existing settings):

```json
{
  "workbench.browser.enableRemoteProxy": true,
  "workbench.browser.dataStorage": "workspace"
}
```

1. Run `research-flow` in the remote terminal from your research folder and keep it running.
2. Run **Browser: Open Integrated Browser** from the Command Palette.
3. Paste the complete private URL printed by the app, including `#token=...`.
4. Check that the browser address bar shows the remote indicator.

VS Code carries browser traffic over the existing remote connection. Use the
original server port (normally **8765**); no Ports-panel setup or `--browser-port`
option is needed. Reopen the browser tab after changing these settings.
Remote browser access is currently a VS Code preview feature. If the settings are
unavailable, update VS Code or use the [optional SSH setup](linux.md#other-browsers-optional).

Use the running app URL. Opening a portable HTML export provides **Save copy** and
does not write the server YAML. Older iframe-based previews may be blocked by the
app's frame protection; use the current integrated browser or a normal browser.
The terminal directory at launch controls automatic discovery. VS Code's open
workspace alone does not select the YAML, and changing it does not switch projects.

Recover the URL for an existing running instance with the same project/port options:

```bash
research-flow --project "$HOME/research/my-study/workflow.yaml" --print-url
```

Reference: [VS Code browser remote connections](https://code.visualstudio.com/docs/debugtest/integrated-browser#_browse-over-remote-connections).

## Alternative: install without pipx

Create a dedicated virtual environment, then install the release into it:

```bash
python3 -m venv "$HOME/.local/share/research-flow-env"
"$HOME/.local/share/research-flow-env/bin/python" -m pip install \
  https://github.com/SpicyChicken6/research-flow/releases/download/v0.8.6/research_flow-0.8.6-py3-none-any.whl
"$HOME/.local/share/research-flow-env/bin/research-flow" --project "$HOME/research/my-study/workflow.yaml" --init
```

The installed environment also supports `python -m research_flow`.

## Update or uninstall

Save your edits and stop the running server before updating. Download a newer wheel
from [Releases](https://github.com/SpicyChicken6/research-flow/releases), then use
`pipx install --force /absolute/path/to/the-new-wheel.whl`. Restart with the same
`--project` path. A version-specific URL stays on that version; `pipx upgrade` will
not discover a new release from a pinned wheel URL.

To follow the development branch instead (requires Git):

```bash
pipx install 'git+https://github.com/SpicyChicken6/research-flow.git'
# Later:
pipx upgrade research-flow
```

If replacing an existing installation with the development branch, add `--force`
to that install command. Development-branch updates may change more frequently.

Stop the server and run `pipx uninstall research-flow` to remove the app. Your
workflow files, backups and tokens remain in their data directory.
