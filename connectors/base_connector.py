"""Abstract interface for read-only website connectors."""

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """Common public-data connector contract."""

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def test_connection(self) -> bool: ...

    @abstractmethod
    def get_site_information(self) -> dict[str, Any]: ...

    @abstractmethod
    def get_posts(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_pages(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_categories(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_tags(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_media(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def disconnect(self) -> None: ...
