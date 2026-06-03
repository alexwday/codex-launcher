# codex-launcher

Local proxy wrapper for Codex Desktop in restricted enterprise networks.

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
- configures and launches Codex Desktop with the proxy provider.

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
- Codex Desktop config and launch helpers

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

5. Start proxy/dashboard:

```bash
python -m src.main
```

6. Open the dashboard:

```text
http://127.0.0.1:8765
```

7. Select a model, configure Codex, and launch Codex Desktop from the dashboard.

You can still print Codex provider wiring instructions:

```bash
python -m src.launch_codex --profile local
```

## Notes

- Set `CODEX_PROXY_PROFILE=local` for local development, `work` for enterprise settings.
- Keep `PROXY_STATIC_API_KEY` local-only; upstream auth should use OAuth2 tokens.
- Secrets stay in `.env`; `~/.codex/config.toml` only stores the proxy provider name, base URL, wire API, and environment variable name.
- The proxy sets `store=false` on `/v1/responses` before forwarding upstream.
