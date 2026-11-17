import pytest


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCUMENT_QA_DB_PATH", str(tmp_path / "qa.sqlite3"))
