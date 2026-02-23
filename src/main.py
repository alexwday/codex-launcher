"""Application entrypoint for running the proxy server."""

from __future__ import annotations

import uvicorn

from .config import get_settings
from .proxy_app import create_app


def main() -> None:
    settings = get_settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.proxy.host, port=settings.proxy.port)


if __name__ == "__main__":
    main()
