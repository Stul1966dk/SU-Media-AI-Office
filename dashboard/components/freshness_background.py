"""Once-per-session background verification of content freshness."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, MutableMapping

import streamlit as st

from core.content_freshness_review import ContentFreshnessReviewService
from dashboard.components.database import open_database


_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="content-freshness-review"
)
SESSION_KEY = "content_freshness_background_started"


def ensure_freshness_background(
    *, state: MutableMapping[str, Any] | None = None
) -> None:
    """Start one silent freshness review for this UI session."""
    current = state if state is not None else st.session_state
    if current.get(SESSION_KEY):
        return
    # Complete schema initialization before the worker opens its own
    # connection. This avoids concurrent first-open migrations.
    database = open_database()
    database.close()
    current[SESSION_KEY] = True
    _EXECUTOR.submit(_run)


def _run() -> None:
    database = open_database()
    try:
        ContentFreshnessReviewService(database).run()
    finally:
        database.close()
