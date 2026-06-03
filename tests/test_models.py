from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.models import ModelConfigError, SelectedModelStore, load_model_catalog


class ModelsTests(unittest.TestCase):
    def test_loads_model_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "models.json"
            path.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "id": "codex-facing",
                                "display_name": "Codex Facing",
                                "upstream_model": "corp-model",
                                "max_output_tokens": 12000,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            models = load_model_catalog(
                path,
                default_model_id="codex-facing",
                default_upstream_model="corp-model",
                default_max_output_tokens=32768,
            )

        self.assertEqual(models[0].id, "codex-facing")
        self.assertEqual(models[0].upstream_model, "corp-model")
        self.assertEqual(models[0].max_output_tokens, 12000)

    def test_profile_specific_catalog_uses_matching_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "models.json"
            path.write_text(
                json.dumps(
                    {
                        "profiles": {
                            "local": {
                                "models": [
                                    {
                                        "id": "local-model",
                                        "upstream_model": "openai-local",
                                        "max_output_tokens": 8000,
                                    }
                                ]
                            },
                            "work": {
                                "models": [
                                    {
                                        "id": "work-model",
                                        "upstream_model": "corp-work",
                                        "max_output_tokens": 16000,
                                    }
                                ]
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            models = load_model_catalog(
                path,
                profile="work",
                default_model_id="work-model",
                default_upstream_model="corp-work",
                default_max_output_tokens=32768,
            )

        self.assertEqual([model.id for model in models], ["work-model"])
        self.assertEqual(models[0].upstream_model, "corp-work")

    def test_catalog_adds_default_model_when_profile_model_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "models.json"
            path.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "id": "local-first",
                                "upstream_model": "openai-local",
                                "max_output_tokens": 8000,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            models = load_model_catalog(
                path,
                profile="work",
                default_model_id="work-model",
                default_upstream_model="corp-work",
                default_max_output_tokens=32768,
            )

        self.assertEqual(models[0].id, "work-model")
        self.assertEqual(models[0].upstream_model, "corp-work")
        self.assertEqual(models[1].id, "local-first")

    def test_flat_catalog_can_filter_by_profile_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "models.json"
            path.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "id": "local-model",
                                "upstream_model": "openai-local",
                                "max_output_tokens": 8000,
                                "profiles": ["local"],
                            },
                            {
                                "id": "work-model",
                                "upstream_model": "corp-work",
                                "max_output_tokens": 16000,
                                "profiles": ["work"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            models = load_model_catalog(
                path,
                profile="work",
                default_model_id="work-model",
                default_upstream_model="corp-work",
                default_max_output_tokens=32768,
            )

        self.assertEqual([model.id for model in models], ["work-model"])

    def test_missing_catalog_uses_fallback(self) -> None:
        models = load_model_catalog(
            Path("/tmp/does-not-exist-codex-launcher-models.json"),
            default_model_id="fallback",
            default_upstream_model="fallback-upstream",
            default_max_output_tokens=32768,
        )

        self.assertEqual(models[0].id, "fallback")
        self.assertEqual(models[0].upstream_model, "fallback-upstream")

    def test_selected_model_store_rejects_unknown_model(self) -> None:
        models = load_model_catalog(
            Path("/tmp/does-not-exist-codex-launcher-models.json"),
            default_model_id="fallback",
            default_upstream_model="fallback-upstream",
            default_max_output_tokens=32768,
        )
        store = SelectedModelStore(models, "fallback")

        with self.assertRaises(ModelConfigError):
            store.select("missing")

    def test_selected_model_store_rejects_missing_default(self) -> None:
        models = load_model_catalog(
            Path("/tmp/does-not-exist-codex-launcher-models.json"),
            default_model_id="fallback",
            default_upstream_model="fallback-upstream",
            default_max_output_tokens=32768,
        )

        with self.assertRaises(ModelConfigError):
            SelectedModelStore(models, "missing")


if __name__ == "__main__":
    unittest.main()
