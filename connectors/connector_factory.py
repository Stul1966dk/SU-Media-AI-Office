"""Select connectors only from documented Website Discovery facts."""

from typing import Any

from core.database import Database

from .base_connector import BaseConnector
from .wordpress_connector import WordPressConnector


class ConnectorFactory:
    """Create the supported connector for a discovered website CMS."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self, website_id: str, *, session: Any | None = None,
        agent_orchestrator: Any | None = None,
    ) -> BaseConnector | None:
        profile = self.database.get_website_discovery_profile(website_id)
        if not profile or profile["cms"] != "wordpress":
            return None
        return WordPressConnector(
            website_id=website_id, database=self.database, session=session,
            agent_orchestrator=agent_orchestrator,
        )

    def suggested_connector(self, website_id: str) -> str | None:
        """Return a connector name without connecting or making requests."""
        profile = self.database.get_website_discovery_profile(website_id)
        return "WordPressConnector" if profile and profile["cms"] == "wordpress" else None
