"""Database engine and session helpers."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from okx_paper_bot.config import AppSettings
from okx_paper_bot.persistence.models import Base, StrategyTemplate
from okx_paper_bot.strategies import strategy_templates


class Database:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.engine = _create_engine(settings)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False, future=True)

    def init_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        self.apply_lightweight_migrations()
        self.seed_strategy_templates()

    def apply_lightweight_migrations(self) -> None:
        inspector = inspect(self.engine)
        table_names = set(inspector.get_table_names())
        with self.engine.begin() as conn:
            if "strategy_instances" in table_names:
                columns = {column["name"] for column in inspector.get_columns("strategy_instances")}
                if "account_id" not in columns:
                    conn.execute(text("ALTER TABLE strategy_instances ADD COLUMN account_id INTEGER"))
            if "trades" in table_names:
                columns = {column["name"] for column in inspector.get_columns("trades")}
                if "account_id" not in columns:
                    conn.execute(text("ALTER TABLE trades ADD COLUMN account_id INTEGER"))
                if "external_order_id" not in columns:
                    conn.execute(text("ALTER TABLE trades ADD COLUMN external_order_id VARCHAR(120)"))
        self.backfill_account_links()

    def backfill_account_links(self) -> None:
        with self.engine.begin() as conn:
            demo_id = conn.execute(
                text("SELECT id FROM account_configs WHERE account_type = 'okx_demo' AND is_active = 1 ORDER BY id LIMIT 1")
            ).scalar()
            live_id = conn.execute(
                text("SELECT id FROM account_configs WHERE account_type = 'okx_live' AND is_active = 1 ORDER BY id LIMIT 1")
            ).scalar()
            if demo_id is not None:
                conn.execute(
                    text(
                        "UPDATE strategy_instances SET account_id = :account_id "
                        "WHERE account_id IS NULL AND broker_mode IN ('okx_demo', 'paper')"
                    ),
                    {"account_id": demo_id},
                )
                conn.execute(
                    text(
                        "UPDATE trades SET account_id = :account_id "
                        "WHERE account_id IS NULL AND broker_mode IN ('okx_demo', 'paper')"
                    ),
                    {"account_id": demo_id},
                )
            if live_id is not None:
                conn.execute(
                    text(
                        "UPDATE strategy_instances SET account_id = :account_id "
                        "WHERE account_id IS NULL AND broker_mode = 'okx_live'"
                    ),
                    {"account_id": live_id},
                )
                conn.execute(
                    text(
                        "UPDATE trades SET account_id = :account_id "
                        "WHERE account_id IS NULL AND broker_mode = 'okx_live'"
                    ),
                    {"account_id": live_id},
                )

    def seed_strategy_templates(self) -> None:
        with self.session() as session:
            existing = set(session.scalars(select(StrategyTemplate.key)).all())
            for template in strategy_templates():
                if template["key"] in existing:
                    continue
                session.add(
                    StrategyTemplate(
                        key=template["key"],
                        name=template["name"],
                        description=template["description"],
                        param_schema=template["param_schema"],
                    )
                )

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _create_engine(settings: AppSettings) -> Engine:
    url = settings.database_url
    kwargs = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "", 1)
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def create_database(settings: AppSettings | None = None) -> Database:
    return Database(settings or AppSettings.from_env())
