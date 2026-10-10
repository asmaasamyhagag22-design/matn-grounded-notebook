#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# MATN_FONT_DIR is inherited or loaded from the owner's development environment; no font path is embedded here.
source "$repo/scripts/dev_environment.sh"
cd "$repo"
port=${1:-8501}
[[ "$port" =~ ^[0-9]+$ ]] && (( port > 0 && port < 65536 )) || { echo 'Invalid port' >&2; exit 2; }
echo "Matn dashboard: http://127.0.0.1:$port (Ctrl+C to stop)"
exec "$repo/.venv/bin/python" -m streamlit run "$repo/app/dashboard.py" --server.address 127.0.0.1 --server.port "$port" --server.headless true --browser.gatherUsageStats false --global.developmentMode false
