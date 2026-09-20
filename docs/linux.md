# Remote Linux deployment

## 1. Install and launch

For the installed `research-flow` command, begin with [the installation guide](install.md).
It supports all server options shown below; replace `bash start.sh` with
`research-flow`. The source-checkout launcher remains available as follows.

Use a user-owned application directory, for example `~/apps/research-flow`.
Keep project data elsewhere. Run as your regular account, not root.

```bash
cd ~/research/my-project
bash ~/apps/research-flow/start.sh
```

This opens the only YAML in your current research folder, or asks before creating `workflow.yaml`
if none exists. Press Enter to create it, or press Esc to cancel. Use `--init` to
allow creation without a prompt. Multiple YAML files require an explicit choice.
For an existing plan from the application source folder:

```bash
bash start.sh --project "$HOME/research/my-project/project.yaml"
```

For a new plan at a chosen path:

```bash
bash start.sh --project "$HOME/research/my-project/project.yaml" --init
```

A shell with no desktop is sufficient. `--open` explicitly opens a browser for
local use; headless startup is the default. `--no-open` remains accepted for
compatibility. The one runtime dependency is PyYAML. On managed systems, use a
Python environment approved by your administrator instead of changing system Python:

```bash
python -m pip install .
python server.py --project /absolute/path/to/project.yaml
```

## 2. Open the interface

In VS Code Remote-SSH, follow the [integrated browser setup](install.md#open-inside-vs-code-over-remote-ssh)
and open the app's original private URL. With browser remote access enabled, VS Code
uses your existing remote connection; no manual forwarding is needed.

### Other browsers (optional)

For a browser on your own computer without VS Code remote access, create an SSH tunnel:

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 127.0.0.1:8765:127.0.0.1:8765 YOUR_USER@YOUR_SERVER
```

Open the private access URL from the server terminal in your local browser. The
`#token=…` fragment is consumed by the frontend and removed from the visible URL.
The SSH tunnel carries traffic; no firewall opening or `0.0.0.0` binding is needed.

If the server warns that port 8765 is occupied, use its selected port in the tunnel
instead. For example, if it selected 8766, use
`-L 127.0.0.1:8766:127.0.0.1:8766` and open the newly printed URL. With an explicit
`--browser-port`, keep that local port and update the tunnel's server destination.

When local port 8765 is occupied, configure **both** ends explicitly:

```bash
# On the server
bash start.sh --port 8765 --browser-port 18765

# On your computer
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 127.0.0.1:18765:127.0.0.1:8765 YOUR_USER@YOUR_SERVER
```

Now the private URL uses local port 18765. The extra option maintains narrow Host
validation rather than accepting arbitrary hostnames. Repeat `--project` for a
custom project in all server commands. For an SSH jump host, use your normal approved
SSH configuration or `-J YOUR_USER@YOUR_BASTION`; do not disable host-key checking.

On a shared cluster, obtain approval to run a listening process. Some login nodes
forbid long-running web applications. Follow the cluster's job/scheduling policy;
this package does not bypass it.

## 3. Keep it running (optional)

A foreground process stops when you close its terminal. For initial testing, keep
that terminal open or use an existing `tmux` session. For persistent use on a machine
with user services, edit the template at `deploy/research-flow.service` to match your
application directory and chosen project.

```bash
mkdir -p ~/.config/systemd/user
cp deploy/research-flow.service ~/.config/systemd/user/research-flow.service
# Edit the installed unit if the app is not under ~/apps/research-flow.
systemctl --user daemon-reload
systemctl --user enable --now research-flow
systemctl --user status research-flow
```

Set up the virtual environment with `bash start.sh` once, then stop that foreground
instance before starting the service. The service uses the existing environment;
it does not download dependencies during startup. The default template explicitly
selects `~/.local/share/research-flow/project.yaml` and initializes it only if missing.
Edit its `--project` argument to use a different workflow. Update older installed
service files to include an explicit path before upgrading to 0.8.2.

Retrieve the URL without starting another server:

```bash
bash start.sh --project "$HOME/.local/share/research-flow/project.yaml" --print-url
```

For a service with custom `--project`, `--port`, `--browser-port`, or `--token-file`,
repeat those flags with `--print-url`. Do not paste the resulting URL into issues or
shared logs. The service journal itself contains the startup access URL, so treat
it as private. User services may stop on logout unless lingering is enabled; ask the
administrator before changing that policy. The service template is optional and
must be checked against the target machine. It has not been installed on your server.

If startup moved from port 8765 to another port, pass that actual port with
`--port` when recovering the URL.

## Stop and update

Save browser edits first. Stop with Ctrl+C or:

```bash
systemctl --user stop research-flow
```

For the installed command, update with:

```bash
research-flow --update
```

For a source checkout, update from its launcher:

```bash
bash ~/apps/research-flow/start.sh --update
systemctl --user restart research-flow
```

The updater follows official `main` and exits. Source checkouts must be clean and
on `main`; installed copies update through pipx or their own Python's pip. See the
[update guide](install.md#update-or-uninstall) for requirements and older versions.

Do not run two Research Flow instances against one project. Updates do not migrate data on disk
until you explicitly Save from the browser.

## Access token and backups

The default token path is `.research-flow/<project-filename>.token` next to the
project. A new token file is owner-readable only (mode 600) and persists across
restarts. The server refuses world/group-readable token files. A custom token file
can be chosen with `--token-file /absolute/private/path.token`.

To rotate access: stop the server, remove that token file, then restart. A new token
is created; reopen the newly printed URL in the browser. Stop first because a running
process keeps its old token in memory. Root and your own account remain trusted.

The 20 most recent saves have backups in `.research-flow/backups/<filename>/`.
To restore: stop the app, retain a copy of the current file, copy the desired backup
to the selected project path, then restart. A backup directory on the same disk is
not protection against disk loss; include it in your normal private backups.

## Troubleshooting

**Unauthorized / private URL required:** use the complete URL containing the token,
not just `http://127.0.0.1:8765`. Recover it using `--print-url`.

**403 / localhost access:** in VS Code, enable browser remote access as described
above and paste the original server URL, rather than a rewritten local port URL.
Check for the remote indicator. If using an SSH tunnel with another browser, use
`127.0.0.1` or `localhost` and set `--browser-port` when the ports differ.
Direct remote-host access and public reverse-proxy hosting are not supported.

**Default port already in use:** the app warns and automatically selects the next
available port after 8765. Open the newly printed URL. If using an SSH tunnel,
update its destination port too. Other explicit `--port` values stay fixed; choose
another port if one is occupied. Do not kill unrelated processes.

**No venv/ensurepip:** install your distribution's Python venv package or use an
existing Python 3.10+ environment. No sudo is needed by Research Flow itself.

**File changed elsewhere:** download the browser draft first, inspect the on-disk
change, and use Reload when it is safe. There is no automatic merge.

**Blank project after upgrading:** version 0.8.2 defaults to the launch directory.
Restart with `--project /path/to/your/old/project.yaml`. The old global default was
`~/.local/share/research-flow/project.yaml` (or under `XDG_DATA_HOME`); it has not
been moved, deleted or overwritten.

**Multiple YAML files:** choose the workflow explicitly with
`research-flow --project ./my-study.yaml`. Configuration YAML files also count
during discovery; the app does not guess which one you intended.

## References

- [OpenSSH forwarding options](https://man.openbsd.org/ssh.1)
- [Python http.server limitations](https://docs.python.org/3/library/http.server.html)
- [systemd user service documentation](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [GitHub CLI repository creation](https://cli.github.com/manual/gh_repo_create)
