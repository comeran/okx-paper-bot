# OKX Paper Bot

一个用于练习的 OKX 模拟盘量化交易项目骨架。当前实现：

- OKX demo/simulated exchange factory
- 支持从环境变量读取 OKX API 配置
- 行情抓取：从 exchange 拉取 OHLCV 收盘价
- MA / RSI / Bollinger / MACD 策略：buy / sell / hold
- 风控下单金额与仓位比例限制
- 持久化模拟账户，每个策略实例独立账户状态
- SQLite 交易日志（审计流水，WAL + 索引）
- FastAPI dashboard，保留静态 vanilla JS 看板
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
- `ALLOW_PYRAMIDING=1|0`
- `DB_PATH`

多策略实例通过 `strategies.json` 配置。每个实例必须显式设置 `equity > 0`；`equity=0` 会在 dashboard 的 `/api/validation` 中显示为阻塞项，机器人不会按隐式全额资金启动。

## 运行测试

```bash
uv run --group dev pytest -q
```

## 运行一次模拟交易

```bash
uv run okx-paper-bot once
```

默认会：
1. 读取环境变量或 `.env`
2. 创建 OKX demo exchange（没装 `ccxt` 时自动降级为本地 FakeExchange）
3. 拉取最近一段 K 线收盘价
4. 根据均线信号决定是否交易
5. 更新对应实例的 `data/account_<实例名>.json`
6. 把成交审计写入 `data/trades.sqlite3`

## 启动 Dashboard

```bash
uv run okx-paper-bot dashboard --host 0.0.0.0 --port 8080
```

关键接口：

- `/api/health`：服务健康检查
- `/api/validation`：策略/账户/API 配置检查
- `/api/dashboard_v4`：主看板聚合数据
- `/api/config`：非敏感配置读取/保存
- `/api/instances`：策略实例读取/保存
- `/api/control`、`/api/start_bot`、`/api/run_once`：操作中心接口，写入 `data/dashboard_audit.jsonl`

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
