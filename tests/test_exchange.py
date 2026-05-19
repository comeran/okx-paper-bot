from __future__ import annotations

from okx_paper_bot.config import BotConfig
from okx_paper_bot.exchange import create_okx_exchange, create_okx_market_data_exchange


class _FakeOKX:
    def __init__(self, params):
        self.params = params
        self.headers = params.get("headers", {})


class _FakeCCXT:
    calls = []

    @classmethod
    def okx(cls, params):
        cls.calls.append(params)
        return _FakeOKX(params)


def test_market_data_exchange_does_not_attach_private_credentials():
    _FakeCCXT.calls = []
    config = BotConfig(api_key="key", secret="secret", password="pass", okx_demo=True)

    exchange = create_okx_market_data_exchange(config, ccxt_module=_FakeCCXT)

    params = _FakeCCXT.calls[-1]
    assert "apiKey" not in params
    assert "secret" not in params
    assert "password" not in params
    assert exchange.headers["x-simulated-trading"] == "1"


def test_authenticated_exchange_attaches_private_credentials():
    _FakeCCXT.calls = []
    config = BotConfig(api_key="key", secret="secret", password="pass", okx_demo=False)

    create_okx_exchange(config, ccxt_module=_FakeCCXT, auth=True)

    params = _FakeCCXT.calls[-1]
    assert params["apiKey"] == "key"
    assert params["secret"] == "secret"
    assert params["password"] == "pass"
