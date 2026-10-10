#!/usr/bin/env bash
# Rebuild the Ubuntu 24.04 / CPython 3.12 environments from the recorded Linux wheelhouse.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
[[ $(python3.12 -c 'import sys; print(sys.version_info[:2] == (3, 12))') == True ]]
(cd wheelhouse && sha256sum -c "$repo/requirements/linux-wheelhouse-sha256.txt")
for pair in '.venv main requirements-linux.lock.txt' '.venv-ocr-rapid rapidocr requirements-ocr-rapid-linux.lock.txt' '.venv-ocr paddle requirements-ocr-linux.lock.txt'; do
    read -r environment wheels lock <<< "$pair"
    if [[ -d "$environment" && ! -x "$environment/bin/python" ]]; then
        echo "Existing environment is not Linux: $environment; preserve or remove it explicitly first." >&2
        exit 1
    fi
    [[ -x "$environment/bin/python" ]] || python3.12 -m venv "$environment"
    "$environment/bin/python" -m pip install --no-index --find-links "wheelhouse/linux/$wheels" -r "$lock"
    "$environment/bin/python" -m pip check
done
