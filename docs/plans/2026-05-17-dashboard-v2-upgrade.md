# Dashboard V2 全面升级实施计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 将 OKX Paper Bot Dashboard 从基础的静态页面升级为功能完整的实时交易监控面板，包含权益曲线、策略统计、实时推送、交互控制、回测可视化和网格交易面板。

**Architecture:** 保持 stdlib `http.server` 不引入 Flask/FastAPI（LXC 256MB 内存限制）。前端使用 CDN 引入的轻量级 JS 库（TradingView Lightweight Charts + Chart.js）。实时推送使用 Server-Sent Events (SSE)。API 层扩展多个 JSON endpoint。所有 HTML/CSS/JS 内联在 Python 字符串常量中，使用 `string.Template` 避免 CSS 花括号冲突。

**Tech Stack:** Python stdlib (http.server, json, sqlite3, threading), Chart.js 4.x CDN, vanilla JS, SSE, SQLite

---

## Phase 1: API 层扩展

### Task 1: 扩展 /api/status 返回完整账户数据

**Objective:** 让 `/api/status` 返回余额、持仓、收益、策略信息等完整账户状态。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py:119-136` (DashboardHandler.do_GET)
- Create: `tests/test_dashboard.py`

**Step 1: Write failing test**

```python
# tests/test_dashboard.py
"""Dashboard 测试。"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from okx_paper_bot.config import BotConfig
from okx_paper_bot.dashboard import _build_api_status


def test_api_status_returns_complete_fields(tmp_path):
    """api/status 应返回余额、持仓、收益等字段。"""
    db = tmp_path / "trades.sqlite3"
    config = BotConfig(db_path=db, initial_balance_usdt=1000.0)
    result = _build_api_status(config)
    assert "balance" in result
    assert "positions_value" in result
    assert "total_equity" in result
    return_pct = result["return_pct"]
    assert isinstance(return_pct, float)
    assert "positions" in result
    assert "strategy" in result
    assert "time" in result
```

**Step 2: Run test to verify failure**

Run: `cd /opt/data/okx-paper-bot && PYTHONPATH=src .venv/bin/python -m pytest tests/test_dashboard.py::test_api_status_returns_complete_fields -v`
Expected: FAIL — `_build_api_status` not defined

**Step 3: Implement _build_api_status**

在 `dashboard.py` 中添加函数：

```python
def _build_api_status(config: BotConfig) -> dict:
    """构建完整的 API 状态响应。"""
    store = TradeStore(config.db_path)
    trades = store.list_trades()

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

    prices: dict[str, float] = {}
    for t in reversed(trades):
        if t["symbol"] not in prices:
            prices[t["symbol"]] = t["price"]

    pos_value = sum(amount * prices.get(sym, 0) for sym, amount in positions.items())
    total = balance + pos_value
    ret_pct = (total - config.initial_balance_usdt) / config.initial_balance_usdt * 100

    pos_details = []
    for sym, amount in positions.items():
        price = prices.get(sym, 0)
        pos_details.append({"symbol": sym, "amount": amount, "price": price, "value": amount * price})

    return {
        "time": datetime.now(BJT).isoformat(),
        "balance": round(balance, 2),
        "positions_value": round(pos_value, 2),
        "total_equity": round(total, 2),
        "return_pct": round(ret_pct, 2),
        "initial_balance": config.initial_balance_usdt,
        "strategy": config.strategy_name,
        "positions": pos_details,
        "trades_count": len(trades),
    }
```

**Step 4: Update DashboardHandler.do_GET** 中 `/api/status` 分支调用 `_build_api_status`。

**Step 5: Run test, commit.**

---

### Task 2: 添加 /api/trades 端点（分页 + 筛选）

**Objective:** 支持按交易对、方向筛选交易历史，支持分页。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`
- Modify: `tests/test_dashboard.py`

**Step 1: Write failing test**

```python
def test_api_trades_with_filter(tmp_path):
    """api/trades 支持 symbol 和 side 筛选。"""
    db = tmp_path / "trades.sqlite3"
    config = BotConfig(db_path=db)
    store = TradeStore(db)
    store.record_trade("BTC/USDT", "buy", 0.01, 60000.0, "o1")
    store.record_trade("ETH/USDT", "buy", 0.1, 3000.0, "o2")
    store.record_trade("BTC/USDT", "sell", 0.01, 61000.0, "o3")
    result = _build_api_trades(config, symbol="BTC/USDT", side=None, page=1, per_page=10)
    assert result["total"] == 2
    assert all(t["symbol"] == "BTC/USDT" for t in result["trades"])
```

**Step 2: Implement `_build_api_trades(config, symbol=None, side=None, page=1, per_page=20)`**

返回 `{"trades": [...], "total": N, "page": P, "pages": N}`。

**Step 3: Wire into DashboardHandler** with query string parsing via `urllib.parse.parse_qs`。

**Step 4: Run test, commit.**

---

### Task 3: 添加 /api/equity 端点

**Objective:** 返回权益历史数据供前端绘制曲线。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`
- Modify: `tests/test_dashboard.py`

**Step 1: Write failing test**

```python
def test_api_equity_returns_history(tmp_path):
    """api/equity 返回权益历史列表。"""
    eq_file = tmp_path / "equity_history.json"
    data = [
        {"timestamp": "2026-05-17 10:00:00", "balance_usdt": 1000, "positions_value": 0,
         "total_equity": 1000, "pnl": 0, "pnl_pct": 0},
        {"timestamp": "2026-05-17 11:00:00", "balance_usdt": 950, "positions_value": 80,
         "total_equity": 1030, "pnl": 30, "pnl_pct": 3.0},
    ]
    eq_file.write_text(json.dumps(data))
    result = _build_api_equity(eq_file)
    assert len(result["history"]) == 2
    assert result["history"][1]["total_equity"] == 1030
    assert "sharpe" in result
    assert "max_drawdown" in result
```

**Step 2: Implement `_build_api_equity(equity_file)`**

读取 `equity_history.json`，计算 sharpe_ratio 和 max_drawdown（复用 `EquityTracker`），返回 JSON。

**Step 3: Wire into DashboardHandler.**

**Step 4: Run test, commit.**

---

### Task 4: 添加 /api/stats 端点

**Objective:** 返回策略表现统计（胜率、盈亏比、Sharpe、最大回撤等）。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`
- Modify: `tests/test_dashboard.py`

**Step 1: Write failing test**

```python
def test_api_stats_returns_metrics(tmp_path):
    """api/stats 返回策略统计指标。"""
    db = tmp_path / "trades.sqlite3"
    config = BotConfig(db_path=db, initial_balance_usdt=1000.0)
    store = TradeStore(db)
    store.record_trade("BTC/USDT", "buy", 0.01, 60000.0, "o1")
    store.record_trade("BTC/USDT", "sell", 0.01, 62000.0, "o2")
    store.record_trade("BTC/USDT", "buy", 0.01, 61000.0, "o3")
    store.record_trade("BTC/USDT", "sell", 0.01, 59000.0, "o4")
    result = _build_api_stats(config)
    assert "win_rate" in result
    assert "profit_factor" in result
    assert "total_trades" in result
    assert "avg_win" in result
    assert "avg_loss" in result
```

**Step 2: Implement `_build_api_stats(config)`**

从 trade 历史中配对 buy/sell，计算每笔盈亏、胜率、盈亏比、平均盈亏。复用 `EquityTracker` 的 sharpe 和 max_drawdown。

**Step 3: Wire into DashboardHandler.**

**Step 4: Run test, commit.**

---

### Task 5: 添加 /api/config 端点

**Objective:** 返回当前 bot 配置信息（策略、参数、交易对等），只读。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: Implement `_build_api_config(config)`**

```python
def _build_api_config(config: BotConfig) -> dict:
    return {
        "symbols": config.all_symbols,
        "strategy": config.strategy_name,
        "timeframe": config.timeframe,
        "fast_window": config.fast_window,
        "slow_window": config.slow_window,
        "rsi_period": config.rsi_period,
        "rsi_buy": config.rsi_buy,
        "rsi_sell": config.rsi_sell,
        "bollinger_period": config.bollinger_period,
        "bollinger_std": config.bollinger_std,
        "stop_loss_pct": config.stop_loss_pct,
        "take_profit_pct": config.take_profit_pct,
        "trailing_stop_pct": config.trailing_stop_pct,
        "tp1_pct": config.tp1_pct,
        "tp1_fraction": config.tp1_fraction,
        "tp2_pct": config.tp2_pct,
        "tp2_fraction": config.tp2_fraction,
        "order_usdt": config.order_usdt,
        "fee_pct": config.fee_pct,
        "loop_interval": config.loop_interval_seconds,
        "demo": config.okx_demo,
    }
```

**Step 2: Wire into DashboardHandler, commit.**

---

### Task 6: 添加 /api/backtest 端点

**Objective:** 支持通过 API 触发回测并返回结果。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: Implement handler**

接受 POST JSON `{"symbol": "BTC/USDT", "timeframe": "1h", "days": 30, "fast": 5, "slow": 20}`。

复用 `backtester.fetch_historical_candles` + `run_backtest`，返回 `BacktestResult` 的 JSON 序列化（trades 列表 + summary 字段）。

注意：回测是同步阻塞的，用 `threading.Thread` + 超时保护，避免阻塞 dashboard 主线程。

**Step 2: Wire into DashboardHandler (POST /api/backtest).**

**Step 3: Commit.**

---

## Phase 2: SSE 实时推送

### Task 7: 实现 SSE 端点 /api/stream

**Objective:** 用 Server-Sent Events 替代 30s 页面刷新，实现价格/交易/权益实时推送。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: Implement SSE handler**

```python
def do_GET(self):
    if self.path == "/api/stream":
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        # 每 5 秒推送一次状态更新
        while True:
            try:
                data = json.dumps(_build_api_status(config))
                self.wfile.write(f"data: {data}\n\n".encode())
                self.wfile.flush()
                time.sleep(5)
            except (BrokenPipeError, ConnectionResetError):
                break
```

注意：`http.server` 是单线程的，SSE 会阻塞其他请求。需要用 `ThreadingHTTPServer` 替代 `HTTPServer`。

**Step 2: Change `run_dashboard` to use `ThreadingHTTPServer`。**

**Step 3: Commit.**

---

### Task 8: 前端 JS 接入 SSE

**Objective:** 页面加载后通过 EventSource 监听 `/api/stream`，实时更新所有数据卡片。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py` (HTML_TEMPLATE)

**Step 1: 在 HTML 模板中添加 JS**

```javascript
const evtSource = new EventSource('/api/stream');
evtSource.onmessage = function(e) {
    const data = JSON.parse(e.data);
    // 更新余额、持仓、收益等 DOM
    document.getElementById('balance').textContent = data.balance.toFixed(2);
    document.getElementById('pos-value').textContent = data.positions_value.toFixed(2);
    // ... 等等
};
```

**Step 2: 移除 `setTimeout(()=>location.reload(),30000)` 刷新逻辑。**

**Step 3: Commit.**

---

## Phase 3: 前端图表

### Task 9: 权益曲线（Chart.js 折线图）

**Objective:** 展示账户净值随时间变化的折线图，标注最大回撤区间。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py` (HTML + JS)

**Step 1: 在 HTML 中添加 `<canvas id="equity-chart">` 容器。**

**Step 2: 添加 JS 从 `/api/equity` 拉取数据，用 Chart.js 绘制折线图。**

```javascript
async function loadEquityChart() {
    const res = await fetch('/api/equity');
    const data = await res.json();
    const labels = data.history.map(h => h.timestamp);
    const values = data.history.map(h => h.total_equity);
    new Chart(document.getElementById('equity-chart'), {
        type: 'line',
        data: { labels, datasets: [{ label: '账户总值', data: values, borderColor: '#58a6ff', fill: true, backgroundColor: 'rgba(88,166,255,0.1)' }] },
        options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#8b949e' } }, y: { ticks: { color: '#8b949e' } } } }
    });
}
```

**Step 3: Commit.**

---

### Task 10: 策略统计仪表盘（指标卡片 + 饼图）

**Objective:** 展示胜率、盈亏比、Sharpe、Max DD 等关键指标，用饼图展示盈亏分布。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: 添加统计卡片 HTML 区域。**

```html
<div class="card">
  <div class="header">📈 策略表现</div>
  <div class="metric"><div class="label">胜率</div><div class="value" id="win-rate">--</div></div>
  <div class="metric"><div class="label">盈亏比</div><div class="value" id="profit-factor">--</div></div>
  <div class="metric"><div class="label">Sharpe</div><div class="value" id="sharpe">--</div></div>
  <div class="metric"><div class="label">最大回撤</div><div class="value" id="max-dd">--</div></div>
</div>
```

**Step 2: JS 从 `/api/stats` 拉取数据填充。**

**Step 3: Commit.**

---

### Task 11: 多交易对持仓饼图

**Objective:** 用 Chart.js doughnut chart 展示各交易对持仓占比。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: 添加 `<canvas id="positions-pie">`。**

**Step 2: JS 从 `/api/status` 的 positions 数组绘制 doughnut chart。**

**Step 3: Commit.**

---

## Phase 4: 交易历史增强

### Task 12: 交易历史筛选 + 分页 UI

**Objective:** 添加交易对/方向筛选下拉框和分页按钮。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: 在交易历史区域添加筛选控件。**

```html
<div class="card">
  <div class="header">📋 交易历史</div>
  <div class="filters">
    <select id="filter-symbol"><option value="">全部交易对</option></select>
    <select id="filter-side">
      <option value="">全部方向</option>
      <option value="buy">买入</option>
      <option value="sell">卖出</option>
    </select>
  </div>
  <div id="trades-table"></div>
  <div id="trades-pagination"></div>
</div>
```

**Step 2: JS 从 `/api/trades?symbol=X&side=Y&page=Z` 拉取数据，渲染表格和分页。**

**Step 3: Commit.**

---

### Task 13: 交易盈亏计算

**Objective:** 配对 buy/sell 交易，计算每笔已平仓交易的盈亏金额和百分比，在交易历史中显示。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py` (`_build_api_trades`)

**Step 1: 在 `_build_api_trades` 中增加盈亏计算逻辑。**

对每笔 sell 交易，向前查找最近的同 symbol 未配对 buy，计算 `pnl = (sell_price - buy_price) * amount - fees`。

**Step 2: 前端表格增加"盈亏"列，绿色/红色显示。**

**Step 3: Commit.**

---

## Phase 5: 回测可视化

### Task 14: 回测面板 UI

**Objective:** 在 Dashboard 中添加回测表单，展示回测结果。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: 添加回测面板 HTML。**

```html
<div class="card">
  <div class="header">🧪 回测</div>
  <div class="backtest-form">
    <select id="bt-symbol">...</select>
    <select id="bt-timeframe">
      <option value="1h">1小时</option><option value="4h">4小时</option><option value="1d">1天</option>
    </select>
    <input id="bt-days" type="number" value="30" min="1" max="365">
    <button id="bt-run" onclick="runBacktest()">运行回测</button>
  </div>
  <div id="bt-result"></div>
  <canvas id="bt-chart"></canvas>
</div>
```

**Step 2: JS `runBacktest()` 发 POST 到 `/api/backtest`，渲染结果指标 + 权益曲线。**

**Step 3: Commit.**

---

### Task 15: 回测结果图表

**Objective:** 用 Chart.js 展示回测权益曲线和买卖点位。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: 回测 API 返回逐笔权益序列（`initial_balance` → 每笔 trade 的 `cumulative_pnl`）。**

**Step 2: 用 Chart.js line chart 绘制，buy 点用绿色三角标，sell 点用红色三角标。**

**Step 3: Commit.**

---

## Phase 6: 网格交易面板

### Task 16: /api/grid 端点

**Objective:** 返回网格交易状态（配置、各级别状态、循环数、累计利润）。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: Implement `_build_api_grid(config)`**

读取 bot 运行时的 `GridState`（需要某种方式共享状态，最简方案：grid 状态序列化到 `data/grid_state.json`，dashboard 读取）。

**Step 2: Wire into DashboardHandler.**

**Step 3: Commit.**

---

### Task 17: 网格交易 UI

**Objective:** 可视化网格区间、各级别买卖状态、利润统计。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: 添加网格面板 HTML。**

```html
<div class="card">
  <div class="header">📊 网格交易</div>
  <div id="grid-info"></div>
  <div id="grid-visual"></div>
</div>
```

**Step 2: JS 绘制网格可视化 — 价格轴 + 横线标记各级别状态（已买/待卖/空闲用不同颜色）。**

**Step 3: Commit.**

---

## Phase 7: 交互式控制

### Task 18: /api/control 端点（启动/停止/参数热更新）

**Objective:** 支持通过 Dashboard 控制 bot 运行状态。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: Implement control endpoint**

- `POST /api/control` body: `{"action": "restart"}` 或 `{"action": "update_config", "params": {...}}`
- restart: 发 SIGTERM 给 bot 进程，systemd 自动重启
- update_config: 写入 `.env` 文件，发 SIGHUP 让 bot 重新加载（需要 bot 支持热重载，或简单地重启）

⚠️ 安全考虑：此端点仅限内网访问，不暴露到公网。

**Step 2: Commit.**

---

### Task 19: 控制面板 UI

**Objective:** 添加启动/停止按钮和参数调整表单。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: 添加控制面板 HTML。**

```html
<div class="card">
  <div class="header">⚙️ 控制面板</div>
  <div class="controls">
    <button onclick="controlBot('restart')">🔄 重启 Bot</button>
    <button onclick="controlBot('stop')">⏹ 停止 Bot</button>
  </div>
  <div class="param-form">
    <label>止损 %: <input id="cfg-sl" type="number" step="0.01"></label>
    <label>止盈 %: <input id="cfg-tp" type="number" step="0.01"></label>
    <button onclick="updateConfig()">应用</button>
  </div>
</div>
```

**Step 2: JS 绑定按钮事件。**

**Step 3: Commit.**

---

## Phase 8: UI/UX 打磨

### Task 20: 响应式布局 + 移动端适配

**Objective:** Dashboard 在手机上可用。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py` (CSS)

**Step 1: 添加 CSS 媒体查询。**

```css
@media (max-width: 768px) {
  .metric { display: block; margin: 8px 0; }
  .card { padding: 12px; }
  table { font-size: 13px; }
  th, td { padding: 4px 8px; }
}
```

**Step 2: 添加 `<meta name="viewport">` 确认已存在（已存在）。**

**Step 3: Commit.**

---

### Task 21: 顶部状态栏 + 导航

**Objective:** 添加顶部导航栏，支持切换不同面板区域。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: 添加导航栏 HTML。**

```html
<nav class="nav">
  <a href="#overview">总览</a>
  <a href="#equity">权益</a>
  <a href="#trades">交易</a>
  <a href="#backtest">回测</a>
  <a href="#grid">网格</a>
  <a href="#settings">设置</a>
</nav>
```

**Step 2: CSS 样式 + 锚点定位。**

**Step 3: Commit.**

---

### Task 22: 加载状态 + 错误处理

**Objective:** 图表加载时显示 spinner，API 失败时显示友好错误。

**Files:**
- Modify: `src/okx_paper_bot/dashboard.py`

**Step 1: 添加 CSS spinner 动画。**

**Step 2: JS fetch 添加 try/catch 和 loading 状态。**

**Step 3: Commit.**

---

## Phase 9: 测试 + 部署

### Task 23: 完善 dashboard 测试

**Objective:** 确保所有新 API endpoint 有测试覆盖。

**Files:**
- Modify: `tests/test_dashboard.py`

**Step 1: 补充边界测试：**
- 空交易历史
- 只有 buy 没有 sell
- 单交易对 vs 多交易对
- equity_history.json 不存在
- 分页边界（page > total_pages）

**Step 2: 运行全量测试确保无回归。**

```bash
cd /opt/data/okx-paper-bot
PYTHONPATH=src .venv/bin/python -m pytest tests/ -v
```

**Step 3: Commit.**

---

### Task 24: 更新 PVE LXC 部署

**Objective:** 将升级后的 dashboard 部署到 CT 101。

**Files:**
- None (deployment step)

**Step 1: 同步代码到 LXC。**

```bash
cd /opt/data/okx-paper-bot
tar --exclude='.venv' --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' \
  -czf /tmp/okx-dashboard-v2.tar.gz .
scp /tmp/okx-dashboard-v2.tar.gz root@192.168.1.2:/tmp/
ssh root@192.168.1.2 "pct push 101 /tmp/okx-dashboard-v2.tar.gz /tmp/okx-dashboard-v2.tar.gz"
ssh root@192.168.1.2 "pct exec 101 -- bash -lc 'cd /opt/okx-paper-bot && tar -xzf /tmp/okx-dashboard-v2.tar.gz'"
```

**Step 2: 重启 dashboard service。**

```bash
ssh root@192.168.1.2 "pct exec 101 -- systemctl restart okx-dashboard"
```

**Step 3: 验证。**

```bash
ssh root@192.168.1.2 "pct exec 101 -- curl -fsS http://127.0.0.1:50001/api/status"
```

**Step 4: Commit deployment notes.**

---

### Task 25: 更新 SKILL.md 文档

**Objective:** 更新 okx-paper-bot skill 文档，记录新的 dashboard 功能和 API。

**Files:**
- Modify: `~/skills/quant-trading/okx-paper-bot/SKILL.md`

**Step 1: 更新 Dashboard 段落，记录所有新 API endpoint。**

**Step 2: 更新 Architecture 段落。**

**Step 3: Commit.**

---

## 任务依赖关系

```
Phase 1 (API层): Task 1 → 2 → 3 → 4 → 5 → 6 (可并行 1-5)
Phase 2 (SSE):   Task 7 → 8
Phase 3 (图表):  Task 9 → 10 → 11 (依赖 Task 3,4)
Phase 4 (交易历史): Task 12 → 13 (依赖 Task 2)
Phase 5 (回测):  Task 14 → 15 (依赖 Task 6)
Phase 6 (网格):  Task 16 → 17
Phase 7 (控制):  Task 18 → 19
Phase 8 (UX):    Task 20 → 21 → 22 (可并行)
Phase 9 (测试部署): Task 23 → 24 → 25
```

## 预计工作量

| Phase | Tasks | 预计时间 |
|-------|-------|----------|
| Phase 1: API 层 | 6 | 30-40 min |
| Phase 2: SSE | 2 | 15-20 min |
| Phase 3: 图表 | 3 | 20-30 min |
| Phase 4: 交易历史 | 2 | 15-20 min |
| Phase 5: 回测 | 2 | 15-20 min |
| Phase 6: 网格 | 2 | 15-20 min |
| Phase 7: 控制 | 2 | 15-20 min |
| Phase 8: UX | 3 | 15-20 min |
| Phase 9: 测试部署 | 3 | 20-30 min |
| **总计** | **25** | **~3-4 小时** |

## 注意事项

- **`string.Template`**: CSS 包含 `{}`，必须用 `Template` + `$var`，不能用 `str.format()`
- **`ThreadingHTTPServer`**: SSE 需要并发连接，必须用 `ThreadingHTTPServer`
- **内存限制**: LXC 256MB，Chart.js 用 CDN 引入，不打包
- **安全**: 控制端点仅限内网，不暴露公网
- **兼容性**: 保持现有 `/api/status` 返回格式不变（前端可能有依赖）
