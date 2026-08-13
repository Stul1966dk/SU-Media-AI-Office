"""Re-authenticate Search Console from a terminal (reliable OAuth login).

Running the OAuth login through a Streamlit button is fragile — the local
callback server runs inside Streamlit's thread and often does not complete.
This script runs the same login in a plain process instead: it opens a
browser for the Google login, writes a fresh token.json, and clears the
"login udløbet"-advarsel on the daily-work page.

Run it from anywhere:

    python scripts/reconnect_search_console.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.database import Database
from integrations.search_console import SearchConsoleAuthenticationError
from integrations.search_console_integration import SearchConsoleIntegration


def open_database() -> Database:
    database = Database(PROJECT_ROOT / "data" / "affiliate_manager.db")
    database.initialize()
    return database


def _default_integration(database: Any) -> SearchConsoleIntegration:
    return SearchConsoleIntegration(PROJECT_ROOT, database)


def run(
    database: Any,
    *,
    integration_factory: Callable[[Any], Any] = _default_integration,
) -> int:
    """Run the interactive OAuth login once. Returns a process exit code."""
    try:
        print("Åbner browseren til Google-login for Search Console …")
        state = integration_factory(database).connect()
    except SearchConsoleAuthenticationError as error:
        print(f"Login mislykkedes: {error}")
        return 1
    except Exception as error:  # vis en brugbar besked frem for et stack trace
        print(f"Login mislykkedes ({type(error).__name__}): {error}")
        return 1
    print(f"OK — forbundet som {state.get('account') or 'ukendt konto'}.")
    print("Advarslen på 'I dag' er ryddet. Kør evt. den daglige opdatering nu.")
    return 0


def main() -> int:
    database = open_database()
    try:
        return run(database)
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
