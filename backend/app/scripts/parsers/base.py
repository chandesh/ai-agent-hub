"""Parser contract and factory for ingestion sources."""

from abc import ABC, abstractmethod
from typing import Any


class BaseParser(ABC):
    """Base class for source-specific payload parsers."""

    def __init__(self, config: dict):
        self.config = config
        parser_config = config.get("parser", {})
        self.item_path: str | None = parser_config.get("item_path")
        self.mappings: dict = parser_config.get("mappings", {})
        self.entity: str | None = config.get("entity")

    @abstractmethod
    def fetch_page(self, page_token: str | int | None) -> dict:
        """Fetch one page of raw data."""

    @abstractmethod
    def has_next_page(self, response: dict) -> bool:
        """Whether another page is available."""

    @abstractmethod
    def next_page_token(self, response: dict) -> str | int | None:
        """Token identifying the next page."""

    def parse(self, raw: dict) -> dict[str, Any]:
        """Map one raw item to normalized model fields."""
        from app.scripts.parsers.mapping import evaluate_mappings

        return evaluate_mappings(raw, self.mappings)

    def get_items(self, response: dict) -> list[dict]:
        """Extract the list of raw items from a page response."""
        if not self.item_path:
            return []
        items: Any = response
        for token in self.item_path.split("."):
            if not isinstance(items, dict):
                return []
            items = items.get(token)
        return items if isinstance(items, list) else []

    async def close(self) -> None:
        """Release resources held by the parser."""


class ParserFactory:
    """Registry mapping source ``type`` values to parser classes."""

    _registry: dict[str, type[BaseParser]] = {}

    @classmethod
    def register(cls, type_: str, parser_cls: type[BaseParser]) -> None:
        cls._registry[type_] = parser_cls

    @classmethod
    def build(cls, type_: str, config: dict) -> BaseParser:
        if type_ not in cls._registry:
            raise ValueError(f"Unknown parser type: {type_}")
        return cls._registry[type_](config)
