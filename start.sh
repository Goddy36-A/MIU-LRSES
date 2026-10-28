#!/bin/sh
# One command for macOS/Linux: set up on first run, then start the system.
cd "$(dirname "$0")" || exit 1
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
if [ ! -f .setup_done ]; then
  "$PY" setup_local.py || exit 1
fi
exec ./venv/bin/python run_server.py "$@"
