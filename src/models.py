"""Model catalog and runtime selection state."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


class ModelConfigError(ValueError):
    """Raised when model configuration is invalid."""


@dataclass(frozen=True)
class ModelConfig:
    id: str
    display_name: str
    upstream_model: str
    max_output_tokens: int
    description: str = ""
    context_window: Optional[int] = None
    reasoning_effort: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None}


def load_model_catalog(
    path: Path,
    *,
    default_model_id: str,
    default_upstream_model: str,
    default_max_output_tokens: int,
) -> list[ModelConfig]:
    """Load non-secret model settings from JSON, with a safe fallback model."""
    if not path.exists():
        return [
            ModelConfig(
                id=default_model_id,
                display_name=default_model_id,
                upstream_model=default_upstream_model,
                max_output_tokens=default_max_output_tokens,
            )
        ]

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelConfigError(f"Invalid model config JSON: {exc}") from exc

    items = raw.get("models") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ModelConfigError("Model config must be a list or an object with a models list")

    models = [_parse_model_config(item) for item in items]
    if not models:
        raise ModelConfigError("Model config must include at least one model")

    seen: set[str] = set()
    for model in models:
        if model.id in seen:
            raise ModelConfigError(f"Duplicate model id: {model.id}")
        seen.add(model.id)

    return models


class SelectedModelStore:
    """Thread-safe selected model state."""

    def __init__(self, models: list[ModelConfig], default_model_id: str) -> None:
        if not models:
            raise ModelConfigError("At least one model is required")
        self._models = {model.id: model for model in models}
        self._ordered_ids = [model.id for model in models]
        self._selected_id = default_model_id if default_model_id in self._models else self._ordered_ids[0]
        self._lock = threading.Lock()

    def list_models(self) -> list[dict[str, Any]]:
        selected_id = self.selected().id
        return [
            {
                **self._models[model_id].to_dict(),
                "selected": model_id == selected_id,
            }
            for model_id in self._ordered_ids
        ]

    def selected(self) -> ModelConfig:
        with self._lock:
            return self._models[self._selected_id]

    def select(self, model_id: str) -> ModelConfig:
        if model_id not in self._models:
            raise ModelConfigError(f"Unknown model id: {model_id}")
        with self._lock:
            self._selected_id = model_id
            return self._models[self._selected_id]


def _parse_model_config(item: Any) -> ModelConfig:
    if not isinstance(item, dict):
        raise ModelConfigError("Each model entry must be an object")

    model_id = str(item.get("id") or "").strip()
    upstream_model = str(item.get("upstream_model") or "").strip()
    display_name = str(item.get("display_name") or model_id).strip()
    if not model_id:
        raise ModelConfigError("Model entry missing id")
    if not upstream_model:
        raise ModelConfigError(f"Model {model_id} missing upstream_model")

    try:
        max_output_tokens = int(item.get("max_output_tokens", 32768))
    except (TypeError, ValueError) as exc:
        raise ModelConfigError(f"Model {model_id} max_output_tokens must be an integer") from exc

    context_window = item.get("context_window")
    if context_window is not None:
        try:
            context_window = int(context_window)
        except (TypeError, ValueError) as exc:
            raise ModelConfigError(f"Model {model_id} context_window must be an integer") from exc

    reasoning_effort = item.get("reasoning_effort")
    if reasoning_effort is not None:
        reasoning_effort = str(reasoning_effort).strip() or None

    return ModelConfig(
        id=model_id,
        display_name=display_name,
        upstream_model=upstream_model,
        max_output_tokens=max_output_tokens,
        description=str(item.get("description") or ""),
        context_window=context_window,
        reasoning_effort=reasoning_effort,
    )
