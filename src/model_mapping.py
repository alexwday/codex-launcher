"""Model alias mapping helpers."""

from __future__ import annotations

from dataclasses import dataclass

_FAMILY_KEYS = ("sonnet", "opus", "haiku")


@dataclass(frozen=True)
class ModelMapper:
    """Maps external model IDs to internal model IDs."""

    mapping: dict[str, str]

    def map(self, model_name: str) -> str:
        if model_name in self.mapping:
            return self.mapping[model_name]

        lowered_lookup = {k.lower(): v for k, v in self.mapping.items()}
        lowered = model_name.lower()

        if lowered in lowered_lookup:
            return lowered_lookup[lowered]

        for family in _FAMILY_KEYS:
            if family in lowered and family in lowered_lookup:
                return lowered_lookup[family]

        return model_name
