#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# MATN_FONT_DIR is inherited or loaded from the owner's development environment; no font path is embedded here.
source "$repo/scripts/dev_environment.sh"
if (( $# == 0 )); then echo 'Usage: read_pdf.sh PDF [--out DIR] [--milestone]' >&2; exit 2; fi
pdf=$(realpath -- "$1")
shift
cd "$repo"
exec "$repo/.venv/bin/python" -m matn_reading read "$pdf" "$@"
