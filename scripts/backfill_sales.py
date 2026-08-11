"""Import historical Partner Ads sales into the local database.

Idempotent (safe to re-run) and notification-free: old sales are stored and
marked as already handled, so no Telegram messages are sent. Use this once to
fill in history the live monitor never imported.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config import load_config
from core.database import Database
from core.partner_ads_backfill import backfill_sales
from partner_ads import PartnerAdsService


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Importér historiske Partner Ads-salg uden notifikationer."
    )
    parser.add_argument(
        "--start", type=_parse_date, default=date(2020, 1, 1),
        help="Startdato (YYYY-MM-DD, standard 2020-01-01).",
    )
    parser.add_argument(
        "--end", type=_parse_date, default=date.today(),
        help="Slutdato (YYYY-MM-DD, standard i dag).",
    )
    arguments = parser.parse_args()

    config = load_config()
    database = Database(config.database_file)
    database.initialize()
    partner_ads = PartnerAdsService(
        config.partner_ads_base_url, config.partner_ads_key
    )
    try:
        result = backfill_sales(
            database, partner_ads,
            start_date=arguments.start, end_date=arguments.end,
        )
    finally:
        database.close()

    print(
        f"Backfill {arguments.start} til {arguments.end}: "
        f"{result['fetched']} hentet, {result['created']} nye, "
        f"{result['updated']} opdaterede, {result['unchanged']} uændrede, "
        f"{result['duplicates']} dubletter. Ingen notifikationer sendt."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
