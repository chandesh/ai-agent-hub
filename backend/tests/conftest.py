"""Pytest fixtures shared across the backend test suite."""

import os
import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (import all models so metadata is complete)
from app.core.config import settings
from app.db.database import Base


def _test_database_url() -> str:
    """Test DB URL: explicit env var, else the app DB with a _test suffix."""
    explicit = os.getenv("TEST_DATABASE_URL")
    if explicit:
        return explicit
    return re.sub(r"/[^/]+$", "/ai_agent_hub_test", settings.database_url)


@pytest.fixture(scope="session")
def engine():
    test_engine = create_engine(_test_database_url())
    Base.metadata.create_all(bind=test_engine)
    yield test_engine
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture
def db_session(engine):
    """Session bound to a transaction that is rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint"
    )()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
