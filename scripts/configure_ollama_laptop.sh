#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo: system-wide Ollama service configuration requires root.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ${1:-} == --recover-models ]]; then
    python3.12 "$repo/scripts/recover_ollama_models.py"
elif (( $# != 0 )); then
    echo "Usage: configure_ollama_laptop.sh [--recover-models]" >&2; exit 2
fi
target=/etc/systemd/system/ollama.service.d/matn-laptop.conf
if [[ -f "$target" ]] && ! cmp -s "$repo/scripts/ollama-laptop.conf" "$target"; then
    echo "Existing configuration differs: $target; preserve and review it before replacement." >&2
    exit 1
fi
install -D -m 644 "$repo/scripts/ollama-laptop.conf" "$target"
systemctl daemon-reload
systemctl restart ollama
systemctl show ollama --property=Environment
