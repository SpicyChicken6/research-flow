#!/usr/bin/env bash
# Headless launch. Resolve code relative to this script, data outside the checkout.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
VENV="${RESEARCH_FLOW_VENV:-$ROOT/.venv}"
command -v "$PYTHON" >/dev/null || { echo 'Python 3.10+ is required.' >&2; exit 1; }
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10+ is required")'
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV" || {
    echo 'Cannot create a virtual environment. Install your distro venv package or use an existing environment.' >&2
    exit 1
  }
fi
if ! "$VENV/bin/python" -c 'import yaml; assert (6, 0, 2) <= tuple(map(int, yaml.__version__.split("."))) < (7,)' 2>/dev/null; then
  "$VENV/bin/python" -m pip install "$ROOT"
fi
exec "$VENV/bin/python" "$ROOT/server.py" "$@"
