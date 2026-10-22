"""Ingestion parsers.

Concrete parsers register themselves with :class:`ParserFactory`; importing
this package makes all supported source types available.
"""

from app.scripts.parsers.base import BaseParser, ParserFactory

__all__ = ["BaseParser", "ParserFactory"]
