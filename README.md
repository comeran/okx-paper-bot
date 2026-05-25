# OKX Quant Workbench

基于 OKX 的多策略实验、事件回测、模拟盘和实盘预留量化工作台。

> 仅用于研究与模拟验证，不构成投资建议。实盘下单默认锁定。

## 当前能力

- SQLite 首版存储：策略模板、策略实例、K 线缓存、实验批次、回测摘要、资金曲线、成交和审计事件。
- SQLAlchemy 数据访问层，`DATABASE_URL` 可切换到 MySQL，凭据只放 `.env` 或部署环境变量。
- Alembic migration 骨架。
- 预置策略：MA、RSI、MACD、布林带、突破、网格。
- K 线事件回测：只消费 completed candle，信号在 candle close 生成，下一根 K 线执行。
- 实验系统：参数网格、批量回测、排行榜、候选晋级状态。
- OKX 适配预留：`paper`、`okx_demo`、`okx_live`，Demo 自动使用 `x-simulated-trading: 1`。
- 实盘硬门禁：环境开关、策略级开关、确认短语全部通过才允许真实下单。
- React/Vite 工作台：总览、数据中心、实验室、策略实例、回测对比、网格控制台、成交、设置。

## 配置

`.env` 支持：

```bash
DATABASE_URL=sqlite:///data/okx_quant.sqlite3
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8080

OKX_API_KEY=
OKX_API_SECRET=
OKX_API_PASSWORD=

ALLOW_LIVE_TRADING=0
LIVE_CONFIRM_PHRASE=ENABLE_LIVE_TRADING
```

MySQL 可选连接示例：

```bash
DATABASE_URL=mysql+pymysql://okx:<password>@182.92.200.23:3000/<db_name>
```

不要把真实密码写入 tracked 文件。

## 后端

```bash
uv run okx-paper-bot init-db
uv run okx-paper-bot seed-sample --count 360
uv run okx-paper-bot backtest --strategy ma_crossover --params '{"fast":5,"slow":20}'
uv run okx-paper-bot dashboard --host 127.0.0.1 --port 8080
```

关键 API：

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/strategies`
- `GET/POST/PATCH /api/instances`
- `POST /api/instances/{id}/status`
- `GET /api/data/summary`
- `POST /api/candles/seed`
- `POST /api/candles/sync`
- `POST /api/backtests/run`
- `POST /api/experiments`
- `GET /api/runs`
- `GET /api/runs/{id}`
- `GET /api/trades`
- `POST /api/runs/{id}/promote`
- `POST /api/live/validate`
- `POST /api/settings/credentials`
- `POST /api/settings/live`

## 前端

开发模式：

```bash
cd frontend
npm install
npm run dev
```

生产构建：

```bash
cd frontend
npm run build
```

构建后的 `frontend/dist` 会由 FastAPI Dashboard 自动服务。

## 测试

```bash
uv run --group dev pytest -q
cd frontend && npm run build
```
