from __future__ import annotations

import unittest

from src.model_mapping import ModelMapper


class ModelMapperTests(unittest.TestCase):
    def test_exact_match(self) -> None:
        mapper = ModelMapper({"gpt-5.3-codex": "corp-gpt5"})
        self.assertEqual(mapper.map("gpt-5.3-codex"), "corp-gpt5")

    def test_case_insensitive_exact_match(self) -> None:
        mapper = ModelMapper({"GPT-5.3-CODEX": "corp-gpt5"})
        self.assertEqual(mapper.map("gpt-5.3-codex"), "corp-gpt5")

    def test_family_fallback(self) -> None:
        mapper = ModelMapper({"sonnet": "internal-sonnet"})
        self.assertEqual(mapper.map("claude-sonnet-4-20250514"), "internal-sonnet")

    def test_passthrough_when_no_match(self) -> None:
        mapper = ModelMapper({"some-model": "mapped"})
        self.assertEqual(mapper.map("unknown-model"), "unknown-model")


if __name__ == "__main__":
    unittest.main()
