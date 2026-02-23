"""Optional RBC SSL certificate configuration."""

from __future__ import annotations

import importlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def configure_rbc_security_certs() -> Optional[str]:
    """Enable RBC certificates when rbc_security is installed."""
    try:
        module = importlib.import_module("rbc_security")
    except ImportError:
        logger.info("rbc_security not installed; skipping certificate setup")
        return None
    except Exception as exc:
        logger.warning("Failed loading rbc_security: %s", exc)
        return None

    try:
        module.enable_certs()
        logger.info("Enabled certificates using rbc_security")
        return "rbc_security"
    except Exception as exc:
        logger.warning("rbc_security.enable_certs() failed: %s", exc)
        return None
