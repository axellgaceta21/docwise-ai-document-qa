"""Database integration tests require a separate disposable PostgreSQL database."""
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from dotenv import dotenv_values, load_dotenv


_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)


_PURE_MODULES = {"test_comparison.py", "test_correction_status.py"}
_PURE_TESTS = {("test_phase3.py", "test_cache_key_changes_with_each_relevant_input")}


def _supabase_project_ref(url: str) -> str | None:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if host.endswith(".pooler.supabase.com") and parsed.port == 5432:
        user = unquote(parsed.username or "")
        return user.rsplit(".", 1)[1] if "." in user else None
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return host.split(".")[1]
    return None


def validate_test_target(test_url: str, production_url: str | None) -> None:
    """Fail closed before schema creation or TRUNCATE can touch production."""
    try:
        test = urlsplit(test_url)
        if test.scheme not in ("postgresql", "postgres") or not test.hostname:
            raise ValueError
        production_ref = _supabase_project_ref(production_url or "")
        test_ref = _supabase_project_ref(test_url)
        if test_ref and production_ref and test_ref != production_ref:
            return
        # A named local test database is also safe when production is not local.
        local = test.hostname in ("localhost", "127.0.0.1", "::1")
        local_db = test.path.lstrip("/").endswith("_test")
        prod = urlsplit(production_url or "")
        if local and local_db and (prod.hostname or "") not in ("localhost", "127.0.0.1", "::1"):
            return
    except (ValueError, TypeError):
        pass
    raise pytest.UsageError(
        "Unsafe TEST_DATABASE_URL: use a different Supabase project via its session pooler "
        "or a separate local database ending in _test. Production database is never a test target."
    )


def _validate_configured_test_target(test_url: str) -> None:
    # Check the loaded process setting and the backend file independently.
    # A shell override must not make the actual production project look safe.
    production_urls = {os.getenv("DATABASE_URL"), dotenv_values(_ENV_FILE).get("DATABASE_URL")}
    for production_url in production_urls:
        if production_url:
            validate_test_target(test_url, production_url)
    if not any(production_urls):
        validate_test_target(test_url, None)


def pytest_collection_modifyitems(items):
    if test_url := os.getenv("TEST_DATABASE_URL"):
        _validate_configured_test_target(test_url)
        return
    for item in items:
        if item.path.name in _PURE_MODULES or (item.path.name, item.name) in _PURE_TESTS:
            continue
        if item.path.name == "test_ai.py" and "endpoint" not in item.name and "missing_key" not in item.name:
            continue
        if item.path.name == "test_postgres_config.py":
            continue
        item.add_marker(pytest.mark.skip(reason="Set TEST_DATABASE_URL to a disposable PostgreSQL database"))


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch, request):
    url = os.getenv("TEST_DATABASE_URL")
    if not url or request.node.get_closest_marker("skip"):
        return
    _validate_configured_test_target(url)
    monkeypatch.setenv("DATABASE_URL", url)
    from app.db import database, init_db

    init_db()
    with database() as connection:
        connection.execute("TRUNCATE TABLE sessions, ai_cache, api_usage RESTART IDENTITY CASCADE")
