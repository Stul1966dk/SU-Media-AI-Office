"""Sanitized structured logging for lifecycle actions."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any


def log_action(
    logger: logging.Logger,
    *,
    action: str,
    website: str = "",
    target_url: str = "",
    record_ids: dict[str, Any] | None = None,
    previous_status: str = "",
    new_status: str = "",
    error: Exception | None = None,
) -> None:
    """Log identifiers and status only; never prompts or credentials."""
    payload = {
        "action": action,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "website": website,
        "url": target_url,
        "record_ids": record_ids or {},
        "previous_status": previous_status,
        "new_status": new_status,
        "error_type": type(error).__name__ if error else "",
        "error_message": str(error)[:300] if error else "",
    }
    logger.info("workflow_action", extra={"workflow": payload})
