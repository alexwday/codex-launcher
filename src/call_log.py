"""In-memory API call log for the local dashboard."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class CallLogEntry:
    id: str
    started_at: float
    duration_ms: int
    method: str
    path: str
    status_code: int
    streaming: bool
    original_model: str
    upstream_model: str
    request_preview: str
    response_preview: str
    error: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CallLog:
    """Bounded, thread-safe log of recent proxy calls."""

    def __init__(self, max_entries: int = 200) -> None:
        self._entries: deque[CallLogEntry] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def add(
        self,
        *,
        started_at: float,
        method: str,
        path: str,
        status_code: int,
        streaming: bool,
        original_model: str,
        upstream_model: str,
        request_payload: Any,
        response_payload: Any = None,
        error: str = "",
        usage: Optional[dict[str, Any]] = None,
    ) -> CallLogEntry:
        usage = usage or {}
        entry = CallLogEntry(
            id=f"call_{uuid.uuid4().hex[:16]}",
            started_at=started_at,
            duration_ms=int((time.time() - started_at) * 1000),
            method=method,
            path=path,
            status_code=status_code,
            streaming=streaming,
            original_model=original_model,
            upstream_model=upstream_model,
            request_preview=_preview(request_payload),
            response_preview=_preview(response_payload),
            error=error,
            input_tokens=int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
        )
        with self._lock:
            self._entries.appendleft(entry)
        return entry

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            entries = list(self._entries)[: max(limit, 0)]
        return [entry.to_dict() for entry in entries]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _preview(value: Any, max_chars: int = 1400) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=True, sort_keys=True)
        except TypeError:
            text = str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[truncated]"
