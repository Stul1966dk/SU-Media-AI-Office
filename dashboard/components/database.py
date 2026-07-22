"""Shared local database factory for Streamlit pages."""

import os
from pathlib import Path

from core.database import Database


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def open_database(*, read_only: bool = False) -> Database:
    """Open and initialize the configured local AI Office database."""
    default_path = PROJECT_ROOT / "data" / "affiliate_manager.db"
    path = Path(os.getenv("SU_MEDIA_DATABASE_PATH", default_path))
    database = Database(path)
    if read_only:
        database.initialize_read_only()
    else:
        database.initialize()
    return database
