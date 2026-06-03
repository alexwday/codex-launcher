"""Environment-backed settings for codex-launcher."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = _PROJECT_ROOT / ".env"


class ConfigError(ValueError):
    """Raised when configuration is invalid or incomplete."""


@dataclass(frozen=True)
class ProxyConfig:
    host: str
    port: int
    static_api_key: str


@dataclass(frozen=True)
class UpstreamConfig:
    base_url: str
    verify_ssl: bool
    static_api_key: str
    connect_timeout_seconds: int = 10
    read_timeout_seconds: int = 180


@dataclass(frozen=True)
class OAuthConfig:
    token_endpoint: str
    client_id: str
    client_secret: str
    scope: str
    refresh_buffer_minutes: int
    request_timeout_seconds: int = 30


@dataclass(frozen=True)
class TokenDefaults:
    chat_max_tokens: int
    responses_max_output_tokens: int


@dataclass(frozen=True)
class CodexConfig:
    model_provider: str
    model: str
    env_key: str
    config_path: Path
    app_path: Path
    desktop_repo_url: str


@dataclass(frozen=True)
class Settings:
    profile: str
    proxy: ProxyConfig
    upstream: UpstreamConfig
    oauth: Optional[OAuthConfig]
    token_defaults: TokenDefaults
    codex: CodexConfig
    model_mapping: dict[str, str]
    model_config_path: Path
    log_level: str


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


def _parse_bool(name: str, raw_value: Optional[str], *, default: bool) -> bool:
    if raw_value is None or raw_value.strip() == "":
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean value")


def _parse_int(name: str, raw_value: Optional[str], *, default: int) -> int:
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        return int(raw_value.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _parse_model_mapping(raw_value: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not raw_value.strip():
        return mapping

    for pair in raw_value.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ConfigError(
                "MODEL_MAPPING must use source=target pairs separated by commas"
            )
        source, target = pair.split("=", 1)
        source = source.strip()
        target = target.strip()
        if not source or not target:
            raise ConfigError("MODEL_MAPPING contains an empty source or target")
        mapping[source] = target

    return mapping


def _env_for_profile(profile: str, key: str, default: Optional[str] = None) -> Optional[str]:
    prefixed_key = f"{profile.upper()}_{key}"
    prefixed = os.getenv(prefixed_key)
    if prefixed is not None and prefixed.strip() != "":
        return prefixed
    return os.getenv(key, default)


def _expand_path(raw_value: str, *, base_dir: Path = _PROJECT_ROOT) -> Path:
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def load_settings(profile_override: Optional[str] = None) -> Settings:
    _load_env_file(_ENV_FILE)

    profile = (profile_override or os.getenv("CODEX_PROXY_PROFILE", "work")).strip().lower()
    if not profile:
        raise ConfigError("CODEX_PROXY_PROFILE cannot be empty")

    proxy_host = _env_for_profile(profile, "PROXY_HOST", "127.0.0.1") or "127.0.0.1"
    proxy_port = _parse_int(
        "PROXY_PORT",
        _env_for_profile(profile, "PROXY_PORT", "8765"),
        default=8765,
    )

    proxy_static_api_key = (
        _env_for_profile(profile, "PROXY_STATIC_API_KEY", "") or ""
    ).strip()
    if not proxy_static_api_key:
        raise ConfigError(
            f"{profile.upper()}_PROXY_STATIC_API_KEY (or PROXY_STATIC_API_KEY) is required"
        )

    upstream_base_url = (
        _env_for_profile(profile, "UPSTREAM_BASE_URL", "https://api.openai.com/v1")
        or "https://api.openai.com/v1"
    ).strip()

    upstream_verify_ssl = _parse_bool(
        "VERIFY_SSL",
        _env_for_profile(profile, "VERIFY_SSL", "true"),
        default=True,
    )

    upstream_static_api_key = (
        _env_for_profile(profile, "UPSTREAM_API_KEY", "") or ""
    ).strip()

    oauth_token_endpoint = (_env_for_profile(profile, "OAUTH_TOKEN_ENDPOINT", "") or "").strip()
    oauth_client_id = (_env_for_profile(profile, "OAUTH_CLIENT_ID", "") or "").strip()
    oauth_client_secret = (_env_for_profile(profile, "OAUTH_CLIENT_SECRET", "") or "").strip()
    oauth_scope = (_env_for_profile(profile, "OAUTH_SCOPE", "") or "").strip()

    oauth: Optional[OAuthConfig] = None
    oauth_fields = [oauth_token_endpoint, oauth_client_id, oauth_client_secret]
    if any(oauth_fields):
        if not all(oauth_fields):
            raise ConfigError(
                "OAuth config is incomplete. Set OAUTH_TOKEN_ENDPOINT, OAUTH_CLIENT_ID, and OAUTH_CLIENT_SECRET."
            )
        oauth = OAuthConfig(
            token_endpoint=oauth_token_endpoint,
            client_id=oauth_client_id,
            client_secret=oauth_client_secret,
            scope=oauth_scope,
            refresh_buffer_minutes=_parse_int(
                "OAUTH_REFRESH_BUFFER_MINUTES",
                _env_for_profile(profile, "OAUTH_REFRESH_BUFFER_MINUTES", "5"),
                default=5,
            ),
        )

    default_max_tokens = _parse_int(
        "DEFAULT_MAX_TOKENS",
        _env_for_profile(profile, "DEFAULT_MAX_TOKENS", "32768"),
        default=32768,
    )
    default_max_output_tokens = _parse_int(
        "DEFAULT_MAX_OUTPUT_TOKENS",
        _env_for_profile(profile, "DEFAULT_MAX_OUTPUT_TOKENS", str(default_max_tokens)),
        default=default_max_tokens,
    )

    model_mapping = _parse_model_mapping(
        (_env_for_profile(profile, "MODEL_MAPPING", "") or "").strip()
    )

    codex_model_provider = (
        _env_for_profile(profile, "CODEX_MODEL_PROVIDER", "codex-launcher-proxy")
        or "codex-launcher-proxy"
    ).strip()
    codex_model = (
        _env_for_profile(profile, "CODEX_MODEL", "gpt-5.3-codex")
        or "gpt-5.3-codex"
    ).strip()
    codex_env_key = (
        _env_for_profile(profile, "CODEX_ENV_KEY", "CODEX_PROXY_API_KEY")
        or "CODEX_PROXY_API_KEY"
    ).strip()
    codex_config_path = _expand_path(
        _env_for_profile(profile, "CODEX_CONFIG_PATH", "~/.codex/config.toml")
        or "~/.codex/config.toml"
    )
    codex_app_path = _expand_path(
        _env_for_profile(profile, "CODEX_APP_PATH", "/Applications/Codex.app")
        or "/Applications/Codex.app"
    )
    codex_desktop_repo_url = (
        _env_for_profile(
            profile,
            "CODEX_DESKTOP_REPO_URL",
            "https://github.com/openai/codex",
        )
        or "https://github.com/openai/codex"
    ).strip()
    model_config_path = _expand_path(
        _env_for_profile(profile, "MODEL_CONFIG_PATH", "models.json")
        or "models.json"
    )

    log_level = (os.getenv("LOG_LEVEL", "INFO") or "INFO").strip().upper()

    return Settings(
        profile=profile,
        proxy=ProxyConfig(
            host=proxy_host,
            port=proxy_port,
            static_api_key=proxy_static_api_key,
        ),
        upstream=UpstreamConfig(
            base_url=upstream_base_url,
            verify_ssl=upstream_verify_ssl,
            static_api_key=upstream_static_api_key,
        ),
        oauth=oauth,
        token_defaults=TokenDefaults(
            chat_max_tokens=default_max_tokens,
            responses_max_output_tokens=default_max_output_tokens,
        ),
        codex=CodexConfig(
            model_provider=codex_model_provider,
            model=codex_model,
            env_key=codex_env_key,
            config_path=codex_config_path,
            app_path=codex_app_path,
            desktop_repo_url=codex_desktop_repo_url,
        ),
        model_mapping=model_mapping,
        model_config_path=model_config_path,
        log_level=log_level,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
