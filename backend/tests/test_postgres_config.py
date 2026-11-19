from unittest.mock import MagicMock

import pytest

from app import db
from conftest import validate_test_target


def test_database_url_requires_postgresql(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        db.database_url()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        db.database_url()


def test_database_uses_supabase_session_pooler_url_without_exposing_it(monkeypatch):
    url = "postgresql://user:password@aws-0-region.pooler.supabase.com:5432/postgres?sslmode=require"
    monkeypatch.setenv("DATABASE_URL", url)
    connection = MagicMock()
    connection.__enter__.return_value = connection
    monkeypatch.setattr(db.psycopg, "connect", MagicMock(return_value=connection))
    with db.database() as opened:
        assert opened is connection
    db.psycopg.connect.assert_called_once_with(url, connect_timeout=10, row_factory=db.dict_row)


def test_test_fixture_accepts_only_a_distinct_supabase_project():
    production = "postgresql://postgres.production:secret@aws-0-region.pooler.supabase.com:5432/postgres"
    isolated = "postgresql://postgres.testing:secret@aws-0-region.pooler.supabase.com:5432/postgres"
    validate_test_target(isolated, production)
    with pytest.raises(pytest.UsageError, match="Unsafe TEST_DATABASE_URL"):
        validate_test_target(production, production)
    with pytest.raises(pytest.UsageError, match="Unsafe TEST_DATABASE_URL"):
        validate_test_target("postgresql://other.production:secret@aws-0-region.pooler.supabase.com:5432/postgres", production)


def test_test_fixture_accepts_a_named_local_test_database_only():
    production = "postgresql://postgres.production:secret@aws-0-region.pooler.supabase.com:5432/postgres"
    validate_test_target("postgresql://tester:secret@localhost:5432/docwise_test", production)
    with pytest.raises(pytest.UsageError, match="Unsafe TEST_DATABASE_URL"):
        validate_test_target("postgresql://tester:secret@localhost:5432/postgres", production)


def test_schema_initializer_secures_every_docwise_table_and_sequence():
    connection = MagicMock()
    db._secure_schema(connection)
    statements = [call.args[0].as_string() if hasattr(call.args[0], "as_string") else call.args[0]
                  for call in connection.execute.call_args_list]
    for name in db.DOCWISE_TABLES:
        assert f'ALTER TABLE "public"."{name}" ENABLE ROW LEVEL SECURITY' in statements
        assert f'REVOKE ALL PRIVILEGES ON TABLE "public"."{name}" FROM anon, authenticated' in statements
    for name in db.DOCWISE_SEQUENCES:
        assert f'REVOKE ALL PRIVILEGES ON SEQUENCE "public"."{name}" FROM anon, authenticated' in statements
    assert any("REVOKE ALL ON TABLES FROM anon, authenticated" in statement for statement in statements)
    assert any("REVOKE ALL ON SEQUENCES FROM anon, authenticated" in statement for statement in statements)
