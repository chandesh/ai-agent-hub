"""Ingestion parsers.

Concrete parsers register themselves with :class:`ParserFactory`; importing
this package makes all supported source types available.
"""

from app.scripts.parsers.base import BaseParser, ParserFactory
from app.scripts.parsers.api import APIParser

ParserFactory.register("api", APIParser)

__all__ = ["BaseParser", "ParserFactory", "APIParser"]
