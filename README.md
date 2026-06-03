# codex-launcher

Local proxy wrapper for Codex CLI in restricted enterprise networks.

## Goal

Route Codex traffic through a local proxy that:
- authenticates inbound requests with a local static key,
- initializes enterprise SSL certs via `rbc_security`,
- acquires and refreshes OAuth2 access tokens for upstream calls,
- maps Codex-facing model names to internal model names,
- forces dashboard-selected upstream models,
- forces Responses API `store=false`,
- injects token defaults (`32768`) when callers omit them,
- monitors calls from a local dashboard,
- configures Codex CLI with the proxy provider,
- opens Codex CLI in a new terminal with the proxy API key in process env.

## Current scope

This repo contains:
- profile-based config (`local` / `work`)
- SSL setup helper
- OAuth token manager with refresh scheduling
- model alias mapper
- request normalizers for `/v1/responses` and `/v1/chat/completions`
- direct `/v1/responses` forwarding to a custom Responses-capable base URL
- optional `/v1/chat/completions` forwarding
- in-memory call logging
- dashboard HTML served at `/`
- Codex CLI config and launch helpers
- GitHub-only Codex CLI setup scripts

## Quick Start

1. Create a venv and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Create `.env` from the template and fill values:

```bash
cp .env.example .env
```

3. Set `CODEX_PROXY_PROFILE=work` in `.env` and fill the `WORK_*` values.

4. Edit `models.json` under `profiles.work.models` with Codex-facing model names and upstream model names. The dashboard selects `WORK_CODEX_MODEL` on startup; if that id is missing from `models.json`, the launcher adds a fallback from `.env` instead of silently selecting a local model.

5. Install Codex CLI. The dashboard can do this for you: click **Install/Update CLI**, or click **Launch CLI** and the launcher will install from GitHub first when the CLI is missing.

If you want to run the same install manually, use the release script:

```bash
scripts/install_codex_cli_from_github_release.sh
```

If release assets are blocked but source cloning works and Rust dependencies are available:

```bash
scripts/setup_codex_cli_from_source.sh
```

Make sure `CODEX_CLI_PATH` in `.env` points to the installed binary. If the script installed to `~/.local/bin/codex`, either add `~/.local/bin` to `PATH` or set:

```text
CODEX_CLI_PATH=~/.local/bin/codex
```

6. Optional: set the default folder where CLI sessions should start:

```text
CODEX_WORKSPACE_PATH=/Users/you/Projects/some-repo
```

7. Start proxy/dashboard:

```bash
python -m src.main
```

8. Open the dashboard:

```text
http://127.0.0.1:8765
```

9. Select a model, enter or paste the launch workspace path, configure Codex, and launch Codex CLI from the dashboard. If Codex CLI is missing, launch first attempts a GitHub release install into `~/.local/bin/codex`.

You can still print Codex provider wiring instructions:

```bash
python -m src.launch_codex --profile work
```

You can also configure and launch from the terminal:

```bash
python -m src.launch_codex --profile work --launch
```

To launch from a specific workspace without changing `.env`:

```bash
python -m src.launch_codex --profile work --workspace /Users/you/Projects/some-repo --launch
```

## Debug Responses Upstream

If the proxy reports an upstream error such as `unknown endpoint /responses`, run the diagnostic script. It loads the same `.env` profile, enables `rbc_security` certs when available, acquires OAuth using the configured client credentials, uses the selected work model, and probes likely Responses API URL variants from `WORK_UPSTREAM_BASE_URL`.

```bash
python scripts/debug_responses_endpoint.py --profile work
```

For a safe preview without sending requests:

```bash
python scripts/debug_responses_endpoint.py --profile work --dry-run
```

The script tests paths like:

- configured base + `/responses`
- configured base with trailing `/v1` removed + `/responses`
- configured base with trailing `/v1` removed + `/v1/responses`
- configured base with trailing `/v1` removed + `/openai/v1/responses`
- configured base + `/chat/completions` as a sanity check, unless `--skip-chat-sanity` is set

## Notes

- Set `CODEX_PROXY_PROFILE=local` for local development, `work` for enterprise settings.
- Keep `PROXY_STATIC_API_KEY` local-only; upstream auth should use OAuth2 tokens.
- Secrets stay in `.env`; `~/.codex/config.toml` only stores the proxy provider name, base URL, wire API, and environment variable name.
- The proxy sets `store=false` on `/v1/responses` before forwarding upstream.
- The dashboard launch button opens a macOS Terminal window because Codex CLI is an interactive TUI.
- The proxy API key is injected into the launched CLI process environment and is not written to `~/.codex/config.toml`.
- `CODEX_WORKSPACE_PATH` is only the default. The dashboard launch workspace field can override it for each launch.
- The dashboard can install/update Codex CLI from GitHub Releases. The launcher also checks `~/.local/bin/codex` even if `~/.local/bin` is not on `PATH`.
- If Codex reports `wire_api = chat is no longer supported`, click **Configure** or **Launch CLI** again. The launcher migrates deprecated provider entries in `~/.codex/config.toml` from `chat` to `responses`.
