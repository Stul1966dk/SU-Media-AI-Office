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

from core.agent_orchestrator import AgentOrchestrator
from core.database import Database
from core.dashboard import Dashboard
from core.knowledge_engine import KnowledgeEngine
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry
from agents.decision_engine import DecisionEngine
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
    registry = WebsiteRegistry(database)
    try:
        result = registry.sync()
    except FileNotFoundError:
        logger.warning("Website Registry CSV blev ikke fundet.")
        return registry
    except (OSError, UnicodeError, ValueError) as error:
        logger.warning("Website Registry kunne ikke importeres: %s", error)
        return registry

    logger.info(
        (
            "Website Registry synkroniseret: %d fundet, %d nye, "
            "%d opdaterede, %d nyligt udfasede."
        ),
        result.total,
        result.created,
        result.updated,
        result.phased_out,
    )
    return registry


def run_check(
    partner_ads: PartnerAdsService,
    telegram: TelegramService,
    database: Database,
    logger: logging.Logger,
) -> tuple[int, int]:
    """Run one fetch, notification, and persistence cycle."""
    checked_at = datetime.now().astimezone()

    _, sales = partner_ads.fetch_sales()

    if not database.is_baseline_initialized():
        database.initialize_sales_baseline(sales)
        logger.info("Baseline initialiseret med %d eksisterende salg.", len(sales))
        return len(sales), 0

    new_sales: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for sale in sales:
        kombiid = sale["kombiid"]
        if kombiid not in seen_ids and not database.sale_exists(kombiid):
            new_sales.append(sale)
            seen_ids.add(kombiid)
    for sale in new_sales:
        daily_commission = database.get_today_commission(
            sale["dato"]
        ) + Decimal(sale["provision"])
        telegram.send_sale(sale, daily_commission)
        database.save_sale(sale)

    logger.info(
        "Kontrol %s: %d hentede salg, %d nye salg.",
        checked_at.strftime(DATE_TIME_FORMAT),
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
    knowledge_engine = KnowledgeEngine(project_root / "knowledge")
    knowledge_document_count = knowledge_engine.initialize()
    logger.info(
        "Knowledge Engine initialiseret med %d dokumenter.",
        knowledge_document_count,
    )
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
    orchestrator = AgentOrchestrator(
        decision_engine=decision_engine,
        project_manager=project_manager,
        task_engine=task_engine,
        knowledge_engine=knowledge_engine,
        database=database,
        website_registry=website_registry,
    )
    registered_agents = orchestrator.initialize()
    orchestrator.run_once()
    orchestrator_counts = orchestrator.get_counts()
    logger.info(
        "Agent Orchestrator klar med %d registrerede agenter.",
        registered_agents,
    )
    recommendation = decision_engine.get_top_recommendation()
    if recommendation is not None:
        logger.info(
            "Decision Engine valgte %s: %s.",
            recommendation.item_type,
            recommendation.recommended_action,
        )
    next_task = project_manager.choose_next_task(robotland_project_id)
    print(
        Dashboard(database).render(
            next_task,
            knowledge_document_count=knowledge_document_count,
            orchestrator_counts=orchestrator_counts,
        )
    )
    print()
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
                logger.error("Kontrol fejlede: %s", error)

            if once:
                return

            next_check = datetime.now().astimezone() + timedelta(
                seconds=CHECK_INTERVAL_SECONDS
            )
            logger.info(
                "Næste kontrol: %s",
                next_check.strftime(DATE_TIME_FORMAT),
            )
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
