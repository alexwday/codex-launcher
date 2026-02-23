"""Request normalization for OpenAI-compatible endpoints."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .model_mapping import ModelMapper


class RequestNormalizationError(ValueError):
    """Raised when a request body cannot be normalized."""


def _clone_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RequestNormalizationError("Request body must be a JSON object")
    return deepcopy(payload)


def normalize_chat_completions_request(
    payload: Any,
    *,
    mapper: ModelMapper,
    default_max_tokens: int,
) -> dict[str, Any]:
    normalized = _clone_payload(payload)

    model = normalized.get("model")
    if isinstance(model, str) and model.strip():
        normalized["model"] = mapper.map(model)

    if "max_tokens" not in normalized and "max_completion_tokens" not in normalized:
        normalized["max_tokens"] = default_max_tokens

    return normalized


def normalize_responses_request(
    payload: Any,
    *,
    mapper: ModelMapper,
    default_max_output_tokens: int,
) -> dict[str, Any]:
    normalized = _clone_payload(payload)

    model = normalized.get("model")
    if isinstance(model, str) and model.strip():
        normalized["model"] = mapper.map(model)

    if "max_output_tokens" not in normalized and "max_tokens" not in normalized:
        normalized["max_output_tokens"] = default_max_output_tokens

    return normalized
