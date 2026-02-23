"""OAuth2 token manager with scheduled refresh."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

from .config import OAuthConfig

logger = logging.getLogger(__name__)


class OAuthTokenError(RuntimeError):
    """Raised when a valid OAuth token cannot be obtained."""


class OAuthManager:
    """Manages OAuth2 client-credentials token acquisition and refresh."""

    def __init__(self, config: OAuthConfig, *, verify_ssl: bool) -> None:
        self._config = config
        self._verify_ssl = verify_ssl
        self._access_token: Optional[str] = None
        self._expires_at_epoch: Optional[float] = None
        self._refresh_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def get_token(self) -> str:
        """Return a valid token, fetching if needed."""
        with self._lock:
            if not self._access_token or self._needs_refresh_locked():
                self._fetch_token_locked()

            if not self._access_token:
                raise OAuthTokenError("OAuth token is unavailable")

            return self._access_token

    def stop(self) -> None:
        """Stop scheduled refresh timer."""
        with self._lock:
            if self._refresh_timer:
                self._refresh_timer.cancel()
                self._refresh_timer = None

    def _needs_refresh_locked(self) -> bool:
        if self._expires_at_epoch is None:
            return True
        remaining = self._expires_at_epoch - time.time()
        return remaining <= (self._config.refresh_buffer_minutes * 60)

    def _fetch_token_locked(self) -> None:
        """Fetch and cache a new token. Call under lock."""
        payload = {"grant_type": "client_credentials"}
        if self._config.scope:
            payload["scope"] = self._config.scope

        timeout = self._config.request_timeout_seconds

        response = requests.post(
            self._config.token_endpoint,
            data=payload,
            auth=HTTPBasicAuth(self._config.client_id, self._config.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
            verify=self._verify_ssl,
        )

        if response.status_code in {400, 401}:
            body_payload = {
                **payload,
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
            }
            response = requests.post(
                self._config.token_endpoint,
                data=body_payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=timeout,
                verify=self._verify_ssl,
            )

        if not response.ok:
            detail = response.text
            raise OAuthTokenError(
                f"OAuth token request failed ({response.status_code}): {detail}"
            )

        data = response.json()
        token = str(data.get("access_token") or "").strip()
        if not token:
            raise OAuthTokenError("OAuth response did not include access_token")

        expires_in = int(data.get("expires_in", 3600))
        self._access_token = token
        self._expires_at_epoch = time.time() + expires_in
        self._schedule_refresh_locked()
        logger.info("OAuth token acquired; expires in %ss", expires_in)

    def _schedule_refresh_locked(self) -> None:
        if self._refresh_timer:
            self._refresh_timer.cancel()
            self._refresh_timer = None

        if self._expires_at_epoch is None:
            return

        refresh_in_seconds = max(
            int(self._expires_at_epoch - time.time())
            - (self._config.refresh_buffer_minutes * 60),
            1,
        )

        timer = threading.Timer(refresh_in_seconds, self._refresh_in_background)
        timer.daemon = True
        timer.start()
        self._refresh_timer = timer

    def _refresh_in_background(self) -> None:
        with self._lock:
            try:
                self._fetch_token_locked()
            except Exception as exc:
                logger.warning("Background OAuth refresh failed: %s", exc)
