#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
python -B -m pytest tests checks -q -p no:cacheprovider -m "not slow"
