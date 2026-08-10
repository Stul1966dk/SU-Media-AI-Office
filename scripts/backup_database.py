"""Create a consistent local backup of the AI Office database.

Uses the same database path as the dashboard (``SU_MEDIA_DATABASE_PATH`` or the
default ``data/affiliate_manager.db``) and stores snapshots in ``data/backups``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.local_backup import create_backup


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tag en konsistent lokal backup af AI Office-databasen."
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=14,
        help="Antal seneste backups der bevares (standard: 14).",
    )
    arguments = parser.parse_args()

    default_path = PROJECT_ROOT / "data" / "affiliate_manager.db"
    source = Path(os.getenv("SU_MEDIA_DATABASE_PATH", default_path))
    backup_dir = PROJECT_ROOT / "data" / "backups"

    result = create_backup(source, backup_dir, keep=arguments.keep)
    size_mb = result["size_bytes"] / (1024 * 1024)
    print(f"Backup oprettet: {result['backup_path'].name} ({size_mb:.1f} MB)")
    if result["pruned"]:
        print(f"Slettede {len(result['pruned'])} ældre backup(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
