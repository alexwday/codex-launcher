"""FastAPI proxy app for Codex Desktop traffic."""

from __future__ import annotations

import hmac
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from .call_log import CallLog
from .codex_manager import configure_codex, get_codex_status, launch_codex
from .config import Settings, get_settings
from .model_mapping import ModelMapper
from .models import SelectedModelStore, load_model_catalog
from .oauth_manager import OAuthManager, OAuthTokenError
from .request_normalizer import (
    RequestNormalizationError,
    normalize_chat_completions_request,
    normalize_responses_request,
)
from .security import configure_rbc_security_certs

logger = logging.getLogger(__name__)
_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "dashboard.html"


@dataclass
class RuntimeContext:
    settings: Settings
    mapper: ModelMapper
    models: SelectedModelStore
    call_log: CallLog
    oauth_manager: Optional[OAuthManager]
    ssl_provider: Optional[str]


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    logging.basicConfig(
        level=getattr(logging, resolved_settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ssl_provider = configure_rbc_security_certs()
    models = load_model_catalog(
        resolved_settings.model_config_path,
        profile=resolved_settings.profile,
        default_model_id=resolved_settings.codex.model,
        default_upstream_model=resolved_settings.model_mapping.get(
            resolved_settings.codex.model,
            resolved_settings.codex.model,
        ),
        default_max_output_tokens=resolved_settings.token_defaults.responses_max_output_tokens,
    )

    oauth_manager: Optional[OAuthManager] = None
    if resolved_settings.oauth is not None:
        oauth_manager = OAuthManager(
            resolved_settings.oauth,
            verify_ssl=resolved_settings.upstream.verify_ssl,
        )
        try:
            oauth_manager.get_token()
            logger.info("Initial OAuth token fetch succeeded")
        except OAuthTokenError as exc:
            logger.warning("Initial OAuth token fetch failed: %s", exc)

    app = FastAPI(title="Codex Launcher Proxy", version="0.2.0")
    app.state.context = RuntimeContext(
        settings=resolved_settings,
        mapper=ModelMapper(resolved_settings.model_mapping),
        models=SelectedModelStore(models, resolved_settings.codex.model),
        call_log=CallLog(),
        oauth_manager=oauth_manager,
        ssl_provider=ssl_provider,
    )

    @app.on_event("shutdown")
    def _shutdown() -> None:
        context: RuntimeContext = app.state.context
        if context.oauth_manager:
            context.oauth_manager.stop()

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _TEMPLATE_PATH.read_text(encoding="utf-8")

    @app.get("/health")
    def health() -> dict[str, Any]:
        context: RuntimeContext = app.state.context
        selected = context.models.selected()
        return {
            "status": "ok",
            "profile": context.settings.profile,
            "proxy_host": context.settings.proxy.host,
            "proxy_port": context.settings.proxy.port,
            "oauth_enabled": context.oauth_manager is not None,
            "ssl_provider": context.ssl_provider,
            "selected_model": selected.id,
            "selected_upstream_model": selected.upstream_model,
        }

    @app.get("/api/config")
    def api_config() -> dict[str, Any]:
        context: RuntimeContext = app.state.context
        settings = context.settings
        selected = context.models.selected()
        return {
            "profile": settings.profile,
            "localBaseUrl": f"http://{settings.proxy.host}:{settings.proxy.port}",
            "upstreamBaseUrl": settings.upstream.base_url,
            "verifySsl": settings.upstream.verify_ssl,
            "oauthEnabled": context.oauth_manager is not None,
            "sslProvider": context.ssl_provider,
            "codex": {
                "modelProvider": settings.codex.model_provider,
                "model": selected.id,
                "envKey": settings.codex.env_key,
                "configPath": str(settings.codex.config_path),
                "cliPath": settings.codex.cli_path,
                "workspacePath": str(settings.codex.workspace_path),
                "sourcePath": str(settings.codex.cli_source_path),
                "repoUrl": settings.codex.cli_repo_url,
                "releaseBaseUrl": settings.codex.cli_release_base_url,
            },
        }

    @app.get("/api/models")
    def api_models() -> dict[str, Any]:
        context: RuntimeContext = app.state.context
        selected = context.models.selected()
        return {"selectedModel": selected.to_dict(), "models": context.models.list_models()}

    @app.post("/api/models/select")
    async def api_select_model(request: Request) -> dict[str, Any]:
        context: RuntimeContext = app.state.context
        payload = await _read_json_payload(request)
        model_id = str(payload.get("model") or "").strip()
        try:
            selected = context.models.select(model_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return {"success": True, "selectedModel": selected.to_dict()}

    @app.get("/api/calls")
    def api_calls(limit: int = Query(default=100, ge=0, le=500)) -> dict[str, Any]:
        context: RuntimeContext = app.state.context
        return {"calls": context.call_log.list(limit)}

    @app.post("/api/calls/clear")
    def api_clear_calls() -> dict[str, bool]:
        context: RuntimeContext = app.state.context
        context.call_log.clear()
        return {"success": True}

    @app.get("/api/codex/status")
    def api_codex_status(runDoctor: bool = False) -> dict[str, Any]:
        context: RuntimeContext = app.state.context
        return get_codex_status(context.settings, run_doctor=runDoctor).to_dict()

    @app.post("/api/codex/configure")
    def api_configure_codex() -> dict[str, Any]:
        context: RuntimeContext = app.state.context
        return configure_codex(context.settings, context.models.selected())

    @app.post("/api/codex/launch")
    def api_launch_codex() -> dict[str, Any]:
        context: RuntimeContext = app.state.context
        return launch_codex(context.settings, context.models.selected())

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        context: RuntimeContext = app.state.context
        _require_proxy_auth(request, context)
        payload = await _read_json_payload(request)
        selected = context.models.selected()

        try:
            normalized_payload = normalize_chat_completions_request(
                payload,
                mapper=context.mapper,
                default_max_tokens=selected.max_output_tokens,
                forced_model=selected.upstream_model,
            )
        except RequestNormalizationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        return _forward_post(
            context,
            endpoint="chat/completions",
            payload=normalized_payload,
            original_payload=payload,
            original_model=str(payload.get("model") or ""),
            upstream_model=selected.upstream_model,
            request_path="/v1/chat/completions",
        )

    @app.post("/v1/responses")
    async def responses(request: Request) -> Response:
        context: RuntimeContext = app.state.context
        _require_proxy_auth(request, context)
        payload = await _read_json_payload(request)
        selected = context.models.selected()

        try:
            normalized_payload = normalize_responses_request(
                payload,
                mapper=context.mapper,
                default_max_output_tokens=selected.max_output_tokens,
                forced_model=selected.upstream_model,
                force_store_false=True,
            )
        except RequestNormalizationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        return _forward_post(
            context,
            endpoint="responses",
            payload=normalized_payload,
            original_payload=payload,
            original_model=str(payload.get("model") or ""),
            upstream_model=selected.upstream_model,
            request_path="/v1/responses",
        )

    return app


def _require_proxy_auth(request: Request, context: RuntimeContext) -> None:
    expected = context.settings.proxy.static_api_key
    provided = request.headers.get("x-api-key", "").strip()

    if not provided:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            provided = auth_header[7:].strip()

    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing proxy API key",
        )


async def _read_json_payload(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {exc}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a JSON object",
        )

    return payload


def _forward_post(
    context: RuntimeContext,
    *,
    endpoint: str,
    payload: dict[str, Any],
    original_payload: dict[str, Any],
    original_model: str,
    upstream_model: str,
    request_path: str,
) -> Response:
    started_at = time.time()
    target_url = f"{context.settings.upstream.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"Content-Type": "application/json"}
    streaming = payload.get("stream") is True

    try:
        auth_header = _resolve_upstream_authorization(context)
    except OAuthTokenError as exc:
        context.call_log.add(
            started_at=started_at,
            method="POST",
            path=request_path,
            status_code=status.HTTP_502_BAD_GATEWAY,
            streaming=streaming,
            original_model=original_model,
            upstream_model=upstream_model,
            request_payload=original_payload,
            error=str(exc),
        )
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": {"message": f"OAuth token unavailable: {exc}"}},
        )

    if auth_header:
        headers["Authorization"] = auth_header

    try:
        upstream_response = requests.post(
            target_url,
            json=payload,
            headers=headers,
            timeout=(
                context.settings.upstream.connect_timeout_seconds,
                context.settings.upstream.read_timeout_seconds,
            ),
            verify=context.settings.upstream.verify_ssl,
            stream=streaming,
        )
    except requests.Timeout as exc:
        context.call_log.add(
            started_at=started_at,
            method="POST",
            path=request_path,
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            streaming=streaming,
            original_model=original_model,
            upstream_model=upstream_model,
            request_payload=original_payload,
            error=str(exc),
        )
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={"error": {"message": f"Upstream timeout: {exc}"}},
        )
    except requests.RequestException as exc:
        context.call_log.add(
            started_at=started_at,
            method="POST",
            path=request_path,
            status_code=status.HTTP_502_BAD_GATEWAY,
            streaming=streaming,
            original_model=original_model,
            upstream_model=upstream_model,
            request_payload=original_payload,
            error=str(exc),
        )
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": {"message": f"Upstream connection error: {exc}"}},
        )

    media_type = upstream_response.headers.get("content-type", "application/json")
    if streaming and upstream_response.ok:
        return StreamingResponse(
            _stream_and_log(
                context,
                upstream_response,
                started_at=started_at,
                request_path=request_path,
                original_payload=original_payload,
                original_model=original_model,
                upstream_model=upstream_model,
            ),
            status_code=upstream_response.status_code,
            media_type=media_type,
        )

    content = upstream_response.content
    response_payload = _json_or_text(content)
    context.call_log.add(
        started_at=started_at,
        method="POST",
        path=request_path,
        status_code=upstream_response.status_code,
        streaming=streaming,
        original_model=original_model,
        upstream_model=upstream_model,
        request_payload=original_payload,
        response_payload=response_payload,
        error="" if upstream_response.ok else _error_text(response_payload),
        usage=_extract_usage(response_payload),
    )
    return Response(
        content=content,
        status_code=upstream_response.status_code,
        media_type=media_type,
    )


def _stream_and_log(
    context: RuntimeContext,
    upstream_response: requests.Response,
    *,
    started_at: float,
    request_path: str,
    original_payload: dict[str, Any],
    original_model: str,
    upstream_model: str,
) -> Any:
    chunks: list[bytes] = []
    error = ""
    try:
        for chunk in upstream_response.iter_content(chunk_size=None):
            if not chunk:
                continue
            if sum(len(item) for item in chunks) < 4096:
                chunks.append(chunk)
            yield chunk
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        preview = b"".join(chunks).decode("utf-8", errors="replace")
        context.call_log.add(
            started_at=started_at,
            method="POST",
            path=request_path,
            status_code=upstream_response.status_code,
            streaming=True,
            original_model=original_model,
            upstream_model=upstream_model,
            request_payload=original_payload,
            response_payload=preview,
            error=error,
        )
        upstream_response.close()


def _resolve_upstream_authorization(context: RuntimeContext) -> str:
    if context.oauth_manager is not None:
        token = context.oauth_manager.get_token()
        return f"Bearer {token}"

    if context.settings.upstream.static_api_key:
        return f"Bearer {context.settings.upstream.static_api_key}"

    return ""


def _json_or_text(content: bytes) -> Any:
    try:
        return requests.models.complexjson.loads(content.decode("utf-8"))
    except Exception:
        return content.decode("utf-8", errors="replace")


def _extract_usage(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    usage = payload.get("usage")
    return usage if isinstance(usage, dict) else {}


def _error_text(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        if error:
            return str(error)
    return str(payload)[:500]
