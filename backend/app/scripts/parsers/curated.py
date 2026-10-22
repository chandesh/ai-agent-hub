"""Parser for the static curated agent catalog."""

import importlib
import logging
from datetime import datetime, timezone

from app.scripts.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class CuratedParser(BaseParser):
    """Iterates a Python catalog list as a source of agents."""

    def __init__(self, config: dict):
        super().__init__(config)
        parser_config = config.get("parser", {})
        module = importlib.import_module(parser_config["module"])
        self.catalog = getattr(module, parser_config["item_path"])

    def iter_items(self, enrich_only: bool = False):
        if enrich_only:
            logger.info(
                "enrich_only skipped for curated source "
                "(no external existence check)"
            )
            return
        for item in self.catalog:
            parsed = self.parse(item)
            parsed["external_id"] = item.get("slug") or parsed.get("slug")
            parsed["last_synced_at"] = datetime.now(timezone.utc)
            yield parsed

    def fetch_page(self, page_token):
        raise NotImplementedError("Curated sources are not paginated")

    def has_next_page(self, response):
        return False

    def next_page_token(self, response):
        return None
