#!/usr/bin/env bash
# Launch mpkloop from anywhere.
here="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$here" && exec "$here/.venv/bin/python" -m mpkloop "$@"
