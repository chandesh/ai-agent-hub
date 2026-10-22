"""Backfill tracking columns on rows created before the ingestion pipeline.

Existing rows receive ``source='legacy'``, ``external_id`` from their slug and
``last_synced_at`` from ``created_at`` so the first re-ingestion can match them.

Usage (inside the backend container):
    python -m app.scripts.backfill_existing
"""

import logging

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models import Agent, MCPServer

logger = logging.getLogger(__name__)


def backfill_existing(db: Session | None = None) -> None:
    owns_session = db is None
    db = db or SessionLocal()
    try:
        agents = db.query(Agent).filter(Agent.source.is_(None)).all()
        for agent in agents:
            agent.source = "legacy"
            agent.last_synced_at = agent.created_at
            agent.external_id = agent.slug

        servers = db.query(MCPServer).filter(MCPServer.source.is_(None)).all()
        for server in servers:
            server.source = "legacy"
            server.last_synced_at = server.created_at
            server.external_id = server.slug

        db.commit()
        if agents or servers:
            logger.info(
                "Backfilled %d agents and %d MCP servers", len(agents), len(servers)
            )
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    backfill_existing()
