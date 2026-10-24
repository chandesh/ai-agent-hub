"""Tests for the curated catalog parser."""

from app.scripts.parsers.base import ParserFactory
from app.scripts.parsers.curated import CuratedParser

CONFIG = {
    "entity": "agent",
    "parser": {
        "item_path": "CATALOG",
        "module": "app.scripts.agent_catalog",
        "mappings": {
            "name": "name",
            "slug": "slug",
            "description": "description",
            "short_description": "short_description",
            "website_url": "website_url",
            "logo_url": "logo_url",
            "category": "category",
            "pricing_model": "pricing_model",
            "featured": "featured",
            "tags": "tags",
        },
    },
}


def test_curated_parser_iterates_catalog():
    parser = CuratedParser(CONFIG)

    items = list(parser.iter_items(enrich_only=False))

    assert len(items) > 0
    assert all("external_id" in item for item in items)
    assert items[0]["external_id"] == items[0]["slug"]


def test_curated_enrich_only_empty():
    parser = CuratedParser(CONFIG)

    items = list(parser.iter_items(enrich_only=True))

    assert items == []


def test_curated_parser_registered():
    assert isinstance(ParserFactory.build("curated", CONFIG), CuratedParser)
