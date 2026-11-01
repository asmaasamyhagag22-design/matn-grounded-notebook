#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$root"
source "$root/scripts/dev_environment.sh"
export PYTHONDONTWRITEBYTECODE=1
exec systemd-inhibit --what=sleep:idle:handle-lid-switch --why='Matn local app' "${MATN_PYTHON:-$root/.venv/bin/python}" -B -m matn_app "$@"
