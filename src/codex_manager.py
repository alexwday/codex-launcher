"""Codex Desktop installation, configuration, and launch helpers."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import tomlkit

from .config import Settings
from .models import ModelConfig


@dataclass(frozen=True)
class CodexStatus:
    installed: bool
    running: bool
    app_path: str
    app_executable: str
    bundled_cli: str
    config_path: str
    setup_url: str
    doctor_ok: Optional[bool] = None
    doctor: Optional[dict[str, Any]] = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_codex_status(settings: Settings, *, run_doctor: bool = False) -> CodexStatus:
    app_executable = _app_executable(settings)
    bundled_cli = _bundled_cli(settings)
    installed = app_executable.exists() and bundled_cli.exists()
    running = _is_codex_running()
    doctor: Optional[dict[str, Any]] = None
    doctor_ok: Optional[bool] = None
    message = ""

    if not installed:
        message = (
            f"Codex Desktop was not found at {settings.codex.app_path}. "
            f"Clone and set up Codex Desktop from {settings.codex.desktop_repo_url}."
        )
    elif run_doctor:
        doctor_ok, doctor = _run_doctor(bundled_cli)
        if doctor_ok is False:
            message = "Codex doctor reported a problem."

    return CodexStatus(
        installed=installed,
        running=running,
        app_path=str(settings.codex.app_path),
        app_executable=str(app_executable),
        bundled_cli=str(bundled_cli),
        config_path=str(settings.codex.config_path),
        setup_url=settings.codex.desktop_repo_url,
        doctor_ok=doctor_ok,
        doctor=doctor,
        message=message,
    )


def configure_codex(settings: Settings, selected_model: ModelConfig) -> dict[str, Any]:
    """Update user-level Codex config.toml and keep a timestamped backup."""
    config_path = settings.codex.config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Optional[Path] = None

    if config_path.exists():
        backup_path = config_path.with_name(
            f"{config_path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        )
        backup_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
        doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()

    proxy_url = f"http://{settings.proxy.host}:{settings.proxy.port}/v1"
    provider_id = settings.codex.model_provider

    doc["model_provider"] = provider_id
    doc["model"] = selected_model.id

    providers = doc.get("model_providers")
    if providers is None:
        providers = tomlkit.table()
        doc["model_providers"] = providers

    provider = providers.get(provider_id)
    if provider is None:
        provider = tomlkit.table()
        providers[provider_id] = provider

    provider["name"] = "Codex Launcher Proxy"
    provider["base_url"] = proxy_url
    provider["wire_api"] = "responses"
    provider["env_key"] = settings.codex.env_key

    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return {
        "configured": True,
        "configPath": str(config_path),
        "backupPath": str(backup_path) if backup_path else None,
        "modelProvider": provider_id,
        "model": selected_model.id,
        "baseUrl": proxy_url,
        "envKey": settings.codex.env_key,
    }


def launch_codex(settings: Settings, selected_model: ModelConfig) -> dict[str, Any]:
    status = get_codex_status(settings, run_doctor=True)
    if not status.installed:
        return {
            "success": False,
            "reason": "not_installed",
            "status": status.to_dict(),
            "message": status.message,
        }
    if status.running:
        return {
            "success": False,
            "reason": "already_running",
            "status": status.to_dict(),
            "message": "Codex Desktop is already running. Quit it, then launch from this dashboard so the proxy API key is in its environment.",
        }

    config_result = configure_codex(settings, selected_model)
    env = os.environ.copy()
    env[settings.codex.env_key] = settings.proxy.static_api_key

    process = subprocess.Popen([str(_app_executable(settings))], env=env)
    return {
        "success": True,
        "pid": process.pid,
        "config": config_result,
        "status": get_codex_status(settings, run_doctor=False).to_dict(),
    }


def _app_executable(settings: Settings) -> Path:
    return settings.codex.app_path / "Contents" / "MacOS" / "Codex"


def _bundled_cli(settings: Settings) -> Path:
    return settings.codex.app_path / "Contents" / "Resources" / "codex"


def _is_codex_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-x", "Codex"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _run_doctor(bundled_cli: Path) -> tuple[bool, dict[str, Any]]:
    try:
        result = subprocess.run(
            [str(bundled_cli), "doctor", "--json"],
            capture_output=True,
            text=True,
            timeout=45,
        )
    except Exception as exc:
        return False, {"error": str(exc)}

    stdout = result.stdout.strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        payload = {"stdout": stdout[-2000:], "stderr": result.stderr[-2000:]}

    return result.returncode == 0, payload
