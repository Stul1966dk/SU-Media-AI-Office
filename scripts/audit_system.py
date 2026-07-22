"""Report AI Office integrity issues; optionally run safe repairs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.database import open_database
from core.system_audit import SystemIntegrityAudit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repair-safe", action="store_true",
        help="Kør kun dokumenterede, ikke-slettende reparationer.",
    )
    arguments = parser.parse_args()
    database = open_database()
    try:
        audit = SystemIntegrityAudit(database)
        result = audit.repair_safe() if arguments.repair_safe else audit.run()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
