#!/usr/bin/env bash
set -euo pipefail

name="nc-cli"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      name="${2:?--name requires a value}"
      shift 2
      ;;
    --as-nc)
      name="nc"
      shift
      ;;
    -h|--help)
      cat <<'HELP'
Usage: ./install.sh [--name nc-cli|NAME] [--as-nc]

Installs the CLI into ~/.local/bin.
Default command name is `nc-cli` to avoid clobbering netcat's common `nc` binary.
Use --as-nc only if you intentionally want the command to be named `nc`.
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
install -m 0755 "$(dirname "$0")/bin/nc-cli" "$HOME/.local/bin/$name"
echo "Installed: $HOME/.local/bin/$name"
echo 'Make sure ~/.local/bin is in PATH.'
