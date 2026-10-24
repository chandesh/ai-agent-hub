"""Models for configurable ingestion sources and their run history."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base


class Source(Base):
    """A configured data source for the ingestion pipeline."""

    __tablename__ = "sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(64), unique=True, nullable=False)
    display_name = Column(String(128), nullable=False)
    type = Column(String(32), nullable=False)
    config = Column(JSONB, nullable=False)
    status = Column(String(16), default="active", nullable=False)
    last_fetched_at = Column(DateTime(timezone=True))
    last_fetched_count = Column(Integer, default=0)
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    runs = relationship("IngestionRun", back_populates="source")

    def __repr__(self):
        return f"<Source {self.name}>"


class IngestionRun(Base):
    """Audit record for one execution of an ingestion source."""

    __tablename__ = "ingestion_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(
        UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False, index=True
    )
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    items_seen = Column(Integer, default=0)
    items_created = Column(Integer, default=0)
    items_updated = Column(Integer, default=0)
    items_failed = Column(Integer, default=0)
    error_summary = Column(Text)

    source = relationship("Source", back_populates="runs")

    def __repr__(self):
        return f"<IngestionRun source_id={self.source_id}>"
