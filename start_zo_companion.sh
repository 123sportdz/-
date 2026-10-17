#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -x ".venv/bin/python" ]]; then
  exec ".venv/bin/python" zo_companion.py connect
fi
if command -v python3 >/dev/null 2>&1; then
  exec python3 zo_companion.py connect
fi
printf 'Python 3 is required to start the Zo companion.\n' >&2
exit 1
