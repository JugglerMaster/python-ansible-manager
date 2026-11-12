#!/bin/bash
# Dev launcher for ansiblecli.
#
# Renamed from ansiblecli.sh → acli.sh so it no longer collides with the
# ansiblecli/ package directory on shell tab-completion.
#
# Usage:   ./acli.sh [args...]        (same as the installed `ansiblecli`)
# Or just: make run
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"

if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -e "$DIR"
fi

# Re-install automatically if the package isn't present (e.g. fresh venv).
if ! "$VENV/bin/python" -c "import ansiblecli" 2>/dev/null; then
    echo "Installing ansiblecli into $VENV..."
    "$VENV/bin/pip" install -e "$DIR"
fi

exec "$VENV/bin/ansiblecli" "$@"
