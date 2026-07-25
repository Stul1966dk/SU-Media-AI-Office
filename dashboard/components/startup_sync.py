"""Once-per-session, non-blocking synchronization at Streamlit startup."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, MutableMapping

import streamlit as st

from core.data_refresh_service import DataRefreshService
from dashboard.components.database import open_database
from dashboard.components.formatting import format_datetime


SETTING_NAME = "sync_automatically_on_app_start"
SESSION_KEYS = {
    "checked": "startup_sync_check_completed",
    "started": "startup_sync_started",
    "completed": "startup_sync_completed",
    "failed": "startup_sync_failed",
    "started_at": "startup_sync_started_at",
    "completed_at": "startup_sync_completed_at",
    "future": "startup_sync_future",
    "enabled": "startup_sync_enabled",
    "error_type": "startup_sync_error_type",
}
_EXECUTOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="startup-data-refresh"
)


def ensure_startup_sync(
    *,
    state: MutableMapping[str, Any] | None = None,
    database_factory: Callable[[], Any] = open_database,
    executor: Any = _EXECUTOR,
) -> None:
    """Check the setting and start at most one refresh per UI session."""
    state = state if state is not None else st.session_state
    _poll_future(state)
    if state.get(SESSION_KEYS["checked"]):
        return

    database = database_factory()
    try:
        enabled = database.get_app_setting(SETTING_NAME, False)
    finally:
        database.close()
    state[SESSION_KEYS["checked"]] = True
    state[SESSION_KEYS["enabled"]] = enabled
    state.setdefault(SESSION_KEYS["started"], False)
    state.setdefault(SESSION_KEYS["completed"], False)
    state.setdefault(SESSION_KEYS["failed"], False)
    state.setdefault(SESSION_KEYS["started_at"], None)
    state.setdefault(SESSION_KEYS["completed_at"], None)
    state.setdefault(SESSION_KEYS["error_type"], None)
    if not enabled:
        return

    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    state[SESSION_KEYS["started"]] = True
    state[SESSION_KEYS["started_at"]] = started_at
    state[SESSION_KEYS["future"]] = executor.submit(
        run_startup_sync, started_at=started_at
    )


def run_startup_sync(
    *,
    started_at: str,
    database_factory: Callable[[], Any] = open_database,
    service_factory: Callable[[Any], Any] = DataRefreshService,
) -> dict[str, Any]:
    """Run an all-active refresh and record its distinct feature type."""
    database = database_factory()
    result: dict[str, Any] | None = None
    error: Exception | None = None
    try:
        result = service_factory(database).refresh_all(website_ids=None)
    except Exception as caught:
        error = caught
    completed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    failed_steps = int((result or {}).get("failed_steps", 0))
    failed = error is not None or failed_steps > 0
    error_type = (
        type(error).__name__ if error is not None
        else "PartialRefreshError" if failed_steps else None
    )
    error_message = (
        str(error) if error is not None
        else f"{failed_steps} trin fejlede." if failed_steps else None
    )
    try:
        database.save_feature_run(
            feature_name="data_refresh_app_start",
            status="error" if failed else "success",
            started_at=started_at,
            completed_at=completed_at,
            records_processed=len((result or {}).get("steps", [])),
            records_created=int((result or {}).get("completed_steps", 0)),
            records_updated=int((result or {}).get("skipped_steps", 0)),
            error_type=error_type,
            error_message=error_message,
        )
    finally:
        database.close()
    return {
        "completed": not failed,
        "failed": failed,
        "started_at": started_at,
        "completed_at": completed_at,
        "error_type": error_type,
    }


def _poll_future(state: MutableMapping[str, Any]) -> None:
    future = state.get(SESSION_KEYS["future"])
    if not isinstance(future, Future) or not future.done():
        return
    try:
        result = future.result()
    except Exception as error:
        result = {
            "completed": False,
            "failed": True,
            "completed_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "error_type": type(error).__name__,
        }
    state[SESSION_KEYS["completed"]] = bool(result["completed"])
    state[SESSION_KEYS["failed"]] = bool(result["failed"])
    state[SESSION_KEYS["completed_at"]] = result["completed_at"]
    state[SESSION_KEYS["error_type"]] = result.get("error_type")


def render_startup_sync_status() -> None:
    """Render the concise startup synchronization state on Dashboard."""
    _poll_future(st.session_state)
    state = st.session_state
    if not state.get(SESSION_KEYS["enabled"], False):
        st.info("Automatisk synkronisering er slået fra")
    elif state.get(SESSION_KEYS["failed"]):
        st.error("Synkronisering ved app-start fejlede")
    elif state.get(SESSION_KEYS["completed"]):
        st.success("Synkronisering ved app-start er gennemført")
    else:
        st.info("Synkronisering ved app-start kører")
    timestamp = (
        state.get(SESSION_KEYS["completed_at"])
        or state.get(SESSION_KEYS["started_at"])
    )
    if not timestamp:
        database = open_database()
        try:
            previous = database.get_feature_runs().get(
                "data_refresh_app_start"
            )
        finally:
            database.close()
        timestamp = previous.get("completed_at") if previous else None
    if timestamp:
        st.caption(
            "Seneste opstartssynkronisering: " + format_datetime(timestamp)
        )
