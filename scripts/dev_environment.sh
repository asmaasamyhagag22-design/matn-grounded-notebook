#!/usr/bin/env bash
# Development settings are external to the repository. Explicit environment values take precedence.
# Fonts are vendored (design/fonts, OFL-1.1); MATN_FONT_DIR is no longer read or required (ADR-0019).
matn_dev_config="${XDG_CONFIG_HOME:-$HOME/.config}/matn/dev.env"
if [[ -f "$matn_dev_config" ]]; then
    source "$matn_dev_config"
fi
unset MATN_FONT_DIR matn_dev_config
