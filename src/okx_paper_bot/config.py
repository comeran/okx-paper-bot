"""Application settings with secret-safe public views."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv


DEFAULT_DATABASE_URL = "sqlite:///data/okx_quant.sqlite3"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def mask_url_secret(database_url: str) -> str:
    """Return a database URL safe for logs and API responses."""
    try:
        parts = urlsplit(database_url)
    except ValueError:
        return "<invalid database url>"
    if not parts.password:
        return database_url
    username = parts.username or ""
    hostname = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{username}:***@{hostname}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def resolve_database_url(database_url: str) -> str:
    if not database_url.startswith("sqlite:///"):
        return database_url
    path = database_url.replace("sqlite:///", "", 1)
    if not path or path == ":memory:" or path.startswith("file:"):
        return database_url
    db_path = Path(path)
    if not db_path.is_absolute():
        db_path = (PROJECT_ROOT / db_path).resolve()
    return f"sqlite:///{db_path}"


@dataclass(frozen=True)
class AppSettings:
    database_url: str = DEFAULT_DATABASE_URL
    data_dir: Path = Path("data")
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8080
    okx_api_key: str | None = None
    okx_api_secret: str | None = None
    okx_api_password: str | None = None
    allow_live_trading: bool = False
    live_confirm_phrase: str = "ENABLE_LIVE_TRADING"
    default_fee_rate: float = 0.001
    default_slippage_rate: float = 0.0005

    def __post_init__(self) -> None:
        object.__setattr__(self, "database_url", resolve_database_url(self.database_url))

    @classmethod
    def from_env(cls) -> "AppSettings":
        load_dotenv()
        return cls(
            database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            dashboard_host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
            dashboard_port=int(os.getenv("DASHBOARD_PORT", "8080")),
            # Credentials are loaded from database only, not from .env
            allow_live_trading=parse_bool(os.getenv("ALLOW_LIVE_TRADING"), default=False),
            live_confirm_phrase=os.getenv("LIVE_CONFIRM_PHRASE", "ENABLE_LIVE_TRADING"),
            default_fee_rate=float(os.getenv("FEE_RATE", "0.001")),
            default_slippage_rate=float(os.getenv("SLIPPAGE_RATE", "0.0005")),
        )

    @property
    def is_mysql(self) -> bool:
        return self.database_url.startswith(("mysql://", "mysql+pymysql://"))

    @property
    def public_database_url(self) -> str:
        return mask_url_secret(self.database_url)

    def public_dict(self) -> dict:
        return {
            "database_url": self.public_database_url,
            "database_kind": "mysql" if self.is_mysql else "sqlite",
            "dashboard_host": self.dashboard_host,
            "dashboard_port": self.dashboard_port,
            "okx_credentials_configured": all(
                [self.okx_api_key, self.okx_api_secret, self.okx_api_password]
            ),
            "allow_live_trading": self.allow_live_trading,
            "live_confirm_phrase_configured": bool(self.live_confirm_phrase),
            "default_fee_rate": self.default_fee_rate,
            "default_slippage_rate": self.default_slippage_rate,
        }
