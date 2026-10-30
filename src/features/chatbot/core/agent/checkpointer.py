from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.shared.database.config import PROJECT_ROOT, get_database_settings


_checkpoint_resource: sqlite3.Connection | ConnectionPool | None = None
_checkpointer: SqliteSaver | PostgresSaver | None = None
_checkpointer_initialized = False


def _postgres_conninfo() -> str:
    settings = get_database_settings()
    parameters: dict[str, Any] = {
        "sslmode": settings.sslmode,
        "connect_timeout": settings.connect_timeout_seconds,
        "application_name": f"{settings.application_name}-langgraph",
        "options": f"-c search_path={settings.schema}",
    }
    if settings.sslrootcert:
        parameters["sslrootcert"] = settings.sslrootcert
    if settings.connection_url:
        connection_url = settings.connection_url
        if connection_url.startswith("postgres://"):
            connection_url = "postgresql://" + connection_url.removeprefix("postgres://")
        return make_conninfo(connection_url, **parameters)
    return make_conninfo(
        host=settings.host,
        port=settings.port,
        dbname=settings.database,
        user=settings.username,
        password=settings.password,
        **parameters,
    )


def create_graph_checkpointer() -> SqliteSaver | PostgresSaver:
    """Create the durable checkpointer used by chatbot HITL runs."""
    global _checkpoint_resource, _checkpointer, _checkpointer_initialized

    settings = get_database_settings()
    if settings.mode == "postgresql":
        pool = ConnectionPool(
            conninfo=_postgres_conninfo(),
            min_size=1,
            max_size=10,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        checkpointer = PostgresSaver(pool)
        _checkpoint_resource = pool
        _checkpointer = checkpointer
        return checkpointer

    configured_path = os.getenv("LANGGRAPH_CHECKPOINT_SQLITE_PATH", "").strip()
    checkpoint_path = (
        Path(configured_path).expanduser()
        if configured_path
        else PROJECT_ROOT / "storage" / "langgraph_checkpoints.sqlite3"
    )
    if not checkpoint_path.is_absolute():
        checkpoint_path = PROJECT_ROOT / checkpoint_path
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(checkpoint_path.resolve()), check_same_thread=False)
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    _checkpoint_resource = connection
    _checkpointer = checkpointer
    _checkpointer_initialized = True
    return checkpointer


def initialize_graph_checkpointer() -> None:
    """Open deferred resources and create checkpoint tables during app startup."""
    global _checkpointer_initialized
    if _checkpointer_initialized:
        return
    if isinstance(_checkpoint_resource, ConnectionPool):
        _checkpoint_resource.open(wait=True)
    if _checkpointer is None:
        raise RuntimeError("Graph checkpointer has not been created.")
    _checkpointer.setup()
    _checkpointer_initialized = True


def close_graph_checkpointer() -> None:
    global _checkpoint_resource, _checkpointer_initialized
    if _checkpoint_resource is not None:
        _checkpoint_resource.close()
        _checkpoint_resource = None
    _checkpointer_initialized = False
