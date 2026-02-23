from __future__ import annotations

import unittest

from src.model_mapping import ModelMapper
from src.request_normalizer import (
    normalize_chat_completions_request,
    normalize_responses_request,
)


class RequestNormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mapper = ModelMapper({"gpt-5.3-codex": "corp-gpt5"})

    def test_chat_injects_default_max_tokens_when_missing(self) -> None:
        payload = {"model": "gpt-5.3-codex", "messages": [{"role": "user", "content": "hi"}]}
        normalized = normalize_chat_completions_request(
            payload,
            mapper=self.mapper,
            default_max_tokens=32768,
        )
        self.assertEqual(normalized["model"], "corp-gpt5")
        self.assertEqual(normalized["max_tokens"], 32768)

    def test_chat_preserves_existing_max_tokens(self) -> None:
        payload = {
            "model": "gpt-5.3-codex",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 500,
        }
        normalized = normalize_chat_completions_request(
            payload,
            mapper=self.mapper,
            default_max_tokens=32768,
        )
        self.assertEqual(normalized["max_tokens"], 500)

    def test_responses_injects_default_max_output_tokens_when_missing(self) -> None:
        payload = {"model": "gpt-5.3-codex", "input": "hi"}
        normalized = normalize_responses_request(
            payload,
            mapper=self.mapper,
            default_max_output_tokens=32768,
        )
        self.assertEqual(normalized["model"], "corp-gpt5")
        self.assertEqual(normalized["max_output_tokens"], 32768)

    def test_responses_preserves_existing_max_output_tokens(self) -> None:
        payload = {"model": "gpt-5.3-codex", "input": "hi", "max_output_tokens": 1000}
        normalized = normalize_responses_request(
            payload,
            mapper=self.mapper,
            default_max_output_tokens=32768,
        )
        self.assertEqual(normalized["max_output_tokens"], 1000)


if __name__ == "__main__":
    unittest.main()
