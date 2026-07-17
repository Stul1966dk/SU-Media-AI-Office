"""Continuous Affiliate Manager monitoring."""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.database import Database
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry
from agents.decision_engine import DecisionEngine, Recommendation
from agents.project_manager import ProjectManager

from config import Config, load_config
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


def synchronize_websites(
    database: Database,
    logger: logging.Logger,
) -> WebsiteRegistry:
    """Synchronize Website Registry without blocking Affiliate Manager."""
    print("Website Registry")
    print()
    registry = WebsiteRegistry(database)
    try:
        result = registry.sync()
    except FileNotFoundError:
        warning = "ADVARSEL: data/websites.csv blev ikke fundet."
        print(warning)
        logger.warning("Website Registry CSV blev ikke fundet.")
        print()
        return registry
    except (OSError, UnicodeError, ValueError) as error:
        print(f"ADVARSEL: Website Registry kunne ikke importeres: {error}")
        logger.warning("Website Registry kunne ikke importeres: %s", error)
        print()
        return registry

    print(f"{result.total} websites fundet")
    print()
    print(f"+ {result.created} nye websites")
    print(f"~ {result.updated} opdaterede websites")
    print(f"- {result.phased_out} nye websites markeret som phasing_out")
    print()
    print("Import gennemført")
    print()
    return registry


def print_recommendation(recommendation: Recommendation | None) -> None:
    """Print the Decision Engine's top recommendation."""
    print("Dagens vigtigste opgave")
    print()
    if recommendation is None:
        print("Ingen aktive websites at vurdere.")
        print()
        return

    print("Website")
    print(recommendation.website)
    print()
    print("Anbefaling")
    print(recommendation.recommended_action)
    print()
    print("Årsag")
    print(recommendation.reason)
    print()
    print(f"Score: {recommendation.score}")
    print()


def print_next_task(task: dict[str, object] | None) -> None:
    """Print the Project Manager's next executable task."""
    print("Næste anbefalede opgave")
    print()
    if task is None:
        print("Ingen klar opgave.")
        print()
        return

    print("Website")
    print(task["website_id"])
    print()
    print("Projekt")
    print(task["project_title"])
    print()
    print("Delprojekt")
    print(task["subproject_title"])
    print()
    print("Opgave")
    print(task["title"])
    print()
    print("Ansvarlig agent")
    print(task["assigned_agent"])
    print()
    print("Forventet tid")
    print(f"{task['estimated_minutes']} minutter")
    print()
    print("Begrundelse")
    print(task["reason"])
    print()


def run_check(
    partner_ads: PartnerAdsService,
    telegram: TelegramService,
    database: Database,
    logger: logging.Logger,
) -> tuple[int, int]:
    """Run one fetch, notification, and persistence cycle."""
    checked_at = datetime.now().astimezone()
    print(f"Kontroltidspunkt: {checked_at.strftime(DATE_TIME_FORMAT)}")

    _, sales = partner_ads.fetch_sales()
    print(f"Antal hentede salg: {len(sales)}")

    if not database.is_baseline_initialized():
        database.initialize_sales_baseline(sales)
        print("Første kørsel: eksisterende salg registreret uden notifikationer.")
        print("Antal nye salg: 0")
        logger.info("Baseline initialiseret med %d eksisterende salg.", len(sales))
        return len(sales), 0

    new_sales: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for sale in sales:
        kombiid = sale["kombiid"]
        if kombiid not in seen_ids and not database.sale_exists(kombiid):
            new_sales.append(sale)
            seen_ids.add(kombiid)
    print(f"Antal nye salg: {len(new_sales)}")

    for sale in new_sales:
        daily_commission = database.get_today_commission(
            sale["dato"]
        ) + Decimal(sale["provision"])
        telegram.send_sale(sale, daily_commission)
        database.save_sale(sale)

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
    database = Database(config.database_file)
    database.initialize()
    website_registry = synchronize_websites(database, logger)
    task_engine = TaskEngine(database)
    project_manager = ProjectManager(
        task_engine,
        website_registry,
        database,
    )
    robotland_project_id = project_manager.ensure_robotland_test_project()
    decision_engine = DecisionEngine(
        website_registry,
        database,
        project_manager,
    )
    decision_engine.get_top_recommendation()
    print_next_task(project_manager.choose_next_task(robotland_project_id))
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
