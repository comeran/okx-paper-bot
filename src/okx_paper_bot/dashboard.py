"""Web Dashboard - 查看持仓、交易、收益。"""
from __future__ import annotations

import json
import math
import os
from string import Template
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

from okx_paper_bot.config import BotConfig
from okx_paper_bot.store import TradeStore
from okx_paper_bot.paper import PaperAccount
from okx_paper_bot.stats import EquityTracker
from okx_paper_bot.backtest import BacktestResult

BJT = timezone(timedelta(hours=8))

CSS = """
  body{font-family:-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;margin:0;padding:20px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin:12px 0}
  .header{font-size:20px;font-weight:600;color:#58a6ff}
  .metric{display:inline-block;margin:8px 16px 8px 0}
  .metric .label{font-size:12px;color:#8b949e}
  .metric .value{font-size:24px;font-weight:700}
  .green{color:#3fb950}.red{color:#f85149}.yellow{color:#d29922}
  table{width:100%;border-collapse:collapse;margin-top:8px}
  th,td{text-align:left;padding:6px 12px;border-bottom:1px solid #21262d}
  th{color:#8b949e;font-size:12px}
  .pos{color:#3fb950}.neg{color:#f85149}
  .refresh{color:#8b949e;font-size:12px}
"""

HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OKX Paper Bot Dashboard</title>
<style>$css</style>
</head><body>
<div class="card">
  <div class="header">🤖 OKX Paper Bot</div>
  <div class="refresh">自动刷新 30s | $time</div>
</div>
<div class="card">
  <div class="metric"><div class="label">余额</div><div class="value">$balance</div></div>
  <div class="metric"><div class="label">持仓价值</div><div class="value">$pos_value</div></div>
  <div class="metric"><div class="label">账户总值</div><div class="value $total_class">$total</div></div>
  <div class="metric"><div class="label">总收益</div><div class="value $ret_class">$return_pct</div></div>
</div>
<div class="card">
  <div class="header">📦 持仓</div>
  $positions_html
</div>
<div class="card">
  <div class="header">📋 最近交易</div>
  $trades_html
</div>
<script>setTimeout(()=>location.reload(),30000)</script>
</body></html>""")


def _reconstruct_account(config: BotConfig, trades: list[dict]) -> tuple[float, dict[str, float], dict[str, float]]:
    """Reconstruct balance, positions, and prices from trade history.

    Returns:
        (balance, positions, prices) where positions is {symbol: amount} and
        prices is {symbol: last_known_price}.
    """
    balance = config.initial_balance_usdt
    positions: dict[str, float] = {}
    for t in trades:
        if t["side"] == "buy":
            balance -= t["amount"] * t["price"]
            positions[t["symbol"]] = positions.get(t["symbol"], 0) + t["amount"]
        elif t["side"] in ("sell", "stop_loss", "take_profit", "trailing_stop", "partial_tp"):
            balance += t["amount"] * t["price"]
            positions[t["symbol"]] = positions.get(t["symbol"], 0) - t["amount"]
            if positions.get(t["symbol"], 0) <= 1e-12:
                positions.pop(t["symbol"], None)

    # 从交易记录估算价格
    prices: dict[str, float] = {}
    for t in reversed(trades):
        if t["symbol"] not in prices:
            prices[t["symbol"]] = t["price"]

    return balance, positions, prices


def _build_dashboard(config: BotConfig) -> str:
    store = TradeStore(config.db_path)
    trades = store.list_trades()

    balance, positions, prices = _reconstruct_account(config, trades)

    pos_value = sum(amount * prices.get(sym, 0) for sym, amount in positions.items())
    total = balance + pos_value
    ret_pct = (total - config.initial_balance_usdt) / config.initial_balance_usdt * 100

    # 持仓 HTML
    if positions:
        rows = ""
        for sym, amount in positions.items():
            price = prices.get(sym, 0)
            val = amount * price
            rows += f"<tr><td>{sym}</td><td>{amount:.6f}</td><td>{price:.2f}</td><td>{val:.2f}</td></tr>"
        pos_html = f"<table><tr><th>交易对</th><th>数量</th><th>价格</th><th>价值</th></tr>{rows}</table>"
    else:
        pos_html = "<p style='color:#8b949e'>空仓</p>"

    # 交易 HTML
    recent = trades[-20:] if trades else []
    if recent:
        rows = ""
        for t in reversed(recent):
            side_class = "pos" if t["side"] == "buy" else "neg"
            rows += f"<tr><td>{t.get('ts', '')}</td><td class='{side_class}'>{t['side'].upper()}</td><td>{t['symbol']}</td><td>{t['amount']:.6f}</td><td>{t['price']:.2f}</td></tr>"
        trades_html = f"<table><tr><th>时间</th><th>方向</th><th>交易对</th><th>数量</th><th>价格</th></tr>{rows}</table>"
    else:
        trades_html = "<p style='color:#8b949e'>暂无交易记录</p>"

    return HTML_TEMPLATE.safe_substitute(
        css=CSS,
        time=datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S"),
        balance=f"{balance:.2f}", pos_value=f"{pos_value:.2f}", total=f"{total:.2f}",
        return_pct=f"{ret_pct:+.2f}%",
        total_class="green" if total >= config.initial_balance_usdt else "red",
        ret_class="green" if ret_pct >= 0 else "red",
        positions_html=pos_html, trades_html=trades_html,
    )


# ── API helper functions ─────────────────────────────────────────────────


def _build_api_status(config: BotConfig) -> dict:
    """Enhanced /api/status: account overview with positions and equity."""
    store = TradeStore(config.db_path)
    trades = store.list_trades()
    balance, positions, prices = _reconstruct_account(config, trades)

    pos_value = sum(amount * prices.get(sym, 0) for sym, amount in positions.items())
    total = balance + pos_value
    ret_pct = (total - config.initial_balance_usdt) / config.initial_balance_usdt * 100

    pos_list = [
        {"symbol": sym, "amount": amount, "price": prices.get(sym, 0), "value": round(amount * prices.get(sym, 0), 2)}
        for sym, amount in positions.items()
    ]

    return {
        "time": datetime.now(BJT).isoformat(),
        "balance": round(balance, 2),
        "positions_value": round(pos_value, 2),
        "total_equity": round(total, 2),
        "return_pct": round(ret_pct, 2),
        "initial_balance": config.initial_balance_usdt,
        "strategy": config.strategy_name,
        "positions": pos_list,
        "trades_count": len(trades),
    }


def _build_api_trades(
    config: BotConfig,
    symbol: str | None = None,
    side: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Paginated and filtered trades listing."""
    store = TradeStore(config.db_path)
    all_trades = store.list_trades()

    # Filter
    filtered = all_trades
    if symbol:
        filtered = [t for t in filtered if t["symbol"] == symbol]
    if side:
        filtered = [t for t in filtered if t["side"] == side]

    total = len(filtered)
    total_pages = math.ceil(total / per_page) if total > 0 else 0
    page = max(1, min(page, max(total_pages, 1)))

    start = (page - 1) * per_page
    end = start + per_page
    page_trades = filtered[start:end]

    return {
        "trades": page_trades,
        "total": total,
        "page": page,
        "pages": total_pages,
    }


def _build_api_equity(equity_file: str | Path) -> dict:
    """Equity history with sharpe ratio and max drawdown."""
    equity_file = Path(equity_file)
    if not equity_file.exists():
        return {"history": [], "sharpe": 0.0, "max_drawdown": 0.0}

    tracker = EquityTracker(equity_file)
    history = [
        {
            "timestamp": s.timestamp,
            "balance_usdt": s.balance_usdt,
            "positions_value": s.positions_value,
            "total_equity": s.total_equity,
            "pnl": s.pnl,
            "pnl_pct": s.pnl_pct,
        }
        for s in tracker.history
    ]
    return {
        "history": history,
        "sharpe": tracker.sharpe_ratio(),
        "max_drawdown": tracker.max_drawdown(),
    }


def _build_api_stats(config: BotConfig) -> dict:
    """Trading statistics: pair buy/sell trades, compute PnL metrics."""
    store = TradeStore(config.db_path)
    trades = store.list_trades()

    # Pair buy trades with subsequent sell/exit trades by symbol
    pnl_list: list[float] = []
    open_positions: dict[str, list[dict]] = {}  # symbol -> list of buy trades (FIFO)

    for t in trades:
        sym = t["symbol"]
        if t["side"] == "buy":
            open_positions.setdefault(sym, []).append(t)
        elif t["side"] in ("sell", "stop_loss", "take_profit", "trailing_stop", "partial_tp"):
            if open_positions.get(sym):
                buy = open_positions[sym].pop(0)
                pnl = (t["price"] - buy["price"]) * t["amount"]
                pnl_list.append(pnl)

    total_trades = len(pnl_list)
    winning = [p for p in pnl_list if p > 0]
    losing = [p for p in pnl_list if p <= 0]
    win_rate = len(winning) / total_trades if total_trades > 0 else 0.0
    avg_win = sum(winning) / len(winning) if winning else 0.0
    avg_loss = sum(losing) / len(losing) if losing else 0.0
    gross_profit = sum(winning)
    gross_loss = abs(sum(losing))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    return {
        "total_trades": total_trades,
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "total_pnl": round(sum(pnl_list), 2),
    }


def _build_api_config(config: BotConfig) -> dict:
    """Return non-sensitive config fields."""
    return {
        "symbols": config.all_symbols,
        "strategy": config.strategy_name,
        "timeframe": config.timeframe,
        "demo": config.okx_demo,
        "fast_window": config.fast_window,
        "slow_window": config.slow_window,
        "rsi_period": config.rsi_period,
        "rsi_buy": config.rsi_buy,
        "rsi_sell": config.rsi_sell,
        "bollinger_period": config.bollinger_period,
        "bollinger_std": config.bollinger_std,
        "initial_balance": config.initial_balance_usdt,
        "order_usdt": config.order_usdt,
        "max_position_fraction": config.max_position_fraction,
        "fee_pct": config.fee_pct,
        "slippage_pct": config.slippage_pct,
        "stop_loss_pct": config.stop_loss_pct,
        "take_profit_pct": config.take_profit_pct,
        "trailing_stop_pct": config.trailing_stop_pct,
        "tp1_pct": config.tp1_pct,
        "tp1_fraction": config.tp1_fraction,
        "tp2_pct": config.tp2_pct,
        "tp2_fraction": config.tp2_fraction,
        "loop_interval_seconds": config.loop_interval_seconds,
    }


def _build_backtest_result_json(result: BacktestResult) -> dict:
    """Convert BacktestResult to a JSON-serializable dict with cumulative equity curve."""
    # Build cumulative equity curve
    equity_curve = [result.initial_balance]
    for t in result.trades:
        equity_curve.append(equity_curve[-1] + t.pnl)

    trades_list = [
        {
            "entry_time": t.entry_time,
            "entry_price": t.entry_price,
            "exit_time": t.exit_time,
            "exit_price": t.exit_price,
            "amount": t.amount,
            "side": t.side,
            "pnl": round(t.pnl, 2),
            "pnl_pct": round(t.pnl_pct, 4),
            "exit_reason": t.exit_reason,
        }
        for t in result.trades
    ]

    return {
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "start_time": result.start_time,
        "end_time": result.end_time,
        "initial_balance": result.initial_balance,
        "final_balance": round(result.final_balance, 2),
        "total_return": round(result.total_return, 4),
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "win_rate": round(result.win_rate, 4),
        "avg_win": round(result.avg_win, 2),
        "avg_loss": round(result.avg_loss, 2),
        "profit_factor": round(result.profit_factor, 2),
        "max_drawdown": round(result.max_drawdown, 4),
        "trades": trades_list,
        "equity_curve": [round(e, 2) for e in equity_curve],
    }


def _get_equity_file(config: BotConfig) -> Path:
    """Resolve equity history file path."""
    env_path = os.getenv("EQUITY_HISTORY_FILE")
    if env_path:
        return Path(env_path)
    return config.db_path.parent / "equity_history.json"


# ── HTTP Handler ─────────────────────────────────────────────────────────


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        config = BotConfig.from_env()
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/api/status":
            self._json_response(_build_api_status(config))

        elif path == "/api/trades":
            symbol = qs.get("symbol", [None])[0]
            side = qs.get("side", [None])[0]
            page = int(qs.get("page", ["1"])[0])
            per_page = int(qs.get("per_page", ["20"])[0])
            self._json_response(_build_api_trades(config, symbol=symbol, side=side, page=page, per_page=per_page))

        elif path == "/api/equity":
            equity_file = _get_equity_file(config)
            self._json_response(_build_api_equity(equity_file))

        elif path == "/api/stats":
            self._json_response(_build_api_stats(config))

        elif path == "/api/config":
            self._json_response(_build_api_config(config))

        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_build_dashboard(config).encode())

    def do_POST(self):
        config = BotConfig.from_env()
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/backtest":
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)
                params = json.loads(body) if body else {}

                from okx_paper_bot.backtester import fetch_historical_candles, run_backtest
                from okx_paper_bot.exchange import create_exchange

                symbol = params.get("symbol", config.symbol)
                timeframe = params.get("timeframe", config.timeframe)
                days = int(params.get("days", 30))
                fast = int(params.get("fast", config.fast_window))
                slow = int(params.get("slow", config.slow_window))

                # Override config for backtest
                backtest_config = BotConfig(
                    symbol=symbol,
                    timeframe=timeframe,
                    fast_window=fast,
                    slow_window=slow,
                    initial_balance_usdt=config.initial_balance_usdt,
                    order_usdt=config.order_usdt,
                    max_position_fraction=config.max_position_fraction,
                    fee_pct=config.fee_pct,
                    slippage_pct=config.slippage_pct,
                    stop_loss_pct=config.stop_loss_pct,
                    take_profit_pct=config.take_profit_pct,
                    trailing_stop_pct=config.trailing_stop_pct,
                    strategy_name=config.strategy_name,
                )

                since_ms = int((datetime.now(BJT) - timedelta(days=days)).timestamp() * 1000)
                exchange = create_exchange(config)
                candles = fetch_historical_candles(exchange, symbol, timeframe, since_ms=since_ms)
                result = run_backtest(candles, backtest_config)
                self._json_response(_build_backtest_result_json(result))

            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "not found"}).encode())

    def _json_response(self, data: dict, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, *args):
        pass  # 静默日志


def run_dashboard(host: str = "0.0.0.0", port: int = 50001) -> None:
    server = HTTPServer((host, port), DashboardHandler)
    print(f"🌐 Dashboard running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Dashboard stopped")
        server.server_close()
