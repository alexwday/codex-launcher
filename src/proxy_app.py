"""FastAPI proxy app for Codex Desktop traffic."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from .config import Settings, get_settings
from .model_mapping import ModelMapper
from .oauth_manager import OAuthManager, OAuthTokenError
from .request_normalizer import (
    RequestNormalizationError,
    normalize_chat_completions_request,
    normalize_responses_request,
)
from .security import configure_rbc_security_certs

logger = logging.getLogger(__name__)


@dataclass
class RuntimeContext:
    settings: Settings
    mapper: ModelMapper
    oauth_manager: Optional[OAuthManager]


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    logging.basicConfig(
        level=getattr(logging, resolved_settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    configure_rbc_security_certs()

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

    app = FastAPI(title="Codex Launcher Proxy", version="0.1.0")
    app.state.context = RuntimeContext(
        settings=resolved_settings,
        mapper=ModelMapper(resolved_settings.model_mapping),
        oauth_manager=oauth_manager,
    )

    @app.on_event("shutdown")
    def _shutdown() -> None:
        context: RuntimeContext = app.state.context
        if context.oauth_manager:
            context.oauth_manager.stop()

    @app.get("/health")
    def health() -> dict[str, str | int | bool]:
        context: RuntimeContext = app.state.context
        return {
            "status": "ok",
            "profile": context.settings.profile,
            "proxy_host": context.settings.proxy.host,
            "proxy_port": context.settings.proxy.port,
            "oauth_enabled": context.oauth_manager is not None,
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        context: RuntimeContext = app.state.context
        _require_proxy_auth(request, context)
        payload = await _read_json_payload(request)

        try:
            normalized_payload = normalize_chat_completions_request(
                payload,
                mapper=context.mapper,
                default_max_tokens=context.settings.token_defaults.chat_max_tokens,
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
        )

    @app.post("/v1/responses")
    async def responses(request: Request) -> Response:
        context: RuntimeContext = app.state.context
        _require_proxy_auth(request, context)
        payload = await _read_json_payload(request)

        try:
            normalized_payload = normalize_responses_request(
                payload,
                mapper=context.mapper,
                default_max_output_tokens=context.settings.token_defaults.responses_max_output_tokens,
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
        )

    return app


def _require_proxy_auth(request: Request, context: RuntimeContext) -> None:
    expected = context.settings.proxy.static_api_key
    provided = request.headers.get("x-api-key", "").strip()

    if not provided:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            provided = auth_header[7:].strip()

    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing proxy API key",
        )


async def _read_json_payload(request: Request) -> dict:
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


def _forward_post(context: RuntimeContext, *, endpoint: str, payload: dict) -> Response:
    target_url = f"{context.settings.upstream.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"Content-Type": "application/json"}

    auth_header = _resolve_upstream_authorization(context)
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
        )
    except requests.Timeout as exc:
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={"error": {"message": f"Upstream timeout: {exc}"}},
        )
    except requests.RequestException as exc:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": {"message": f"Upstream connection error: {exc}"}},
        )

    media_type = upstream_response.headers.get("content-type", "application/json")
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        media_type=media_type,
    )


def _resolve_upstream_authorization(context: RuntimeContext) -> str:
    if context.oauth_manager is not None:
        token = context.oauth_manager.get_token()
        return f"Bearer {token}"

    if context.settings.upstream.static_api_key:
        return f"Bearer {context.settings.upstream.static_api_key}"

    return ""
