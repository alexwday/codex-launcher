from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.codex_manager import configure_codex, get_codex_status
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

    def test_codex_status_missing_app(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            settings = make_settings(Path(raw_temp_dir))
            with patch("src.codex_manager._is_codex_running", return_value=False):
                status = get_codex_status(settings)

        self.assertFalse(status.installed)
        self.assertFalse(status.running)
        self.assertIn("Clone", status.message)


if __name__ == "__main__":
    unittest.main()
