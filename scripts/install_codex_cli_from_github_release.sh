#!/usr/bin/env bash
set -euo pipefail

install_dir="${CODEX_CLI_INSTALL_DIR:-$HOME/.local/bin}"
release_base_url="${CODEX_CLI_RELEASE_BASE_URL:-https://github.com/openai/codex/releases/latest/download}"

case "$(uname -m)" in
  arm64|aarch64)
    archive="codex-aarch64-apple-darwin.tar.gz"
    binary_name="codex-aarch64-apple-darwin"
    ;;
  x86_64|amd64)
    archive="codex-x86_64-apple-darwin.tar.gz"
    binary_name="codex-x86_64-apple-darwin"
    ;;
  *)
    echo "Unsupported macOS architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

mkdir -p "$install_dir"
curl -fL "$release_base_url/$archive" -o "$tmp_dir/$archive"
tar -xzf "$tmp_dir/$archive" -C "$tmp_dir"

candidate="$tmp_dir/$binary_name"
if [[ ! -f "$candidate" ]]; then
  candidate="$(find "$tmp_dir" -type f -name 'codex*' -print -quit)"
fi

if [[ ! -f "$candidate" ]]; then
  echo "Could not find a codex binary inside $archive" >&2
  exit 1
fi

install -m 0755 "$candidate" "$install_dir/codex"

echo "Installed Codex CLI to $install_dir/codex"
echo "Add this to your shell profile if needed:"
echo "  export PATH=\"$install_dir:\$PATH\""
echo
"$install_dir/codex" --version
