"""Copy existing SQLite reviews/history to PostgreSQL without replacing conflicts."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from streamlit.errors import StreamlitSecretNotFoundError

from review_store import (
    ReviewMigrationError,
    ReviewStoreError,
    migrate_sqlite_to_postgres,
)


def _configured_database_url() -> str | None:
    environment_url = os.environ.get("AUDIT_REVIEW_DATABASE_URL", "").strip()
    if environment_url:
        return environment_url
    try:
        import streamlit as st
        return st.secrets["AUDIT_REVIEW_DATABASE_URL"]
    except (KeyError, StreamlitSecretNotFoundError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        default=str(Path(__file__).parent / "data" / "review_records.sqlite3"),
        help="Path to the existing SQLite review database (default: data/review_records.sqlite3).",
    )
    args = parser.parse_args()
    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.is_file():
        print(f"No SQLite review database found at: {sqlite_path}")
        print("No records were migrated. The repository currently has no local review database to copy.")
        return 0

    database_url = _configured_database_url()
    if not database_url:
        print("No PostgreSQL connection is configured. Add AUDIT_REVIEW_DATABASE_URL to local Streamlit secrets or the environment.")
        return 2
    try:
        result = migrate_sqlite_to_postgres(sqlite_path, database_url)
    except (ReviewMigrationError, ReviewStoreError) as error:
        print(f"Migration stopped: {error}")
        return 1

    print("Migration completed and every source record/history row was verified before commit.")
    print(f"Current review records inserted: {result['records_inserted']} of {result['records_in_source']}")
    print(f"History rows inserted: {result['history_rows_inserted']} of {result['history_rows_in_source']}")
    print(f"Verified: {result['records_verified']} review records and {result['history_rows_verified']} history rows.")
    print("The SQLite source file was retained and not deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
