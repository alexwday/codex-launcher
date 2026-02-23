# codex-launcher

Local proxy wrapper for Codex Desktop in restricted enterprise networks.

## Goal

Route Codex traffic through a local proxy that:
- authenticates inbound requests with a local static key,
- initializes enterprise SSL certs via `rbc_security`,
- acquires and refreshes OAuth2 access tokens for upstream calls,
- maps Codex-facing model names to internal model names,
- injects token defaults (`32768`) when callers omit them.

## Phase 1 (current)

This repo currently contains the project scaffold and baseline modules:
- profile-based config (`local` / `work`)
- SSL setup helper
- OAuth token manager with refresh scheduling
- model alias mapper
- request normalizers for `/v1/responses` and `/v1/chat/completions`
- FastAPI proxy app skeleton with upstream forwarding
- Codex launcher helper script

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

3. Start proxy:

```bash
python -m src.main
```

4. Print Codex provider wiring instructions:

```bash
python -m src.launch_codex --profile local
```

## Notes

- Set `CODEX_PROXY_PROFILE=local` for local development, `work` for enterprise settings.
- Keep `PROXY_STATIC_API_KEY` local-only; upstream auth should use OAuth2 tokens.
