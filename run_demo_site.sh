#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# MATN_FONT_DIR is inherited or loaded from the owner's development environment; no font path is embedded here.
source "$repo/scripts/dev_environment.sh"
cd "$repo"
[[ -f out/demo/manifest.json ]] || { echo 'Demo cache missing: follow docs/DEMO_RUNBOOK.md' >&2; exit 1; }
index=out/demo_site/index.html
if [[ ! -f "$index" ]] || [[ app/site/build_site.py -nt "$index" ]] || [[ app/site/build_assets.py -nt "$index" ]] || [[ out/demo/manifest.json -nt "$index" ]] || [[ design/templates/src/gallery.json -nt "$index" ]]; then
    "$repo/.venv/bin/python" -m app.site.build_site
fi
exec xdg-open "$repo/$index"
