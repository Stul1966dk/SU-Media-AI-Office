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
from core.search_console_service import (
    SearchConsoleDataSyncResult,
    SearchConsoleService,
)
from core.seo_history import analyze_all_sites
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry
from integrations.search_console import (
    SearchConsoleAuthenticationError,
    SearchConsoleConnector,
)
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


def format_search_console_sync(result: SearchConsoleDataSyncResult) -> str:
    """Format the required Search Console synchronization summary."""
    return "\n".join(
        [
            "Search Console synkronisering",
            "",
            f"Properties behandlet       {result.properties_processed}",
            f"Properties med fejl        {result.properties_failed}",
            f"Rækker oprettet             {result.rows_created}",
            f"Rækker opdateret            {result.rows_updated}",
            f"Periode                     {result.start_date} til {result.end_date}",
        ]
    )


def format_click_declines(comparisons: list[dict[str, object]]) -> str:
    """Format up to five websites with the largest absolute click decline."""
    declines = sorted(
        (
            item
            for item in comparisons
            if item["current_clicks"] < item["previous_clicks"]
        ),
        key=lambda item: item["current_clicks"] - item["previous_clicks"],
    )[:5]
    lines = ["Største klikfald", ""]
    if not declines:
        lines.append("Ingen klikfald i perioden.")
        return "\n".join(lines)

    for item in declines:
        click_change = _format_percent(item["click_change_percent"])
        impression_change = _format_percent(
            item["impression_change_percent"]
        )
        ctr_points = _format_points(item["ctr_change_points"], scale=100)
        position_difference = _format_points(item["position_difference"])
        lines.extend(
            [
                str(item["website_id"]),
                (
                    f"  Klik: {item['current_clicks']} "
                    f"({click_change})"
                ),
                (
                    f"  Visninger: {item['current_impressions']} "
                    f"({impression_change})"
                ),
                (
                    f"  CTR: {(item['current_ctr'] or 0) * 100:.2f}% "
                    f"({ctr_points} procentpoint)"
                ),
                (
                    "  Gennemsnitlig placering: "
                    f"{(item['current_position'] or 0):.2f} "
                    f"({position_difference})"
                ),
            ]
        )
    return "\n".join(lines)


def format_lowest_seo_scores(
    websites: list[dict[str, object]],
) -> str:
    """Format the five lowest current 28-day SEO scores."""
    lines = ["Laveste SEO-score", ""]
    if not websites:
        lines.append("Ingen SEO-analyser endnu.")
        return "\n".join(lines)
    for item in websites:
        lines.append(
            f"{item['website_id']:<30}"
            f"{float(item['score']):>5.1f}  {item['trend']}"
        )
    return "\n".join(lines)


def _format_percent(value: object) -> str:
    if value is None:
        return "ny/ingen tidligere værdi"
    return f"{float(value):+.1f}%"


def _format_points(value: object, scale: int = 1) -> str:
    if value is None:
        return "ingen sammenligning"
    return f"{float(value) * scale:+.2f}"


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
    search_console_status = {
        "connection_ok": False,
        "total": 0,
        "latest_sync": None,
        "stored_metrics": 0,
    }
    seo_health_status = {
        "growing": 0,
        "stable": 0,
        "declining": 0,
        "critical": 0,
    }
    search_console = SearchConsoleService(
        connector=SearchConsoleConnector(
            credentials_path=project_root / "credentials.json",
            token_path=project_root / "token.json",
        ),
        database=database,
        website_registry=website_registry,
        logger=logger,
    )
    try:
        search_result = search_console.synchronize()
        data_sync_result = search_console.sync_all_properties(days=180)
    except SearchConsoleAuthenticationError as error:
        logger.warning("Search Console-forbindelse fejlede: %s", error)
        print(f"Search Console-forbindelse fejlede: {error}")
    except Exception as error:
        logger.error(
            "Search Console-forbindelse fejlede (%s).",
            type(error).__name__,
        )
        print("Search Console-forbindelse fejlede. Se loggen.")
    else:
        summary = database.get_search_console_summary()
        search_console_status = {
            "connection_ok": search_result.connection_ok,
            "total": search_result.total,
            "latest_sync": summary["latest_sync"],
            "stored_metrics": summary["stored_metrics"],
        }
        logger.info(
            (
                "Search Console synkroniseret: %d properties, "
                "%d matchede, %d property-fejl."
            ),
            search_result.total,
            search_result.matched,
            data_sync_result.properties_failed,
        )
        print(format_search_console_sync(data_sync_result))
        print()
        print(format_click_declines(search_console.get_comparisons()))
        print()
    analyze_all_sites(database)
    seo_health_status = database.get_seo_health_summary(period="28d")
    print(format_lowest_seo_scores(database.get_lowest_seo_scores()))
    print()
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
            search_console_status=search_console_status,
            seo_health_status=seo_health_status,
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
