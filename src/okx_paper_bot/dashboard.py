"""Web Dashboard - 查看持仓、交易、收益。"""
from __future__ import annotations

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone, timedelta

from okx_paper_bot.config import BotConfig
from okx_paper_bot.store import TradeStore
from okx_paper_bot.paper import PaperAccount

BJT = timezone(timedelta(hours=8))

HTML_TEMPLATE = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OKX Paper Bot Dashboard</title>
<style>
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
</style>
</head><body>
<div class="card">
  <div class="header">🤖 OKX Paper Bot</div>
  <div class="refresh">自动刷新 30s | {time}</div>
</div>
<div class="card">
  <div class="metric"><div class="label">余额</div><div class="value">{balance:.2f}</div></div>
  <div class="metric"><div class="label">持仓价值</div><div class="value">{pos_value:.2f}</div></div>
  <div class="metric"><div class="label">账户总值</div><div class="value {total_class}">{total:.2f}</div></div>
  <div class="metric"><div class="label">总收益</div><div class="value {ret_class}">{return_pct:+.2f}%</div></div>
</div>
<div class="card">
  <div class="header">📦 持仓</div>
  {positions_html}
</div>
<div class="card">
  <div class="header">📋 最近交易</div>
  {trades_html}
</div>
<script>setTimeout(()=>location.reload(),30000)</script>
</body></html>"""


def _build_dashboard(config: BotConfig) -> str:
    store = TradeStore(config.db_path)
    trades = store.list_trades()

    # 重建账户状态
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

    return HTML_TEMPLATE.format(
        time=datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S"),
        balance=balance, pos_value=pos_value, total=total,
        return_pct=ret_pct,
        total_class="green" if total >= config.initial_balance_usdt else "red",
        ret_class="green" if ret_pct >= 0 else "red",
        positions_html=pos_html, trades_html=trades_html,
    )


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        config = BotConfig.from_env()
        if self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            store = TradeStore(config.db_path)
            data = {"trades": len(store.list_trades()), "time": datetime.now(BJT).isoformat()}
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_build_dashboard(config).encode())

    def log_message(self, *args):
        pass  # 静默日志


def run_dashboard(host: str = "0.0.0.0", port: int = 8080) -> None:
    server = HTTPServer((host, port), DashboardHandler)
    print(f"🌐 Dashboard running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Dashboard stopped")
        server.server_close()
