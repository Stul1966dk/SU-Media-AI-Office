"""Consistent local snapshots of the SQLite database.

The SQLite backup API is used instead of a plain file copy so the snapshot is
internally consistent even while the running app holds the database open.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path


BACKUP_PREFIX = "affiliate_manager_"
BACKUP_SUFFIX = ".db"

# Only files this module created (prefix + YYYYMMDD_HHMMSS, with an optional
# collision counter) are eligible for pruning. Manually named historical
# backups such as ``affiliate_manager_before_sprint3_...db`` are left alone.
_AUTO_BACKUP_RE = re.compile(r"^affiliate_manager_\d{8}_\d{6}(?:_\d+)?\.db$")


def create_backup(
    source_path: Path,
    backup_dir: Path,
    *,
    keep: int = 14,
    now: datetime | None = None,
) -> dict:
    """Write a consistent snapshot and prune to the newest ``keep`` backups.

    Returns a summary with the created ``backup_path``, its ``size_bytes`` and
    the list of ``pruned`` backup paths that were removed.
    """
    source_path = Path(source_path)
    backup_dir = Path(backup_dir)
    if not source_path.exists():
        raise FileNotFoundError(f"Databasen findes ikke: {source_path}")
    if keep < 1:
        raise ValueError("keep skal være mindst 1.")

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{BACKUP_PREFIX}{timestamp}{BACKUP_SUFFIX}"

    # Guard against overwriting a snapshot taken within the same second.
    counter = 1
    while backup_path.exists():
        backup_path = (
            backup_dir / f"{BACKUP_PREFIX}{timestamp}_{counter}{BACKUP_SUFFIX}"
        )
        counter += 1

    source = sqlite3.connect(source_path)
    try:
        destination = sqlite3.connect(backup_path)
        try:
            with destination:
                source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    pruned = _prune_old_backups(backup_dir, keep=keep)
    return {
        "backup_path": backup_path,
        "size_bytes": backup_path.stat().st_size,
        "pruned": pruned,
    }


def _prune_old_backups(backup_dir: Path, *, keep: int) -> list[Path]:
    """Delete the oldest auto-backups so at most ``keep`` remain.

    Manually named backups are ignored: they never count toward ``keep`` and are
    never deleted.
    """
    backups = sorted(
        (
            path
            for path in backup_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}")
            if _AUTO_BACKUP_RE.match(path.name)
        ),
        key=lambda path: path.name,
    )
    to_remove = backups[:-keep] if len(backups) > keep else []
    for path in to_remove:
        path.unlink()
    return to_remove
