"""Hot-reload-safe persistence for traffic recommendation decisions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def find_open_task_by_title(
    database: Any, website_id: str, title: str
) -> dict[str, Any] | None:
    """Use the current Database API or its stable SQLite schema."""
    reader = getattr(database, "find_open_task_by_title", None)
    if reader:
        return reader(website_id, title)
    row = _connection(database).execute(
        """
        SELECT id, website_id, title, status
        FROM tasks
        WHERE website_id = ?
          AND LOWER(TRIM(title)) = LOWER(TRIM(?))
          AND status NOT IN ('completed', 'cancelled')
        ORDER BY id
        LIMIT 1
        """,
        (website_id, title),
    ).fetchone()
    return dict(row) if row else None


def upsert_decision(database: Any, values: dict[str, Any]) -> str:
    """Persist through the current method or the already-created table."""
    writer = getattr(
        database, "upsert_traffic_recommendation_decision", None
    )
    if writer:
        return str(writer(values))
    connection = _connection(database)
    key = str(values["recommendation_key"])
    existing = connection.execute(
        """
        SELECT id FROM traffic_recommendation_decisions
        WHERE recommendation_key = ?
        """,
        (key,),
    ).fetchone()
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with connection:
        connection.execute(
            """
            INSERT INTO traffic_recommendation_decisions (
                recommendation_key, website_id, task_type, target_url,
                measured_cause, title, description, priority, status,
                snoozed_until, evidence_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(recommendation_key) DO UPDATE SET
                website_id = excluded.website_id,
                task_type = excluded.task_type,
                target_url = excluded.target_url,
                measured_cause = excluded.measured_cause,
                title = excluded.title,
                description = excluded.description,
                priority = excluded.priority,
                status = excluded.status,
                snoozed_until = excluded.snoozed_until,
                evidence_json = excluded.evidence_json,
                updated_at = excluded.updated_at
            """,
            (
                key,
                str(values["website_id"]),
                str(values["task_type"]),
                str(values.get("target_url", "")),
                str(values.get("measured_cause", "")),
                str(values["title"]),
                str(values["description"]),
                str(values["priority"]),
                str(values["status"]),
                values.get("snoozed_until"),
                json.dumps(
                    values.get("evidence", {}),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                timestamp,
                timestamp,
            ),
        )
    return "updated" if existing else "created"


def get_decision(
    database: Any, recommendation_key: str
) -> dict[str, Any] | None:
    """Return one decision across current and stale Database classes."""
    reader = getattr(
        database, "get_traffic_recommendation_decision", None
    )
    if reader:
        return reader(recommendation_key)
    row = _connection(database).execute(
        """
        SELECT * FROM traffic_recommendation_decisions
        WHERE recommendation_key = ?
        """,
        (recommendation_key,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["evidence"] = json.loads(result.pop("evidence_json"))
    return result


def _connection(database: Any) -> Any:
    connection = getattr(database, "connection", None)
    if connection is None:
        raise RuntimeError("Databaseforbindelsen er ikke åben.")
    return connection
