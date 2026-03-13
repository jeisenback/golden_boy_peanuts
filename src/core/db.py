"""
Shared database utilities for the Energy Options Opportunity Agent.

All agents obtain their SQLAlchemy Engine via `get_engine()` defined here.
This module is the single source of truth for database connection configuration
(DATABASE_URL, pool settings, connection validation). Any future changes to
connection pooling, SSL mode, or timeout parameters are made once here.

Usage:
    from src.core.db import get_engine
    engine = get_engine()
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def get_engine() -> Engine:
    """
    Create a SQLAlchemy engine from the DATABASE_URL environment variable.

    Reads DATABASE_URL from the environment and returns a configured Engine
    with pool_pre_ping enabled to detect and recover from stale connections.
    PostgreSQL is the only supported backend in production; SQLite may be used
    in tests via DATABASE_URL override.

    Returns:
        Engine: SQLAlchemy Engine connected to the configured database.

    Raises:
        RuntimeError: If DATABASE_URL is not set in the environment.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    return create_engine(database_url, pool_pre_ping=True)
