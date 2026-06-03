"""Configure and optionally launch Codex Desktop through the local proxy."""

from __future__ import annotations

import argparse
import json

from .codex_manager import configure_codex, get_codex_status, launch_codex
from .config import load_settings
from .models import SelectedModelStore, load_model_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure and optionally launch Codex Desktop via local proxy")
    parser.add_argument("--profile", default=None, help="Config profile override (local/work)")
    parser.add_argument("--model", default=None, help="Codex-facing model id to select from models.json")
    parser.add_argument("--launch", action="store_true", help="Launch Codex Desktop after configuring")
    parser.add_argument("--status", action="store_true", help="Print Codex install/status information")
    args = parser.parse_args()

    settings = load_settings(args.profile)
    models = load_model_catalog(
        settings.model_config_path,
        profile=settings.profile,
        default_model_id=settings.codex.model,
        default_upstream_model=settings.model_mapping.get(settings.codex.model, settings.codex.model),
        default_max_output_tokens=settings.token_defaults.responses_max_output_tokens,
    )
    store = SelectedModelStore(models, args.model or settings.codex.model)
    selected = store.selected()

    if args.status:
        print(json.dumps(get_codex_status(settings, run_doctor=True).to_dict(), indent=2))
        return

    result = configure_codex(settings, selected)
    print(json.dumps(result, indent=2))
    print()
    print(f"Configured {settings.codex.model_provider} for {selected.id} -> {selected.upstream_model}")
    print(f"Codex will read its local proxy key from {settings.codex.env_key}.")

    if args.launch:
        launch_result = launch_codex(settings, selected)
        print(json.dumps(launch_result, indent=2))


if __name__ == "__main__":
    main()
