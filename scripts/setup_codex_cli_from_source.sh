#!/usr/bin/env bash
set -euo pipefail

repo_url="${CODEX_CLI_REPO_URL:-https://github.com/openai/codex.git}"
source_path="${CODEX_CLI_SOURCE_PATH:-$HOME/Projects/openai-codex}"
install_dir="${CODEX_CLI_INSTALL_DIR:-$HOME/.local/bin}"

if [[ -d "$source_path/.git" ]]; then
  git -C "$source_path" pull --ff-only
else
  mkdir -p "$(dirname "$source_path")"
  git clone "$repo_url" "$source_path"
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "Rust cargo is required to build Codex CLI from source." >&2
  echo "Use scripts/install_codex_cli_from_github_release.sh if GitHub release assets are available." >&2
  exit 1
fi

cd "$source_path/codex-rs"
cargo build --release --bin codex

mkdir -p "$install_dir"
install -m 0755 "$source_path/codex-rs/target/release/codex" "$install_dir/codex"

echo "Built and installed Codex CLI to $install_dir/codex"
echo "Add this to your shell profile if needed:"
echo "  export PATH=\"$install_dir:\$PATH\""
echo
"$install_dir/codex" --version
