from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.codex_manager import configure_codex, get_codex_status, launch_codex
from src.config import CodexConfig, ProxyConfig, Settings, TokenDefaults, UpstreamConfig
from src.models import ModelConfig


def make_settings(temp_dir: Path) -> Settings:
    return Settings(
        profile="test",
        proxy=ProxyConfig(host="127.0.0.1", port=8765, static_api_key="proxy-secret"),
        upstream=UpstreamConfig(
            base_url="https://example.com/v1",
            verify_ssl=True,
            static_api_key="upstream-secret",
        ),
        oauth=None,
        token_defaults=TokenDefaults(chat_max_tokens=32768, responses_max_output_tokens=32768),
        codex=CodexConfig(
            model_provider="codex-launcher-proxy",
            model="codex-facing",
            env_key="CODEX_PROXY_API_KEY",
            config_path=temp_dir / "config.toml",
            cli_path=str(temp_dir / "codex"),
            workspace_path=temp_dir,
            cli_source_path=temp_dir / "openai-codex",
            cli_repo_url="https://github.com/openai/codex.git",
            cli_release_base_url="https://github.com/openai/codex/releases/latest/download",
            app_path=temp_dir / "Codex.app",
            desktop_repo_url="https://github.com/openai/codex",
        ),
        model_mapping={},
        model_config_path=temp_dir / "models.json",
        log_level="INFO",
    )


class CodexManagerTests(unittest.TestCase):
    def test_configure_codex_writes_provider_without_secret(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            temp_dir = Path(raw_temp_dir)
            settings = make_settings(temp_dir)
            model = ModelConfig(
                id="codex-facing",
                display_name="Codex Facing",
                upstream_model="corp-model",
                max_output_tokens=32768,
            )

            result = configure_codex(settings, model)
            text = settings.codex.config_path.read_text(encoding="utf-8")

        self.assertTrue(result["configured"])
        self.assertIn('model_provider = "codex-launcher-proxy"', text)
        self.assertIn('model = "codex-facing"', text)
        self.assertIn('base_url = "http://127.0.0.1:8765/v1"', text)
        self.assertIn('env_key = "CODEX_PROXY_API_KEY"', text)
        self.assertNotIn("proxy-secret", text)
        self.assertNotIn("upstream-secret", text)

    def test_codex_status_missing_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            settings = make_settings(Path(raw_temp_dir))
            with patch("src.codex_manager._is_codex_running", return_value=False):
                status = get_codex_status(settings)

        self.assertFalse(status.installed)
        self.assertFalse(status.running)
        self.assertIn("Codex CLI", status.message)
        self.assertIn("github.com/openai/codex", status.message)

    def test_codex_status_detects_cli_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            temp_dir = Path(raw_temp_dir)
            settings = make_settings(temp_dir)
            cli_path = Path(settings.codex.cli_path)
            cli_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            cli_path.chmod(0o755)

            with patch("src.codex_manager._is_codex_running", return_value=False):
                status = get_codex_status(settings)

        self.assertTrue(status.installed)
        self.assertEqual(status.resolved_cli_path, str(cli_path))

    def test_launch_rejects_invalid_env_key(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            temp_dir = Path(raw_temp_dir)
            settings = make_settings(temp_dir)
            settings = Settings(
                profile=settings.profile,
                proxy=settings.proxy,
                upstream=settings.upstream,
                oauth=settings.oauth,
                token_defaults=settings.token_defaults,
                codex=type(settings.codex)(
                    model_provider=settings.codex.model_provider,
                    model=settings.codex.model,
                    env_key="BAD; echo leaked",
                    config_path=settings.codex.config_path,
                    cli_path=settings.codex.cli_path,
                    workspace_path=settings.codex.workspace_path,
                    cli_source_path=settings.codex.cli_source_path,
                    cli_repo_url=settings.codex.cli_repo_url,
                    cli_release_base_url=settings.codex.cli_release_base_url,
                    app_path=settings.codex.app_path,
                    desktop_repo_url=settings.codex.desktop_repo_url,
                ),
                model_mapping=settings.model_mapping,
                model_config_path=settings.model_config_path,
                log_level=settings.log_level,
            )
            cli_path = Path(settings.codex.cli_path)
            cli_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            cli_path.chmod(0o755)
            model = ModelConfig(
                id="codex-facing",
                display_name="Codex Facing",
                upstream_model="corp-model",
                max_output_tokens=32768,
            )

            with patch("src.codex_manager._run_doctor", return_value=(True, {})):
                with self.assertRaises(ValueError):
                    launch_codex(settings, model)

    def test_launch_uses_workspace_override(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            temp_dir = Path(raw_temp_dir)
            workspace = temp_dir / "workspace"
            workspace.mkdir()
            settings = make_settings(temp_dir)
            cli_path = Path(settings.codex.cli_path)
            cli_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            cli_path.chmod(0o755)
            model = ModelConfig(
                id="codex-facing",
                display_name="Codex Facing",
                upstream_model="corp-model",
                max_output_tokens=32768,
            )

            def fake_terminal_launch(settings_arg, cli_path_arg, workspace_arg):
                return {
                    "pid": 123,
                    "launchMode": "terminal",
                    "workspacePath": str(workspace_arg),
                }

            with patch("src.codex_manager._run_doctor", return_value=(True, {})):
                with patch("src.codex_manager.platform.system", return_value="Darwin"):
                    with patch(
                        "src.codex_manager._launch_cli_in_terminal",
                        side_effect=fake_terminal_launch,
                    ):
                        result = launch_codex(
                            settings,
                            model,
                            workspace_path=str(workspace),
                        )

        self.assertTrue(result["success"])
        self.assertEqual(result["workspacePath"], str(workspace.resolve()))


if __name__ == "__main__":
    unittest.main()
