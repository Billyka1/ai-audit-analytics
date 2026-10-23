import pytest

from review_store import (
    ReviewMigrationError,
    ReviewStoreError,
    default_database_path,
    initialize_review_store,
    migrate_sqlite_to_postgres,
    validate_postgres_url,
)


def test_sqlite_is_the_default_and_local_path_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.delenv("AUDIT_REVIEW_DATABASE_URL", raising=False)
    monkeypatch.delenv("AUDIT_REVIEW_DB", raising=False)
    assert default_database_path().name == "review_records.sqlite3"

    custom_path = tmp_path / "local-reviews.sqlite3"
    monkeypatch.setenv("AUDIT_REVIEW_DB", str(custom_path))
    assert default_database_path() == custom_path


def test_postgres_environment_url_takes_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_REVIEW_DB", str(tmp_path / "local.sqlite3"))
    url = "postgresql://demo:secret@db.example.test/reviews?sslmode=require"
    monkeypatch.setenv("AUDIT_REVIEW_DATABASE_URL", url)
    assert default_database_path() == url


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_postgres_url_accepts_tls(scheme):
    url = f"{scheme}://demo:secret@db.example.test/reviews?sslmode=require"
    assert validate_postgres_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://demo:secret@db.example.test/reviews",
        "postgresql://demo:secret@db.example.test/reviews?sslmode=disable",
        "postgresql://demo:secret@db.example.test",
        "not-a-database-url",
    ],
)
def test_invalid_postgres_url_is_rejected_without_echoing_secrets(url):
    with pytest.raises(ReviewStoreError) as error:
        validate_postgres_url(url)
    assert "secret" not in str(error.value)


def test_storage_connection_errors_are_sanitized(tmp_path):
    # A directory cannot be opened as a SQLite database file.
    with pytest.raises(ReviewStoreError, match="Review storage operation failed") as error:
        initialize_review_store(tmp_path)
    assert "Traceback" not in str(error.value)


def test_postgres_initialization_rejects_missing_tls_before_connecting():
    with pytest.raises(ReviewStoreError, match="must enable TLS") as error:
        initialize_review_store("postgresql://demo:secret@db.example.test/reviews")
    assert "secret" not in str(error.value)


def test_migration_refuses_missing_sqlite_database_without_creating_it(tmp_path):
    database = tmp_path / "no-reviews.sqlite3"
    with pytest.raises(ReviewMigrationError, match="No SQLite review database"):
        migrate_sqlite_to_postgres(
            database,
            "postgresql://demo:secret@db.example.test/reviews?sslmode=require",
        )
    assert not database.exists()


def test_migration_requires_postgres_destination(tmp_path):
    database = tmp_path / "reviews.sqlite3"
    database.touch()
    with pytest.raises(ReviewMigrationError, match="destination must be a PostgreSQL URL"):
        migrate_sqlite_to_postgres(database, str(database))

