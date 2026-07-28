"""Hot-reload-safe read access to the latest persisted traffic diagnoses."""

from __future__ import annotations

import json
from typing import Any


DIAGNOSIS_TABLES = {
    "search": (
        "search_console_diagnoses",
        "get_latest_search_console_diagnosis",
    ),
    "plausible": (
        "plausible_diagnoses",
        "get_latest_plausible_diagnosis",
    ),
}


def read_latest_diagnosis(
    database: Any,
    website_id: str,
    *,
    kind: str,
) -> dict[str, Any] | None:
    """Read through SQLite when a running Database class is stale."""
    if kind not in DIAGNOSIS_TABLES:
        raise ValueError("Ukendt diagnosetype.")
    table, reader_name = DIAGNOSIS_TABLES[kind]
    connection = getattr(database, "connection", None)
    if connection is not None:
        try:
            row = connection.execute(
                f"""
                SELECT analysis_json, created_at, updated_at
                FROM {table}
                WHERE website_id = ?
                ORDER BY period_end DESC, id DESC
                LIMIT 1
                """,
                (website_id,),
            ).fetchone()
            if row is not None:
                diagnosis = json.loads(str(row["analysis_json"]))
                diagnosis["created_at"] = row["created_at"]
                diagnosis["updated_at"] = row["updated_at"]
                return diagnosis
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
    reader = getattr(database, reader_name, None)
    return reader(website_id) if reader else None


def read_latest_diagnoses(
    database: Any,
    website_ids: list[str],
    *,
    kind: str,
) -> list[dict[str, Any]]:
    """Return available current diagnoses for the supplied websites."""
    return [
        diagnosis
        for website_id in website_ids
        if website_id
        if (
            diagnosis := read_latest_diagnosis(
                database, website_id, kind=kind
            )
        ) is not None
    ]
