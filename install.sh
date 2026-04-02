#!/bin/sh
set -eu

REPO="yanodincov/devpipe"
INSTALL_ROOT="${HOME}/.devpipe"
VENV_DIR="${INSTALL_ROOT}/venv"
BIN_DIR="${HOME}/.local/bin"
LAUNCHER="${BIN_DIR}/devpipe"
CONFIG_FILE="${INSTALL_ROOT}/config.yaml"
REF="${DEVPIPE_REF:-main}"

log() {
  printf '%s\n' "$1"
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

require_python() {
  command -v python3 >/dev/null 2>&1 || fail "python3 is required"
  python3 -m venv --help >/dev/null 2>&1 || fail "python3 venv support is required"
}

source_url() {
  case "$REF" in
    main)
      printf 'https://github.com/%s/archive/refs/heads/main.tar.gz\n' "$REPO"
      ;;
    *)
      printf 'https://github.com/%s/archive/refs/tags/%s.tar.gz\n' "$REPO" "$REF"
      ;;
  esac
}

ensure_launcher() {
  mkdir -p "$BIN_DIR"
  cat >"$LAUNCHER" <<EOF
#!/bin/sh
exec "$VENV_DIR/bin/devpipe" "\$@"
EOF
  chmod +x "$LAUNCHER"
}

ensure_config() {
  mkdir -p "$INSTALL_ROOT"
  if [ ! -f "$CONFIG_FILE" ]; then
    cat >"$CONFIG_FILE" <<'EOF'
defaults:
  runner: auto
engines:
  codex:
    model:
      low: gpt-5.4-mini
      middle: gpt-5.3-codex
      high: gpt-5.4
    effort:
      low: low
      middle: medium
      high: high
      extra: xhigh
  claude:
    model:
      low: haiku
      middle: sonnet
      high: opus
    effort:
      low: low
      middle: medium
      high: high
      extra: high
EOF
  fi
}

append_once() {
  file="$1"
  line="$2"
  mkdir -p "$(dirname "$file")"
  touch "$file"
  if ! grep -F "$line" "$file" >/dev/null 2>&1; then
    printf '\n%s\n' "$line" >>"$file"
  fi
}

configure_shell() {
  shell_name="$(basename "${SHELL:-}")"
  case "$shell_name" in
    zsh)
      "$LAUNCHER" install-completion zsh >/dev/null
      append_once "${HOME}/.zshrc" 'export PATH="$HOME/.local/bin:$PATH"'
      append_once "${HOME}/.zshrc" 'fpath+=("$HOME/.zsh/completions")'
      append_once "${HOME}/.zshrc" 'autoload -Uz compinit && compinit'
      ;;
    bash)
      "$LAUNCHER" install-completion bash >/dev/null
      append_once "${HOME}/.bashrc" 'export PATH="$HOME/.local/bin:$PATH"'
      ;;
  esac
}

main() {
  require_python

  url="$(source_url)"
  log "Installing devpipe from $url"

  mkdir -p "$INSTALL_ROOT"
  if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
  fi

  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null
  "$VENV_DIR/bin/python" -m pip install --upgrade "$url"

  ensure_launcher
  ensure_config
  configure_shell

  log ""
  log "Installed: $LAUNCHER"
  log "Config: $CONFIG_FILE"
  log "Run: devpipe doctor"
  log "If needed, add ~/.local/bin to PATH in your shell profile."
}

main "$@"
