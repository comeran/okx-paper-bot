# OKX Paper Bot

一个用于练习的 OKX 模拟盘量化交易项目骨架。当前实现：

- OKX demo/simulated exchange factory
- 支持从环境变量读取 OKX API 配置
- 行情抓取：从 exchange 拉取 OHLCV 收盘价
- 简单均线交叉策略：buy / sell / hold
- 风控下单金额与仓位比例限制
- 内存模拟账户，可执行市价买卖并拒绝余额/仓位不足订单
- SQLite 交易日志
- `TradingBot.run_once_from_exchange()`：从行情到交易的一次完整执行
- `TradingBot.on_prices()`：直接用收盘价序列做回测/单步执行

> 仅用于学习和模拟盘验证，不构成投资建议。

## 配置

可用 `.env` 或环境变量：

- `OKX_API_KEY`
- `OKX_API_SECRET`
- `OKX_API_PASSWORD`
- `OKX_DEMO=1|0`
- `OKX_SYMBOL`
- `OKX_TIMEFRAME`
- `FAST_WINDOW`
- `SLOW_WINDOW`
- `INITIAL_BALANCE_USDT`
- `ORDER_USDT`
- `MAX_POSITION_FRACTION`
- `DB_PATH`

## 运行测试

```bash
cd /opt/data/okx-paper-bot
/opt/hermes/.venv/bin/python3 -m pytest -q
```

## 运行一次模拟交易

```bash
cd /opt/data/okx-paper-bot
PYTHONPATH=src /opt/hermes/.venv/bin/python3 -m okx_paper_bot.cli
```

默认会：
1. 读取环境变量或 `.env`
2. 创建 OKX demo exchange（没装 `ccxt` 时自动降级为本地 FakeExchange）
3. 拉取最近一段 K 线收盘价
4. 根据均线信号决定是否交易
5. 把成交写入 `data/trades.sqlite3`

## 关键接口

- `create_okx_exchange(config)`：创建 OKX demo / fallback exchange
- `fetch_close_prices(exchange, symbol, timeframe, limit)`：读取 OHLCV 收盘价
- `TradingBot.on_prices(closes)`：直接用收盘价执行一次信号判断
- `TradingBot.run_once_from_exchange(exchange)`：从行情源执行一次完整交易循环

## 后续接 OKX 实盘/模拟盘行情

1. 安装依赖：`python -m pip install -e .`
2. 在 OKX 创建 API Key，并开启模拟盘权限。
3. 设置 `.env` 或环境变量。
4. 使用 `create_okx_exchange(BotConfig.from_env())` 创建 exchange。
5. 拉取 OHLCV 收盘价后调用 `TradingBot.run_once_from_exchange(exchange)`。
