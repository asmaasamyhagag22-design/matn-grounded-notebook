#!/usr/bin/env bash
# Live topic research for a meeting: preflight -> Matn v2 live preset -> progress view.
# Usage: ./live.sh "<topic>" "<audience>" [--deck] (env: MATN_LIVE_LEDGER, MATN_LIVE_OUT, MATN_OPEN=1)
# Runs as its own process; the frozen gallery stays usable while it works.
set -uo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd); cd "$root"
source "$root/scripts/dev_environment.sh"
topic=${1:?topic required}; audience=${2:?audience required}; deck=${3:-}
py=${MATN_PYTHON:-"$root/.venv/bin/python"}
ledger=${MATN_LIVE_LEDGER:-out/leap-20261030/ledger}
slug=$(printf '%s' "$topic" | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '-' | cut -c1-48)
out=${MATN_LIVE_OUT:-out/live/$(date +%Y%m%d-%H%M%S)-$slug}
mkdir -p "$out"
echo "== Preflight"
if ! "$py" -B -m matn_research.preflight --preload --out "$out/preflight.json" --progress "$out/progress.html"; then
  echo "NO-GO: use the frozen gallery (bash out/leap-20261030/demo-check-v4.sh, then open gallery v4)."; exit 2
fi
ledger_dir="$ledger" "$py" - "$out/planned.json" <<'PY'
import json, os, sys, time
from pathlib import Path
ledger = Path(os.environ['ledger_dir']) / 'ledger.json'
before = json.loads(ledger.read_bytes())['calls'] if ledger.exists() else {}
Path(sys.argv[1]).write_text(json.dumps(dict(generation=7, native=60, ledger_before=before, started_at=time.time())))
PY
"$py" -B -m matn_research.progress --folder "$out" --ledger "$ledger" --out "$out" --planned "$out/planned.json" --watch --interval 3 &
sidecar=$!
trap 'kill $sidecar 2>/dev/null' EXIT
echo "== Progress view: $root/$out/progress.html"
[ "${MATN_OPEN:-0}" = 1 ] && command -v xdg-open >/dev/null && xdg-open "$out/progress.html" >/dev/null 2>&1 &
echo "== Live run (Matn v2 preset)"
"$py" -B -m matn_research live --out "$out" --topic "$topic" --audience "$audience" --ledger "$ledger" \
  --preset matn_research/live_preset.json --timeout 1200
rc=$?
"$py" -B -m matn_research.progress --folder "$out" --ledger "$ledger" --out "$out" --planned "$out/planned.json" --quiet >/dev/null
echo "== Result: $root/$out/index.html (exit $rc)"
if [ "$deck" = "--deck" ] && { [ -f "$out/v1.json" ] || [ -f "$out/projection.json" ]; }; then
  "$py" -B -m matn_deck from-result "$out" --out "$out/deck" --fonts "${MATN_DECK_FONTS:-office}"
  echo "== Deck: $root/$out/deck/deck.pdf"
fi
exit $rc
