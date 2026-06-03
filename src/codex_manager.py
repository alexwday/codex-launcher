"""Codex CLI installation, configuration, and launch helpers."""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import tomlkit

from .config import Settings
from .models import ModelConfig

_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class CodexStatus:
    installed: bool
    running: bool
    cli_path: str
    resolved_cli_path: Optional[str]
    source_path: str
    workspace_path: str
    config_path: str
    setup_url: str
    release_base_url: str
    doctor_ok: Optional[bool] = None
    doctor: Optional[dict[str, Any]] = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_codex_status(settings: Settings, *, run_doctor: bool = False) -> CodexStatus:
    resolved_cli = _resolve_cli_path(settings)
    installed = resolved_cli is not None
    running = _is_codex_running()
    doctor: Optional[dict[str, Any]] = None
    doctor_ok: Optional[bool] = None
    message = ""

    if not installed:
        message = (
            "Codex CLI was not found. Install it from the GitHub release with "
            "`scripts/install_codex_cli_from_github_release.sh`, or clone/build it "
            f"from {settings.codex.cli_repo_url}."
        )
    elif run_doctor:
        doctor_ok, doctor = _run_doctor(resolved_cli)
        if doctor_ok is False:
            message = "Codex doctor reported a problem."

    return CodexStatus(
        installed=installed,
        running=running,
        cli_path=settings.codex.cli_path,
        resolved_cli_path=str(resolved_cli) if resolved_cli else None,
        source_path=str(settings.codex.cli_source_path),
        workspace_path=str(_workspace_path(settings)),
        config_path=str(settings.codex.config_path),
        setup_url=settings.codex.cli_repo_url,
        release_base_url=settings.codex.cli_release_base_url,
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
    if not status.installed or not status.resolved_cli_path:
        return {
            "success": False,
            "reason": "not_installed",
            "status": status.to_dict(),
            "message": status.message,
        }

    config_result = configure_codex(settings, selected_model)
    launch_result = _launch_cli(settings, Path(status.resolved_cli_path))
    return {
        "success": True,
        **launch_result,
        "config": config_result,
        "status": get_codex_status(settings, run_doctor=False).to_dict(),
    }


def _resolve_cli_path(settings: Settings) -> Optional[Path]:
    raw_path = settings.codex.cli_path.strip()
    if not raw_path:
        return None

    if "/" not in raw_path:
        resolved = shutil.which(raw_path)
        return Path(resolved) if resolved else None

    candidate = Path(raw_path).expanduser()
    if candidate.exists() and os.access(candidate, os.X_OK):
        return candidate
    return None


def _workspace_path(settings: Settings) -> Path:
    workspace = settings.codex.workspace_path.expanduser()
    if workspace.exists() and workspace.is_dir():
        return workspace
    return Path.home()


def _is_codex_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-x", "codex"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _run_doctor(cli_path: Path) -> tuple[bool, dict[str, Any]]:
    try:
        result = subprocess.run(
            [str(cli_path), "doctor", "--json"],
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


def _launch_cli(settings: Settings, cli_path: Path) -> dict[str, Any]:
    _validate_env_name(settings.codex.env_key)
    workspace = _workspace_path(settings)

    if platform.system() == "Darwin":
        return _launch_cli_in_terminal(settings, cli_path, workspace)

    env = os.environ.copy()
    env[settings.codex.env_key] = settings.proxy.static_api_key
    process = subprocess.Popen([str(cli_path)], cwd=str(workspace), env=env)
    return {
        "pid": process.pid,
        "launchMode": "subprocess",
        "workspacePath": str(workspace),
    }


def _launch_cli_in_terminal(settings: Settings, cli_path: Path, workspace: Path) -> dict[str, Any]:
    temp_dir = Path(tempfile.gettempdir())
    key_fd, key_name = tempfile.mkstemp(
        prefix="codex-launcher-key-",
        dir=temp_dir,
    )
    os.close(key_fd)
    key_file = Path(key_name)
    key_file.write_text(settings.proxy.static_api_key, encoding="utf-8")
    key_file.chmod(0o600)

    script_fd, script_name = tempfile.mkstemp(
        prefix="codex-launcher-run-",
        suffix=".sh",
        dir=temp_dir,
    )
    os.close(script_fd)
    script_file = Path(script_name)
    script_file.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -e",
                f"KEY_FILE={shlex.quote(str(key_file))}",
                f"SCRIPT_FILE={shlex.quote(str(script_file))}",
                f"export {settings.codex.env_key}=\"$(cat \"$KEY_FILE\")\"",
                "rm -f \"$KEY_FILE\" \"$SCRIPT_FILE\"",
                f"cd {shlex.quote(str(workspace))}",
                f"exec {shlex.quote(str(cli_path))}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    script_file.chmod(0o700)

    terminal_command = f"/bin/zsh {shlex.quote(str(script_file))}"
    apple_script = f'tell application "Terminal" to do script {json.dumps(terminal_command)}'
    process = subprocess.Popen(["osascript", "-e", apple_script])
    return {
        "pid": process.pid,
        "launchMode": "terminal",
        "workspacePath": str(workspace),
    }


def _validate_env_name(name: str) -> None:
    if not _ENV_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid Codex env var name: {name}")
