"""Application configuration for Affiliate Manager."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Application configuration loaded from the local environment."""

    sales_file: Path
    database_file: Path
    partner_ads_base_url: str
    partner_ads_key: str
    telegram_bot_token: str
    telegram_chat_id: str


def load_config() -> Config:
    """Load application configuration from the project's .env file."""
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")

    return Config(
        sales_file=project_root / "data" / "sales.json",
        database_file=project_root / "data" / "affiliate_manager.db",
        partner_ads_base_url=os.getenv("PARTNER_ADS_BASE_URL", "").strip(),
        partner_ads_key=os.getenv("PARTNER_ADS_KEY", "").strip(),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )
