from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from fastapi.testclient import TestClient

from src.config import CodexConfig, ProxyConfig, Settings, TokenDefaults, UpstreamConfig
from src.proxy_app import create_app


def make_response(payload: dict, status_code: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode("utf-8")
    response.headers["content-type"] = "application/json"
    return response


def make_settings(temp_dir: Path) -> Settings:
    models_path = temp_dir / "models.json"
    models_path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "id": "codex-facing",
                        "display_name": "Codex Facing",
                        "upstream_model": "corp-model-a",
                        "max_output_tokens": 12000,
                    },
                    {
                        "id": "codex-alt",
                        "display_name": "Codex Alt",
                        "upstream_model": "corp-model-b",
                        "max_output_tokens": 16000,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return Settings(
        profile="test",
        proxy=ProxyConfig(host="127.0.0.1", port=8765, static_api_key="proxy-key"),
        upstream=UpstreamConfig(
            base_url="https://upstream.example/v1",
            verify_ssl=True,
            static_api_key="upstream-key",
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
        model_config_path=models_path,
        log_level="INFO",
    )


class ProxyAppTests(unittest.TestCase):
    def test_responses_requires_proxy_auth(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            app = create_app(make_settings(Path(raw_temp_dir)))
            client = TestClient(app)
            response = client.post("/v1/responses", json={"model": "x", "input": "hi"})

        self.assertEqual(response.status_code, 401)

    def test_responses_forwards_directly_with_selected_model_and_store_false(self) -> None:
        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return make_response(
                {
                    "id": "resp_1",
                    "object": "response",
                    "model": kwargs["json"]["model"],
                    "output": [],
                    "usage": {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9},
                }
            )

        with tempfile.TemporaryDirectory() as raw_temp_dir:
            app = create_app(make_settings(Path(raw_temp_dir)))
            client = TestClient(app)
            with patch("src.proxy_app.requests.post", side_effect=fake_post):
                response = client.post(
                    "/v1/responses",
                    headers={"Authorization": "Bearer proxy-key"},
                    json={"model": "codex-original", "input": "hi", "store": True},
                )
                calls = client.get("/api/calls").json()["calls"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["url"], "https://upstream.example/v1/responses")
        self.assertEqual(captured["kwargs"]["headers"]["Authorization"], "Bearer upstream-key")
        self.assertEqual(captured["kwargs"]["json"]["model"], "corp-model-a")
        self.assertIs(captured["kwargs"]["json"]["store"], False)
        self.assertEqual(calls[0]["original_model"], "codex-original")
        self.assertEqual(calls[0]["upstream_model"], "corp-model-a")
        self.assertEqual(calls[0]["input_tokens"], 4)

    def test_model_selection_changes_forced_upstream_model(self) -> None:
        captured = {}

        def fake_post(url, **kwargs):
            captured["payload"] = kwargs["json"]
            return make_response({"id": "resp_1", "object": "response", "output": []})

        with tempfile.TemporaryDirectory() as raw_temp_dir:
            app = create_app(make_settings(Path(raw_temp_dir)))
            client = TestClient(app)
            select_response = client.post("/api/models/select", json={"model": "codex-alt"})
            with patch("src.proxy_app.requests.post", side_effect=fake_post):
                response = client.post(
                    "/v1/responses",
                    headers={"x-api-key": "proxy-key"},
                    json={"model": "anything", "input": "hi"},
                )

        self.assertEqual(select_response.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["payload"]["model"], "corp-model-b")
        self.assertEqual(captured["payload"]["max_output_tokens"], 16000)

    def test_codex_launch_passes_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            temp_dir = Path(raw_temp_dir)
            app = create_app(make_settings(temp_dir))
            client = TestClient(app)
            workspace = temp_dir / "repo"
            workspace.mkdir()
            with patch("src.proxy_app.launch_codex") as mocked_launch:
                mocked_launch.return_value = {
                    "success": True,
                    "workspacePath": str(workspace),
                }
                response = client.post(
                    "/api/codex/launch",
                    json={"workspacePath": str(workspace), "installIfMissing": True},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["workspacePath"], str(workspace))
        self.assertEqual(mocked_launch.call_args.kwargs["workspace_path"], str(workspace))
        self.assertIs(mocked_launch.call_args.kwargs["install_if_missing"], True)

    def test_codex_install_endpoint_runs_installer(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp_dir:
            temp_dir = Path(raw_temp_dir)
            app = create_app(make_settings(temp_dir))
            client = TestClient(app)
            with patch("src.proxy_app.install_or_update_codex_cli") as mocked_install:
                mocked_install.return_value = {
                    "success": True,
                    "resolvedCliPath": str(temp_dir / "codex"),
                }
                with patch("src.proxy_app.get_codex_status") as mocked_status:
                    mocked_status.return_value.to_dict.return_value = {
                        "installed": True,
                        "resolved_cli_path": str(temp_dir / "codex"),
                    }
                    response = client.post("/api/codex/install")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["install"]["resolvedCliPath"], str(temp_dir / "codex"))


if __name__ == "__main__":
    unittest.main()
