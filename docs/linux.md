# Remote Linux deployment

## 1. Install and launch

Use a user-owned application directory, for example `~/apps/research-flow`.
Keep project data elsewhere. Run as your regular account, not root.

```bash
cd ~/apps/research-flow
bash start.sh
```

For an existing plan:

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
python -m pip install -r requirements.txt
python server.py --project /absolute/path/to/project.yaml
```

## 2. Forward the port from your computer

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 127.0.0.1:8765:127.0.0.1:8765 YOUR_USER@YOUR_SERVER
```

Open the private access URL from the server terminal in your local browser. The
`#token=…` fragment is consumed by the frontend and removed from the visible URL.
The SSH tunnel carries traffic; no firewall opening or `0.0.0.0` binding is needed.

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
it does not download dependencies during startup. The default template uses the
external user-data project.

Retrieve the URL without starting another server:

```bash
bash start.sh --print-url
```

For a service with custom `--project`, `--port`, `--browser-port`, or `--token-file`,
repeat those flags with `--print-url`. Do not paste the resulting URL into issues or
shared logs. The service journal itself contains the startup access URL, so treat
it as private. User services may stop on logout unless lingering is enabled; ask the
administrator before changing that policy. The service template is optional and
must be checked against the target machine. It has not been installed on your server.

## Stop and update

Save browser edits first. Stop with Ctrl+C or:

```bash
systemctl --user stop research-flow
```

After publishing the repository, normal updates are:

```bash
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
systemctl --user restart research-flow
```

Do not run these inside the directory containing research data. Do not run two
Research Flow instances against one project. Updates do not migrate data on disk
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

**403 / localhost access:** use `127.0.0.1` or `localhost` in your browser, and set
`--browser-port` when the local and remote ports differ. Direct remote-host access
and reverse-proxy hosting are not supported by this release.

**Address already in use:** stop the previous instance or select another `--port`;
forward that server port from your computer. Do not kill unrelated processes.

**No venv/ensurepip:** install your distribution's Python venv package or use an
existing Python 3.10+ environment. No sudo is needed by Research Flow itself.

**File changed elsewhere:** download the browser draft first, inspect the on-disk
change, and use Reload when it is safe. There is no automatic merge.

**Blank project after upgrading:** the new default is outside the source tree.
Restart with `--project /path/to/your/old/project.yaml`; your original file has not
been deleted or overwritten.

## References

- [OpenSSH forwarding options](https://man.openbsd.org/ssh.1)
- [Python http.server limitations](https://docs.python.org/3/library/http.server.html)
- [systemd user service documentation](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [GitHub CLI repository creation](https://cli.github.com/manual/gh_repo_create)
