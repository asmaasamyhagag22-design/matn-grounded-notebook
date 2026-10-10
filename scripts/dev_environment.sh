#!/usr/bin/env bash
# Development settings are external to the repository. Explicit environment values take precedence.
matn_dev_config="${XDG_CONFIG_HOME:-$HOME/.config}/matn/dev.env"
if [[ -z ${MATN_FONT_DIR:-} && -f "$matn_dev_config" ]]; then
    source "$matn_dev_config"
fi
export MATN_FONT_DIR="${MATN_FONT_DIR:-}"
if [[ -n "$MATN_FONT_DIR" && ! -d "$MATN_FONT_DIR" ]]; then
    echo 'MATN_FONT_DIR is unavailable. Mount the development font source read-only; see docs/ocr_setup.md.' >&2
    return 1
fi
unset matn_dev_config
