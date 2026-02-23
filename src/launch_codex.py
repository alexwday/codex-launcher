"""Helper script to print/apply Codex runtime wiring for the local proxy."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from .config import load_settings


def _build_cmd(
    provider: str,
    model: str,
    base_url: str,
    workspace: str,
    env_key: str,
) -> list[str]:
    return [
        "codex",
        "-c",
        f'model_provider="{provider}"',
        "-c",
        f'model="{model}"',
        "-c",
        f'model_providers.{provider}.name="Codex Launcher Proxy"',
        "-c",
        f'model_providers.{provider}.base_url="{base_url.rstrip('/')}/v1"',
        "-c",
        f'model_providers.{provider}.env_key="{env_key}"',
        "-c",
        f'model_providers.{provider}.wire_api="responses"',
        "-C",
        workspace,
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure and optionally launch Codex via local proxy")
    parser.add_argument("--profile", default=None, help="Config profile override (local/work)")
    parser.add_argument("--workspace", default=str(Path.cwd()), help="Workspace path for Codex")
    parser.add_argument("--proxy-url", default=None, help="Proxy base URL override, e.g. http://127.0.0.1:8765")
    parser.add_argument("--provider", default=None, help="Codex model provider name override")
    parser.add_argument("--model", default=None, help="Codex model override")
    parser.add_argument("--launch", action="store_true", help="Launch Codex immediately")
    args = parser.parse_args()

    settings = load_settings(args.profile)

    provider = args.provider or settings.codex.model_provider
    model = args.model or settings.codex.model
    proxy_url = args.proxy_url or f"http://{settings.proxy.host}:{settings.proxy.port}"

    print("Use this model provider block in ~/.codex/config.toml:")
    print()
    print(f"[model_providers.{provider}]")
    print('name = "Codex Launcher Proxy"')
    print(f'base_url = "{proxy_url.rstrip("/")}/v1"')
    print(f'env_key = "{settings.codex.env_key}"')
    print('wire_api = "responses"')
    print()
    print("Then set:")
    print(f'model_provider = "{provider}"')
    print(f'model = "{model}"')
    print()
    print(f"Export before running Codex: export {settings.codex.env_key}='{settings.proxy.static_api_key}'")

    cmd = _build_cmd(provider, model, proxy_url, args.workspace, settings.codex.env_key)
    print()
    print("One-shot launch command:")
    print(" ".join(cmd))

    if args.launch:
        env = os.environ.copy()
        env[settings.codex.env_key] = settings.proxy.static_api_key
        subprocess.run(cmd, check=True, env=env)


if __name__ == "__main__":
    main()
