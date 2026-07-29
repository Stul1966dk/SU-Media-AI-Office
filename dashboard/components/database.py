"""Shared local database factory for Streamlit pages."""

import importlib
import os
from threading import Lock
from pathlib import Path

import core.database as database_module


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATABASE_RELOAD_LOCK = Lock()


def open_database(*, read_only: bool = False) -> database_module.Database:
    """Open and initialize the configured local AI Office database."""
    # Streamlit can retain the old class after core/database.py changes.
    # Reload before creating an instance so newly added database APIs exist.
    with _DATABASE_RELOAD_LOCK:
        current_database = importlib.reload(database_module)
    default_path = PROJECT_ROOT / "data" / "affiliate_manager.db"
    path = Path(os.getenv("SU_MEDIA_DATABASE_PATH", default_path))
    database = current_database.Database(path)
    if read_only:
        database.initialize_read_only()
    else:
        database.initialize()
    return database
