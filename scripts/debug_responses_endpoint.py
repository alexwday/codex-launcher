#!/usr/bin/env python3
"""Diagnose upstream Responses API URL/auth combinations.

This script loads the same .env/profile settings as codex-launcher, enables
rbc_security certificates when available, acquires OAuth tokens when configured,
and probes likely Responses API paths derived from UPSTREAM_BASE_URL.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Settings, load_settings  # noqa: E402
from src.model_mapping import ModelMapper  # noqa: E402
from src.models import SelectedModelStore, load_model_catalog  # noqa: E402
from src.oauth_manager import OAuthManager  # noqa: E402
from src.request_normalizer import normalize_responses_request  # noqa: E402
from src.security import configure_rbc_security_certs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe possible upstream Responses API URLs using codex-launcher env/auth settings."
    )
    parser.add_argument("--profile", default=None, help="Config profile override, for example work")
    parser.add_argument("--model", default=None, help="Codex-facing model id from models.json")
    parser.add_argument(
        "--input",
        default="Respond with exactly: responses endpoint ok",
        help="Small Responses API input string to send",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=64,
        help="Small max_output_tokens value for diagnostics",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Read timeout seconds for each probe",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print candidate URLs and payload without sending requests",
    )
    parser.add_argument(
        "--skip-chat-sanity",
        action="store_true",
        help="Do not send a legacy chat/completions sanity check",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of text",
    )
    args = parser.parse_args()

    settings = load_settings(args.profile)
    ssl_provider = configure_rbc_security_certs()
    selected_model = _select_model(settings, args.model)
    payload = normalize_responses_request(
        {
            "model": selected_model.id,
            "input": args.input,
            "store": False,
            "max_output_tokens": args.max_output_tokens,
        },
        mapper=ModelMapper(settings.model_mapping),
        default_max_output_tokens=args.max_output_tokens,
        forced_model=selected_model.upstream_model,
        force_store_false=True,
    )

    urls = _candidate_response_urls(settings.upstream.base_url)
    chat_url = _join_url(settings.upstream.base_url, "chat/completions")
    oauth_manager = None
    try:
        headers, auth_summary, oauth_manager = _build_headers(settings)
    except Exception as exc:
        report = {
            "profile": settings.profile,
            "upstreamBaseUrl": settings.upstream.base_url,
            "verifySsl": settings.upstream.verify_ssl,
            "sslProvider": ssl_provider or "system/default",
            "auth": {
                "type": "oauth" if settings.oauth is not None else "static_api_key",
                "tokenAcquired": False,
                "errorType": type(exc).__name__,
                "error": str(exc),
            },
            "model": {
                "codexFacing": selected_model.id,
                "upstream": selected_model.upstream_model,
            },
            "results": [],
            "summary": "Authentication setup failed before endpoint probes were sent.",
        }
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            _print_report(report)
        return 3

    try:
        results: list[dict[str, Any]] = []
        if args.dry_run:
            results = [
                {
                    "name": item["name"],
                    "url": item["url"],
                    "method": "POST",
                    "dryRun": True,
                    "payload": payload,
                }
                for item in urls
            ]
            if not args.skip_chat_sanity:
                results.append(
                    {
                        "name": "chat sanity check",
                        "url": chat_url,
                        "method": "POST",
                        "dryRun": True,
                        "payload": _chat_payload(selected_model.upstream_model),
                    }
                )
        else:
            for item in urls:
                results.append(
                    _post_probe(
                        name=item["name"],
                        url=item["url"],
                        payload=payload,
                        headers=headers,
                        settings=settings,
                        timeout=args.timeout,
                    )
                )
            if not args.skip_chat_sanity:
                results.append(
                    _post_probe(
                        name="chat sanity check",
                        url=chat_url,
                        payload=_chat_payload(selected_model.upstream_model),
                        headers=headers,
                        settings=settings,
                        timeout=args.timeout,
                    )
                )

        report = {
            "profile": settings.profile,
            "upstreamBaseUrl": settings.upstream.base_url,
            "verifySsl": settings.upstream.verify_ssl,
            "sslProvider": ssl_provider or "system/default",
            "auth": auth_summary,
            "model": {
                "codexFacing": selected_model.id,
                "upstream": selected_model.upstream_model,
            },
            "results": results,
            "summary": _summarize(results),
        }

        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            _print_report(report)

        if args.dry_run:
            return 0
        return 0 if any(_is_success(result) for result in results if "responses" in result["name"]) else 2
    finally:
        if oauth_manager is not None:
            oauth_manager.stop()


def _select_model(settings: Settings, model_id: str | None):
    models = load_model_catalog(
        settings.model_config_path,
        profile=settings.profile,
        default_model_id=settings.codex.model,
        default_upstream_model=settings.model_mapping.get(settings.codex.model, settings.codex.model),
        default_max_output_tokens=settings.token_defaults.responses_max_output_tokens,
    )
    store = SelectedModelStore(models, model_id or settings.codex.model)
    return store.selected()


def _build_headers(settings: Settings) -> tuple[dict[str, str], dict[str, Any], OAuthManager | None]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if settings.oauth is not None:
        manager = OAuthManager(settings.oauth, verify_ssl=settings.upstream.verify_ssl)
        token = manager.get_token()
        headers["Authorization"] = f"Bearer {token}"
        return headers, {"type": "oauth", "tokenAcquired": True}, manager

    if settings.upstream.static_api_key:
        headers["Authorization"] = f"Bearer {settings.upstream.static_api_key}"
        return headers, {"type": "static_api_key", "tokenAcquired": False}, None

    return headers, {"type": "none", "tokenAcquired": False}, None


def _candidate_response_urls(base_url: str) -> list[dict[str, str]]:
    base_url = base_url.rstrip("/")
    without_v1 = _strip_trailing_path_segment(base_url, "v1")

    candidates = [
        {
            "name": "responses: configured base + /responses",
            "url": _join_url(base_url, "responses"),
        },
        {
            "name": "responses: remove trailing /v1, then /responses",
            "url": _join_url(without_v1, "responses"),
        },
        {
            "name": "responses: remove trailing /v1, then /v1/responses",
            "url": _join_url(without_v1, "v1/responses"),
        },
        {
            "name": "responses: remove trailing /v1, then /openai/v1/responses",
            "url": _join_url(without_v1, "openai/v1/responses"),
        },
    ]

    seen: set[str] = set()
    unique = []
    for item in candidates:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
    return unique


def _strip_trailing_path_segment(url: str, segment: str) -> str:
    parsed = urlsplit(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[-1].lower() == segment.lower():
        parts = parts[:-1]
    new_path = "/" + "/".join(parts) if parts else ""
    return urlunsplit((parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment)).rstrip("/")


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _chat_payload(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": "Respond with exactly: chat endpoint ok"}],
        "max_tokens": 16,
    }


def _post_probe(
    *,
    name: str,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    settings: Settings,
    timeout: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=(settings.upstream.connect_timeout_seconds, timeout),
            verify=settings.upstream.verify_ssl,
        )
    except requests.RequestException as exc:
        return {
            "name": name,
            "url": url,
            "ok": False,
            "errorType": type(exc).__name__,
            "error": str(exc),
            "durationMs": int((time.perf_counter() - started) * 1000),
        }

    body = _json_or_text(response)
    return {
        "name": name,
        "url": url,
        "ok": response.ok,
        "statusCode": response.status_code,
        "durationMs": int((time.perf_counter() - started) * 1000),
        "contentType": response.headers.get("content-type", ""),
        "bodyPreview": _preview(body),
        "errorHint": _error_hint(response.status_code, body),
    }


def _json_or_text(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


def _preview(value: Any, max_chars: int = 2000) -> Any:
    if isinstance(value, dict):
        return _redact(value)
    if isinstance(value, list):
        return [_redact(item) for item in value[:5]]
    text = str(value)
    return text[:max_chars]


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key.lower() in {"access_token", "id_token", "client_secret", "api_key", "authorization"}:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value[:10]]
    return value


def _error_hint(status_code: int, body: Any) -> str:
    text = json.dumps(body) if isinstance(body, (dict, list)) else str(body)
    lowered = text.lower()
    if 200 <= status_code < 300:
        return "success"
    if status_code in {401, 403}:
        return "auth/entitlement problem; URL reached an authenticated service"
    if status_code == 404 or "unknown endpoint" in lowered or "not found" in lowered:
        return "path problem; compare which candidate URL produced this"
    if status_code == 400:
        return "request shape/model problem or endpoint mismatch"
    if status_code >= 500:
        return "upstream server/gateway problem"
    return "check response body"


def _is_success(result: dict[str, Any]) -> bool:
    return bool(result.get("ok")) and int(result.get("statusCode") or 0) < 300


def _summarize(results: list[dict[str, Any]]) -> str:
    response_results = [result for result in results if "responses" in result["name"]]
    successes = [result for result in response_results if _is_success(result)]
    if successes:
        return f"Responses API succeeded at: {successes[0]['url']}"

    auth_like = [result for result in response_results if result.get("statusCode") in {401, 403}]
    if auth_like:
        return "Responses URLs were reachable but auth/entitlement failed for at least one candidate."

    path_like = [
        result
        for result in response_results
        if result.get("statusCode") == 404
        or "unknown endpoint" in json.dumps(result.get("bodyPreview", "")).lower()
    ]
    if len(path_like) == len(response_results):
        return "All Responses candidates looked like endpoint/path failures."

    return "No Responses candidate succeeded. Compare status/body previews above."


def _print_report(report: dict[str, Any]) -> None:
    print("Codex Launcher Responses API Diagnostic")
    print("=" * 40)
    print(f"Profile: {report['profile']}")
    print(f"Upstream base URL: {report['upstreamBaseUrl']}")
    print(f"SSL verify: {report['verifySsl']} ({report['sslProvider']})")
    print(f"Auth: {report['auth']['type']} token_acquired={report['auth']['tokenAcquired']}")
    print(f"Model: {report['model']['codexFacing']} -> {report['model']['upstream']}")
    print()

    for index, result in enumerate(report["results"], start=1):
        print(f"[{index}] {result['name']}")
        print(f"POST {result['url']}")
        if result.get("dryRun"):
            print("Dry run: request not sent")
            print(json.dumps(result["payload"], indent=2, sort_keys=True))
            print()
            continue
        if "statusCode" in result:
            print(
                f"Status: {result['statusCode']} ok={result['ok']} "
                f"duration_ms={result['durationMs']} content_type={result.get('contentType', '')}"
            )
            print(f"Hint: {result.get('errorHint', '')}")
            print(json.dumps(result.get("bodyPreview"), indent=2, sort_keys=True))
        else:
            print(
                f"Error: {result.get('errorType')} duration_ms={result.get('durationMs')}\n"
                f"{result.get('error')}"
            )
        print()

    print("Summary")
    print("-" * 40)
    print(report["summary"])


if __name__ == "__main__":
    raise SystemExit(main())
