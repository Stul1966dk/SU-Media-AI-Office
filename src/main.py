"""Continuous Affiliate Manager monitoring."""

import argparse
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from config import Config, load_config
from models import SalesDatabase
from partner_ads import PartnerAdsService
from telegram_service import TelegramService


CHECK_INTERVAL_SECONDS = 30 * 60
DATE_TIME_FORMAT = "%d-%m-%Y %H:%M:%S"


def configure_logging(project_root: Path) -> logging.Logger:
    """Configure file logging without credentials or request URLs."""
    log_directory = project_root / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_directory / "affiliate_manager.log",
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        encoding="utf-8",
    )
    return logging.getLogger("affiliate_manager")


def run_check(
    partner_ads: PartnerAdsService,
    telegram: TelegramService,
    database: SalesDatabase,
    logger: logging.Logger,
) -> tuple[int, int]:
    """Run one fetch, notification, and persistence cycle."""
    checked_at = datetime.now().astimezone()
    print(f"Kontroltidspunkt: {checked_at.strftime(DATE_TIME_FORMAT)}")

    _, sales = partner_ads.fetch_sales()
    print(f"Antal hentede salg: {len(sales)}")

    if not database.is_initialized():
        database.initialize_baseline(sales)
        print("Første kørsel: eksisterende salg registreret uden notifikationer.")
        print("Antal nye salg: 0")
        logger.info("Baseline initialiseret med %d eksisterende salg.", len(sales))
        return len(sales), 0

    new_sales = database.find_new(sales)
    print(f"Antal nye salg: {len(new_sales)}")

    for sale in new_sales:
        telegram.send_sale(sale)
        database.register(sale)

    logger.info(
        "Kontrol gennemført: %d hentede salg, %d nye salg.",
        len(sales),
        len(new_sales),
    )
    return len(sales), len(new_sales)


def monitor(config: Config, once: bool = False) -> None:
    """Monitor Partner-ads once or every 30 minutes."""
    project_root = config.sales_file.parent.parent
    logger = configure_logging(project_root)
    database = SalesDatabase(config.database_file)
    partner_ads = PartnerAdsService(
        base_url=config.partner_ads_base_url,
        key=config.partner_ads_key,
    )
    telegram = TelegramService(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
    )

    try:
        while True:
            try:
                run_check(partner_ads, telegram, database, logger)
            except Exception as error:
                # Service exceptions are deliberately sanitized before reaching here.
                print(f"FEJL: {error}")
                logger.error("Kontrol fejlede: %s", error)

            if once:
                return

            next_check = datetime.now().astimezone() + timedelta(
                seconds=CHECK_INTERVAL_SECONDS
            )
            print(f"Næste kontrol: {next_check.strftime(DATE_TIME_FORMAT)}")
            print()
            time.sleep(CHECK_INTERVAL_SECONDS)
    finally:
        database.close()


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="SU Media Affiliate Manager")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Kør én kontrol uden at vente på næste interval.",
    )
    return parser.parse_args()


def main() -> None:
    """Start Affiliate Manager."""
    print("-----------------------------------")
    print("SU Media AI Office")
    print("Affiliate Manager v0.1")
    print("Status: Starter...")
    print("-----------------------------------")
    print()

    try:
        config = load_config()
        monitor(config, once=parse_args().once)
    except (ValueError, OSError) as error:
        print(f"FEJL: {error}")
    except KeyboardInterrupt:
        print()
        print("Affiliate Manager stoppet med Ctrl+C.")


if __name__ == "__main__":
    main()
