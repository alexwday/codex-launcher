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
                default_model_id="fallback",
                default_upstream_model="fallback-upstream",
                default_max_output_tokens=32768,
            )

        self.assertEqual(models[0].id, "codex-facing")
        self.assertEqual(models[0].upstream_model, "corp-model")
        self.assertEqual(models[0].max_output_tokens, 12000)

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


if __name__ == "__main__":
    unittest.main()
