#!/usr/bin/env bash
set -euo pipefail

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      cat <<'HELP'
Usage: ./install.sh

Installs the CLI into ~/.local/bin as `nc-cli`.
The project intentionally does not install an `nc` alias, because `nc` is commonly netcat on Unix systems.
HELP
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$HOME/.local/bin"
install -m 0755 "$(dirname "$0")/bin/nc-cli" "$HOME/.local/bin/nc-cli"
echo "Installed: $HOME/.local/bin/nc-cli"
echo 'Make sure ~/.local/bin is in PATH.'
