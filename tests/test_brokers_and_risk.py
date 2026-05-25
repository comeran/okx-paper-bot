import json

import pytest

from okx_paper_bot.brokers import OKXGateway, PaperAccount, build_okx_order_params, okx_headers_for_mode
from okx_paper_bot.config import AppSettings
from okx_paper_bot.risk import LiveSafetyGate, LiveTradeRequest, size_by_quote


def test_okx_demo_header_is_attached_only_for_demo():
    assert okx_headers_for_mode("okx_demo") == {"x-simulated-trading": "1"}
    assert okx_headers_for_mode("okx_live") == {}


def test_okx_order_params_use_market_td_mode_defaults():
    spot = build_okx_order_params(market_type="spot", inst_id="BTC-USDT", side="buy", amount=1)
    swap = build_okx_order_params(market_type="swap", inst_id="BTC-USDT-SWAP", side="buy", amount=1)

    assert spot["tdMode"] == "cash"
    assert swap["tdMode"] == "cross"


def test_live_gate_requires_all_hard_gates():
    settings = AppSettings(allow_live_trading=True, live_confirm_phrase="ARM")

    result = LiveSafetyGate(settings).validate(
        LiveTradeRequest(broker_mode="okx_live", instance_allow_live=True, confirmation="ARM")
    )
    blocked = LiveSafetyGate(settings).validate(
        LiveTradeRequest(broker_mode="okx_live", instance_allow_live=False, confirmation="ARM")
    )

    assert result.allowed is True
    assert blocked.allowed is False


class _FakeOKX:
    def __init__(self, params):
        self.params = params
        self.orders = []

    def fetch_ohlcv(self, symbol, timeframe, limit, since=None):
        return [[1700000000000, 1, 2, 0.5, 1.5, 10]][-limit:]

    def create_order(self, symbol, order_type, side, amount, price, params):
        order = {
            "symbol": symbol,
            "type": order_type,
            "side": side,
            "amount": amount,
            "price": price,
            "params": params,
        }
        self.orders.append(order)
        return order


class _FakeCCXT:
    last_client = None

    @classmethod
    def okx(cls, params):
        cls.last_client = _FakeOKX(params)
        return cls.last_client


def test_okx_gateway_fetches_candles_without_credentials():
    gateway = OKXGateway(AppSettings(okx_api_key="k", okx_api_secret="s", okx_api_password="p"), "okx_demo", "spot")

    candles = gateway.fetch_candles(symbol="BTC/USDT", timeframe="1m", ccxt_module=_FakeCCXT)

    assert candles[0].close == 1.5
    assert "apiKey" not in _FakeCCXT.last_client.params
    assert _FakeCCXT.last_client.params["headers"] == {"x-simulated-trading": "1"}
    assert _FakeCCXT.last_client.params["sandbox"] is True


def test_okx_live_place_order_requires_hard_gate():
    gateway = OKXGateway(AppSettings(allow_live_trading=False), "okx_live", "spot")

    try:
        gateway.place_order(symbol="BTC/USDT", side="buy", amount=1, ccxt_module=_FakeCCXT)
    except PermissionError as exc:
        assert "ALLOW_LIVE_TRADING" in str(exc)
    else:
        raise AssertionError("expected live gate to block order")


def test_okx_demo_place_order_uses_td_mode():
    gateway = OKXGateway(AppSettings(), "okx_demo", "swap")

    order = gateway.place_order(symbol="BTC/USDT:USDT", side="buy", amount=1, ccxt_module=_FakeCCXT)

    assert order["params"]["tdMode"] == "cross"
    assert _FakeCCXT.last_client.params["headers"] == {"x-simulated-trading": "1"}
    assert _FakeCCXT.last_client.params["sandbox"] is True


def test_okx_gateway_adjust_demo_balance_uses_official_endpoint(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": "0", "data": [], "msg": ""}

    def fake_request(method, url, headers, data, timeout):
        captured.update({"method": method, "url": url, "headers": headers, "data": data, "timeout": timeout})
        return Response()

    monkeypatch.setattr("okx_paper_bot.brokers.requests.request", fake_request)
    gateway = OKXGateway(
        AppSettings(okx_api_key="key", okx_api_secret="secret", okx_api_password="passphrase"),
        "okx_demo",
        "spot",
    )

    result = gateway.adjust_demo_balance(adjustment_type="increase", adjustments=[{"ccy": "USDT", "amt": "5000"}])

    assert result["code"] == "0"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://www.okx.com/api/v5/account/demo-adjust-balance"
    assert captured["headers"]["x-simulated-trading"] == "1"
    assert json.loads(captured["data"]) == {"type": "increase", "adjustments": [{"ccy": "USDT", "amt": "5000"}]}


class TestPaperAccount:
    def test_buy_basic(self):
        account = PaperAccount(cash=10000.0, fee_rate=0.001, slippage_rate=0.0)
        fill = account.buy(price=100.0, quote_amount=1000.0, order_type="market")
        assert fill is not None
        assert fill.side == "buy"
        assert fill.amount == pytest.approx(10.0)
        assert fill.price == 100.0
        assert fill.fee == pytest.approx(10.0 * 100.0 * 0.001)
        assert account.position_size == pytest.approx(10.0)
        assert account.avg_entry_price == pytest.approx(100.0)
        assert account.cash < 10000.0

    def test_buy_applies_slippage(self):
        account = PaperAccount(cash=10000.0, fee_rate=0.0, slippage_rate=0.01)
        fill = account.buy(price=100.0, quote_amount=1000.0)
        assert fill is not None
        assert fill.price == pytest.approx(101.0)

    def test_buy_insufficient_cash_returns_none(self):
        account = PaperAccount(cash=0.0)
        assert account.buy(price=100.0, quote_amount=1000.0) is None

    def test_buy_cash_ceiling_recalculates_amount(self):
        account = PaperAccount(cash=50.0, fee_rate=0.001, slippage_rate=0.0)
        fill = account.buy(price=100.0, quote_amount=10000.0)
        assert fill is not None
        assert fill.fee > 0
        assert account.cash >= -1e-9

    def test_sell_basic(self):
        account = PaperAccount(cash=5000.0, fee_rate=0.001, slippage_rate=0.0)
        account.buy(price=100.0, quote_amount=5000.0)
        cash_after_buy = account.cash
        fill = account.sell(price=110.0, amount=account.position_size)
        assert fill is not None
        assert fill.side == "sell"
        assert fill.pnl > 0
        assert account.cash > cash_after_buy

    def test_sell_no_position_returns_none(self):
        account = PaperAccount(cash=10000.0)
        assert account.sell(price=100.0, amount=1.0) is None

    def test_sell_caps_to_position(self):
        account = PaperAccount(cash=10000.0, fee_rate=0.0, slippage_rate=0.0)
        account.buy(price=100.0, quote_amount=5000.0)
        pos = account.position_size
        fill = account.sell(price=100.0, amount=pos * 2)
        assert fill is not None
        assert fill.amount == pytest.approx(pos)

    def test_sell_resets_avg_entry_on_full_close(self):
        account = PaperAccount(cash=10000.0, fee_rate=0.0, slippage_rate=0.0)
        account.buy(price=100.0, quote_amount=5000.0)
        account.sell(price=100.0, amount=account.position_size)
        assert account.position_size == pytest.approx(0.0, abs=1e-12)
        assert account.avg_entry_price == 0.0

    def test_equity(self):
        account = PaperAccount(cash=5000.0, fee_rate=0.0, slippage_rate=0.0)
        account.buy(price=100.0, quote_amount=5000.0)
        equity = account.equity(price=110.0)
        assert equity == pytest.approx(account.cash + account.position_size * 110.0)

    def test_round_trip_pnl(self):
        account = PaperAccount(cash=10000.0, fee_rate=0.0, slippage_rate=0.0)
        account.buy(price=100.0, quote_amount=5000.0)
        fill = account.sell(price=120.0, amount=account.position_size)
        assert fill.pnl == pytest.approx(1000.0)
        assert account.cash == pytest.approx(11000.0)


def test_size_by_quote_edge_cases():
    assert size_by_quote(0, 100.0, 1000.0) == 0.0
    assert size_by_quote(10000.0, 0, 1000.0) == 0.0
    assert size_by_quote(10000.0, 100.0, 0) == 0.0
