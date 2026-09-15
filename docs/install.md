# Install Research Flow

Research Flow 0.8.1 installs a `research-flow` command. It runs a small Python server
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
pipx install https://github.com/SpicyChicken6/research-flow/releases/download/v0.8.1/research_flow-0.8.1-py3-none-any.whl
pipx ensurepath
```

Reopen the terminal if necessary, then check `research-flow --version`.
The wheel and PyYAML dependency are downloaded during installation. There is no
frontend build and the running app does not fetch external assets.
The package is distributed through GitHub Releases, not PyPI; use the full URL.

## Select where to save

Run from any folder on the Linux server:

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
Without `--project`, the default is `~/.local/share/research-flow/project.yaml`,
respecting `XDG_DATA_HOME` if set. Each server instance edits one YAML file.

The app keeps the 20 most recent backups in `.research-flow/backups/<filename>/`
next to your YAML. The access token also lives in that adjacent `.research-flow`
directory. Neither belongs in a public repository.

## Open inside VS Code over Remote-SSH

1. Connect to the Linux server with VS Code Remote-SSH.
2. Run the command above in its remote terminal and keep it running.
3. In the **Ports** panel, forward remote port **8765** to local port **8765**.
4. Copy the complete private URL from the server output, including `#token=...`.
5. Run **Browser: Open Integrated Browser** from the Command Palette and paste it.

Use the running app URL. Opening a portable HTML export provides **Save copy** and
does not write the server YAML. Older iframe-based previews may be blocked by the
app's frame protection; use the current integrated browser or a normal browser.
VS Code's open workspace folder has no effect on the selected YAML path.

If VS Code forwards to a different local port, such as 18765, restart with:

```bash
research-flow --project "$HOME/research/my-study/workflow.yaml" --browser-port 18765
```

Forward remote 8765 to local 18765 and use the newly printed URL. For manual SSH
forwarding, service setup, and troubleshooting, see [the Linux guide](linux.md).
Recover the URL for an existing running instance with the same project/port options:

```bash
research-flow --project "$HOME/research/my-study/workflow.yaml" --print-url
```

References: [VS Code SSH forwarding](https://code.visualstudio.com/docs/remote/ssh#_forwarding-a-port-creating-ssh-tunnel),
[VS Code integrated browser](https://code.visualstudio.com/docs/debugtest/integrated-browser).

## Alternative: install without pipx

Create a dedicated virtual environment, then install the release into it:

```bash
python3 -m venv "$HOME/.local/share/research-flow-env"
"$HOME/.local/share/research-flow-env/bin/python" -m pip install \
  https://github.com/SpicyChicken6/research-flow/releases/download/v0.8.1/research_flow-0.8.1-py3-none-any.whl
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
