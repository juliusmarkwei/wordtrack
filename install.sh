#!/usr/bin/env bash
# wordtrack installer. Safe to run as:
#   curl -fsSL https://raw.githubusercontent.com/juliusmarkwei/wordtrack/main/install.sh | bash
set -euo pipefail

WORDTRACK_REPO_OWNER="${WORDTRACK_REPO_OWNER:-juliusmarkwei}"
WORDTRACK_REPO_NAME="${WORDTRACK_REPO_NAME:-wordtrack}"
WORDTRACK_REPO_BRANCH="${WORDTRACK_REPO_BRANCH:-main}"
WORDTRACK_INSTALL_DIR="${WORDTRACK_INSTALL_DIR:-$HOME/.wordtrack}"

RAW_BASE="https://raw.githubusercontent.com/${WORDTRACK_REPO_OWNER}/${WORDTRACK_REPO_NAME}/${WORDTRACK_REPO_BRANCH}"
BIN_DIR="$HOME/.local/bin"

log() { printf '%s\n' "$*"; }
err() { printf 'wordtrack install: %s\n' "$*" >&2; }
die() { err "$*"; exit 1; }

# Reads from /dev/tty so this stays safe when piped via `curl | bash`
# (stdin is the script itself in that case, not a terminal).
confirm() {
  local prompt="$1" reply="n"
  if [ -r /dev/tty ]; then
    read -r -p "$prompt [y/N] " reply </dev/tty || reply="n"
  else
    err "no interactive terminal available; assuming 'no' for: $prompt"
  fi
  case "$reply" in
    [yY]|[yY][eE][sS]) return 0 ;;
    *) return 1 ;;
  esac
}

OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="macos" ;;
  Linux) PLATFORM="linux" ;;
  *) die "unsupported OS: $OS (wordtrack supports macOS and Linux only)" ;;
esac

PKG_MANAGER=""
if [ "$PLATFORM" = "linux" ]; then
  if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt"
  elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER="dnf"
  elif command -v pacman >/dev/null 2>&1; then
    PKG_MANAGER="pacman"
  fi
fi

install_with_brew() {
  local formula="$1"
  if ! command -v brew >/dev/null 2>&1; then
    if confirm "Homebrew is required to install '$formula'. Install Homebrew now?"; then
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty
    else
      die "cannot install '$formula' without Homebrew. Install it manually: https://brew.sh"
    fi
  fi
  if confirm "Install '$formula' via Homebrew now?"; then
    brew install "$formula"
  else
    die "'$formula' is required. Install it manually and re-run this script."
  fi
}

install_with_linux_pm() {
  local pkg="$1"
  if [ -z "$PKG_MANAGER" ]; then
    die "no supported package manager found (looked for apt, dnf, pacman). Install '$pkg' manually."
  fi
  if ! confirm "Install '$pkg' via $PKG_MANAGER now? (this will use sudo)"; then
    die "'$pkg' is required. Install it manually and re-run this script."
  fi
  case "$PKG_MANAGER" in
    apt) sudo apt-get update && sudo apt-get install -y "$pkg" ;;
    dnf) sudo dnf install -y "$pkg" ;;
    pacman) sudo pacman -Sy --noconfirm "$pkg" ;;
  esac
}

ensure_dependency() {
  local cmd="$1" macos_formula="$2" linux_pkg="$3"
  if command -v "$cmd" >/dev/null 2>&1; then
    return 0
  fi
  log "'$cmd' was not found."
  if [ "$PLATFORM" = "macos" ]; then
    install_with_brew "$macos_formula"
  else
    install_with_linux_pm "$linux_pkg"
  fi
  command -v "$cmd" >/dev/null 2>&1 || die "failed to install '$cmd'"
}

ensure_dependency python3 python3 python3
ensure_dependency ffmpeg ffmpeg ffmpeg

log "Installing wordtrack into ${WORDTRACK_INSTALL_DIR}..."
mkdir -p "$WORDTRACK_INSTALL_DIR"

for f in wordtrack.py requirements.txt; do
  curl -fsSL "${RAW_BASE}/${f}" -o "${WORDTRACK_INSTALL_DIR}/${f}" \
    || die "failed to download ${f} from ${RAW_BASE}"
done

log "Creating virtual environment..."
python3 -m venv "${WORDTRACK_INSTALL_DIR}/venv"
"${WORDTRACK_INSTALL_DIR}/venv/bin/pip" install --upgrade pip >/dev/null
"${WORDTRACK_INSTALL_DIR}/venv/bin/pip" install -r "${WORDTRACK_INSTALL_DIR}/requirements.txt"

WRAPPER="${WORDTRACK_INSTALL_DIR}/wordtrack"
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
exec "${WORDTRACK_INSTALL_DIR}/venv/bin/python3" "${WORDTRACK_INSTALL_DIR}/wordtrack.py" "\$@"
EOF
chmod +x "$WRAPPER"

mkdir -p "$BIN_DIR"
ln -sf "$WRAPPER" "${BIN_DIR}/wordtrack"

log ""
log "wordtrack installed successfully."

case ":${PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *)
    log ""
    log "NOTE: ${BIN_DIR} is not on your PATH. Add this line to your shell"
    log "profile (e.g. ~/.zshrc or ~/.bashrc), then restart your shell:"
    log ""
    log "    export PATH=\"${BIN_DIR}:\$PATH\""
    ;;
esac

log ""
log "Try it out:"
log "    wordtrack path/to/video.mp4"
