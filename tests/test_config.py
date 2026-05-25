from pathlib import Path

from okx_paper_bot.config import AppSettings, mask_url_secret


def test_database_url_masks_password():
    raw = "mysql+pymysql://user:test-password@db.example.test:3306/app"

    assert mask_url_secret(raw) == "mysql+pymysql://user:***@db.example.test:3306/app"


def test_relative_sqlite_url_is_resolved_from_project_root():
    settings = AppSettings(database_url="sqlite:///data/test.sqlite3")

    expected = Path(__file__).resolve().parents[1] / "data" / "test.sqlite3"
    assert settings.database_url == f"sqlite:///{expected}"


def test_public_settings_do_not_include_okx_secrets():
    settings = AppSettings(
        database_url="sqlite:///data/test.sqlite3",
        okx_api_key="key",
        okx_api_secret="secret",
        okx_api_password="password",
    )

    public = settings.public_dict()

    assert public["okx_credentials_configured"] is True
    assert set(public) == {
        "database_url",
        "database_kind",
        "dashboard_host",
        "dashboard_port",
        "okx_credentials_configured",
        "allow_live_trading",
        "live_confirm_phrase_configured",
        "default_fee_rate",
        "default_slippage_rate",
    }
    assert "secret" not in str(public)
    assert "password" not in str(public)


def test_public_dict_does_not_expose_confirm_phrase():
    settings = AppSettings(live_confirm_phrase="MY_SECRET_PHRASE")

    public = settings.public_dict()

    assert "MY_SECRET_PHRASE" not in str(public)
