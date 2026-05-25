from __future__ import annotations

from okx_paper_bot.config import AppSettings
from okx_paper_bot.persistence.db import create_database


def make_settings(tmp_path):
    return AppSettings(database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}")


def make_database(tmp_path):
    database = create_database(make_settings(tmp_path))
    database.init_schema()
    return database
