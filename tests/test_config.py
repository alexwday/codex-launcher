from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.config import ConfigError, load_settings


class ConfigTests(unittest.TestCase):
    def test_load_local_profile_prefixed_values(self) -> None:
        env = {
            "CODEX_PROXY_PROFILE": "local",
            "LOCAL_PROXY_HOST": "127.0.0.1",
            "LOCAL_PROXY_PORT": "9001",
            "LOCAL_PROXY_STATIC_API_KEY": "abc123",
            "LOCAL_UPSTREAM_BASE_URL": "https://example.com/v1",
            "LOCAL_VERIFY_SSL": "true",
            "LOCAL_DEFAULT_MAX_TOKENS": "32768",
            "LOCAL_DEFAULT_MAX_OUTPUT_TOKENS": "32768",
            "LOCAL_MODEL_MAPPING": "gpt-5.3-codex=corp-model",
            "LOCAL_CODEX_MODEL_PROVIDER": "corp-proxy",
            "LOCAL_CODEX_MODEL": "gpt-5.3-codex",
            "LOCAL_CODEX_ENV_KEY": "CODEX_PROXY_API_KEY",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()

        self.assertEqual(settings.profile, "local")
        self.assertEqual(settings.proxy.port, 9001)
        self.assertEqual(settings.proxy.static_api_key, "abc123")
        self.assertEqual(settings.model_mapping["gpt-5.3-codex"], "corp-model")

    def test_raises_on_missing_proxy_api_key(self) -> None:
        env = {
            "CODEX_PROXY_PROFILE": "local",
            "LOCAL_PROXY_HOST": "127.0.0.1",
            "LOCAL_PROXY_PORT": "9001",
            "LOCAL_UPSTREAM_BASE_URL": "https://example.com/v1",
        }

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError):
                load_settings()

    def test_raises_on_incomplete_oauth(self) -> None:
        env = {
            "CODEX_PROXY_PROFILE": "local",
            "LOCAL_PROXY_STATIC_API_KEY": "abc123",
            "LOCAL_UPSTREAM_BASE_URL": "https://example.com/v1",
            "LOCAL_OAUTH_TOKEN_ENDPOINT": "https://oauth.example/token",
            "LOCAL_OAUTH_CLIENT_ID": "id-only",
        }

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError):
                load_settings()


if __name__ == "__main__":
    unittest.main()
