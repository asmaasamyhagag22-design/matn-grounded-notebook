#!/usr/bin/env bash
# Live topic research, then a verifiable deck from the saved result (deck v2; zero new model calls).
# Usage: ./live-deck.sh "<topic>" "<audience>"   (env: as live.sh, plus MATN_DECK_TEMPLATE, MATN_DECK_FONTS)
# live.sh itself is unchanged (its hash is part of the delivery freeze); this wrapper only adds the deck step.
set -uo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd); cd "$root"
topic=${1:?topic required}; audience=${2:?audience required}
py="$root/.venv/bin/python"
slug=$(printf '%s' "$topic" | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '-' | cut -c1-48)
out=${MATN_LIVE_OUT:-out/live/$(date +%Y%m%d-%H%M%S)-$slug}
MATN_LIVE_OUT="$out" "$root/live.sh" "$topic" "$audience"
rc=$?
if [ -f "$out/v1.json" ] || [ -f "$out/projection.json" ]; then
  echo "== Deck (from the saved result; no model calls)"
  "$py" -B -m matn_deck from-result "$out" --out "$out/deck" --fonts "${MATN_DECK_FONTS:-office}" \
    ${MATN_DECK_TEMPLATE:+--template "$MATN_DECK_TEMPLATE"}
  echo "== Deck: $root/$out/deck/deck.pdf (QA: $root/$out/deck/deck_qa.html)"
else
  echo "== No verified result to build a deck from."
fi
exit $rc
