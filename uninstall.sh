#!/usr/bin/env bash
# wordtrack uninstaller. Safe to run as:
#   curl -fsSL https://raw.githubusercontent.com/juliusmarkwei/wordtrack/main/uninstall.sh | bash
set -euo pipefail

WORDTRACK_INSTALL_DIR="${WORDTRACK_INSTALL_DIR:-$HOME/.wordtrack}"
BIN_DIR="$HOME/.local/bin"
SYMLINK="${BIN_DIR}/wordtrack"

log() { printf '%s\n' "$*"; }

removed_any=0

if [ -e "$SYMLINK" ] || [ -L "$SYMLINK" ]; then
  rm -f "$SYMLINK"
  log "Removed ${SYMLINK}"
  removed_any=1
fi

if [ -d "$WORDTRACK_INSTALL_DIR" ]; then
  rm -rf "$WORDTRACK_INSTALL_DIR"
  log "Removed ${WORDTRACK_INSTALL_DIR}"
  removed_any=1
fi

if [ "$removed_any" -eq 0 ]; then
  log "wordtrack does not appear to be installed (nothing found at ${WORDTRACK_INSTALL_DIR} or ${SYMLINK})."
else
  log "wordtrack has been uninstalled."
fi
