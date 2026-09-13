#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
python -m space_idle.api --host 0.0.0.0 --port 8765 --save-dir saves
