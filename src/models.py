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
    profile: Optional[str] = None,
    default_model_id: str,
    default_upstream_model: str,
    default_max_output_tokens: int,
) -> list[ModelConfig]:
    """Load non-secret model settings from JSON, with a safe fallback model."""
    default_model = ModelConfig(
        id=default_model_id,
        display_name=default_model_id,
        upstream_model=default_upstream_model,
        max_output_tokens=default_max_output_tokens,
        description="Fallback from CODEX_MODEL settings.",
    )
    if not path.exists():
        return [default_model]

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelConfigError(f"Invalid model config JSON: {exc}") from exc

    items = _select_model_items(raw, profile=profile)
    if not isinstance(items, list):
        raise ModelConfigError(
            "Model config must be a list, an object with a models list, "
            "or an object with profiles.<profile>.models"
        )

    models = [_parse_model_config(item) for item in items]
    seen: set[str] = set()
    for model in models:
        if model.id in seen:
            raise ModelConfigError(f"Duplicate model id: {model.id}")
        seen.add(model.id)

    if default_model_id not in seen:
        models.insert(0, default_model)
    if not models:
        raise ModelConfigError("Model config must include at least one model")

    return models


class SelectedModelStore:
    """Thread-safe selected model state."""

    def __init__(self, models: list[ModelConfig], default_model_id: str) -> None:
        if not models:
            raise ModelConfigError("At least one model is required")
        self._models = {model.id: model for model in models}
        self._ordered_ids = [model.id for model in models]
        if default_model_id not in self._models:
            raise ModelConfigError(f"Default model id is not configured: {default_model_id}")
        self._selected_id = default_model_id
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


def _select_model_items(raw: Any, *, profile: Optional[str]) -> Any:
    if isinstance(raw, list):
        return _filter_models_for_profile(raw, profile=profile)
    if not isinstance(raw, dict):
        return raw

    profiles = raw.get("profiles")
    normalized_profile = (profile or "").strip().lower()
    if normalized_profile and isinstance(profiles, dict):
        profile_config = profiles.get(normalized_profile)
        if profile_config is None:
            return []
        if isinstance(profile_config, dict):
            return profile_config.get("models", [])
        return profile_config

    if "models" in raw:
        return _filter_models_for_profile(raw.get("models"), profile=profile)

    return raw


def _filter_models_for_profile(items: Any, *, profile: Optional[str]) -> Any:
    if not isinstance(items, list) or not profile:
        return items

    normalized_profile = profile.strip().lower()
    filtered = []
    for item in items:
        if not isinstance(item, dict):
            filtered.append(item)
            continue
        allowed_profiles = _allowed_profiles(item)
        if not allowed_profiles or normalized_profile in allowed_profiles:
            filtered.append(item)

    return filtered


def _allowed_profiles(item: dict[str, Any]) -> set[str]:
    raw_profiles = item.get("profiles", item.get("profile"))
    if raw_profiles is None:
        return set()
    if isinstance(raw_profiles, str):
        values = [value.strip() for value in raw_profiles.split(",")]
    elif isinstance(raw_profiles, list):
        values = [str(value).strip() for value in raw_profiles]
    else:
        raise ModelConfigError("Model profile metadata must be a string or list")

    return {value.lower() for value in values if value}
