#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Development settings come from the owner's environment; fonts are vendored in design/fonts (no font path needed).
source "$repo/scripts/dev_environment.sh"
if (( $# == 0 )); then echo 'Usage: read_pdf.sh PDF [--out DIR] [--milestone]' >&2; exit 2; fi
pdf=$(realpath -- "$1")
shift
cd "$repo"
exec "$repo/.venv/bin/python" -m matn_reading read "$pdf" "$@"
