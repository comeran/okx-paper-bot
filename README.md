# OKX Quant Workbench

多策略量化交易平台，基于 OKX 交易所，支持策略回测、参数扫描实验、模拟盘/实盘交易，以及完整的可视化工作台。

> 仅用于研究与模拟验证，不构成投资建议。实盘下单默认锁定。

## 功能概览

| 模块 | 说明 |
|---|---|
| **总览** | 仪表盘指标、权益曲线、排行榜、账户概览 |
| **研究室** | 参数网格扫描实验、批量回测、排行榜对比、K线/权益/回撤图表 |
| **策略库** | 6 个内置策略，创建/编辑/删除策略实例，参数配置 |
| **运行中心** | 策略实例启停控制，支持 OKX Demo / OKX Live，实盘三重门禁 |
| **成交日志** | 按来源（回测/Demo/Live）筛选，失败订单诊断，OKX 订单详情 |
| **账户中心** | 多账户管理，实时余额/持仓查询，模拟盘资金调整 |
| **设置** | 系统配置展示，K线缓存诊断 |

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React 19 + Vite + lightweight-charts)            │
│  7 个视图：总览 / 研究室 / 策略库 / 运行中心 / 成交 / 账户 / 设置 │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API
┌──────────────────────────▼──────────────────────────────────┐
│  FastAPI (api/__init__.py)                                  │
│  ├─ 策略实例 CRUD + 运行控制                                 │
│  ├─ 实验/回测引擎（支持异步后台任务）                          │
│  ├─ 账户管理 + OKX 余额/持仓查询                             │
│  └─ K线自动拉取 + 缓存                                      │
├─────────────────────────────────────────────────────────────┤
│  Runner (runner.py)                                         │
│  ├─ 每 8 秒轮询最新价格                                      │
│  ├─ 策略信号检测 → 立即下单                                   │
│  └─ K线批量缓存（每 5 分钟写入数据库）                         │
├─────────────────────────────────────────────────────────────┤
│  Backtest (backtest/__init__.py)                            │
│  ├─ 事件驱动：K线 N 收盘信号 → K线 N+1 执行                   │
│  └─ 防止前视偏差                                             │
├─────────────────────────────────────────────────────────────┤
│  Brokers (brokers/__init__.py)                              │
│  ├─ PaperAccount：本地模拟（回测用）                           │
│  └─ OKXGateway：ccxt + OKX REST API（Demo/Live）             │
├─────────────────────────────────────────────────────────────┤
│  SQLAlchemy ORM (persistence/)                              │
│  11 张表：策略模板/实例、K线缓存、实验、回测运行、               │
│          权益曲线、成交记录、网格状态、账户配置、系统配置、审计日志 │
└─────────────────────────────────────────────────────────────┘
```

## 快速开始

### 环境要求

- Python >= 3.11
- Node.js >= 18（前端构建）

### 安装

```bash
# 后端依赖
uv sync

# 前端依赖
cd frontend && npm install
```

### 初始化数据库

```bash
uv run okx-paper-bot init-db
```

### 启动服务

```bash
# 构建前端
cd frontend && npm run build

# 启动后端（默认 http://127.0.0.1:8080）
uv run okx-paper-bot dashboard
```

### 开发模式

```bash
# 终端 1：后端
uv run okx-paper-bot dashboard

# 终端 2：前端热重载（端口 5173，自动代理 /api 到 8080）
cd frontend && npm run dev
```

## CLI 命令

| 命令 | 说明 |
|---|---|
| `okx-paper-bot init-db` | 创建数据库表结构，种子策略模板 |
| `okx-paper-bot seed-sample [--count 360]` | 生成样本 K 线数据 |
| `okx-paper-bot backtest --strategy ma_crossover --params '{"fast":5,"slow":20}'` | 命令行运行单次回测 |
| `okx-paper-bot dashboard [--host 127.0.0.1] [--port 8080]` | 启动 Web 服务 |

## 内置策略

| 策略 | Key | 类型 | 参数 |
|---|---|---|---|
| MA 交叉 | `ma_crossover` | 趋势 | `fast`(2-100), `slow`(3-240) |
| RSI | `rsi` | 均值回归 | `period`(2-80), `oversold`(5-45), `overbought`(55-95) |
| MACD | `macd` | 趋势 | `fast`, `slow`, `signal` |
| 布林带 | `bollinger` | 均值回归 | `period`(5-160), `std_dev`(0.5-4.0) |
| 突破 | `breakout` | 通道突破 | `lookback`(5-240) |
| 网格 | `grid` | 区间网格 | `lower_price`, `upper_price`, `grid_count`(2-200) |

## 配置

通过 `.env` 文件配置系统参数：

```env
DATABASE_URL=sqlite:///data/okx_quant.sqlite3
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8080
ALLOW_LIVE_TRADING=0
LIVE_CONFIRM_PHRASE=ENABLE_LIVE_TRADING
FEE_RATE=0.001
SLIPPAGE_RATE=0.0005
```

OKX API 凭据在「账户中心」页面管理，支持配置多个账户（Demo / Live）。

MySQL 可选连接示例：

```env
DATABASE_URL=mysql+pymysql://okx:<password>@host:port/db_name
```

## 实盘安全门禁

启用 OKX Live 交易需要同时满足三个条件：

1. 环境变量 `ALLOW_LIVE_TRADING=1`
2. 策略实例勾选「允许进入 OKX Live 门禁」
3. 输入正确的确认口令（默认 `ENABLE_LIVE_TRADING`）

## 关键 API

<details>
<summary>展开查看全部 API 端点</summary>

### 系统
- `GET /api/health` — 健康检查
- `GET /api/settings` — 公共配置
- `GET /api/dashboard` — 仪表盘摘要

### K线数据
- `GET /api/data/summary` — K线缓存摘要
- `POST /api/candles/seed` — 生成样本 K 线
- `POST /api/candles/sync` — 从 OKX 同步 K 线
- `GET /api/candles` — 查询 K 线

### 策略与实例
- `GET /api/strategies` — 策略模板列表
- `GET / POST / PATCH / DELETE /api/instances` — 策略实例 CRUD
- `POST /api/instances/{id}/status` — 启动/暂停/停止实例
- `POST /api/instances/{id}/test-order` — 手动测试下单

### 实验与回测
- `POST /api/backtests/run` — 单次回测
- `POST /api/experiments/jobs` — 异步实验任务
- `GET /api/experiments/jobs/{id}` — 轮询任务进度
- `GET / POST / DELETE /api/experiments` — 实验 CRUD
- `GET /api/runs` — 分页回测结果
- `GET /api/runs/leaderboard` — 排行榜（Top 10 + 最近 3）
- `GET /api/runs/{id}` — 回测详情（K线、权益曲线、成交）

### 成交
- `GET /api/trades` — 成交日志（支持来源筛选）
- `GET /api/trades/{id}` — 成交详情

### 账户
- `GET / POST / PUT / DELETE /api/accounts` — 账户 CRUD
- `GET /api/accounts/summary` — 账户摘要（余额/持仓）
- `GET /api/accounts/{id}/balance` — OKX 余额
- `GET /api/accounts/{id}/positions` — OKX 持仓
- `POST /api/accounts/{id}/demo-balance-adjust` — 模拟盘资金调整

### 实盘验证
- `POST /api/live/validate` — 实盘门禁检查
- `POST /api/settings/live` — Live 配置验证

</details>

## 测试

```bash
uv run pytest tests/ -v
```

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 / FastAPI / SQLAlchemy / ccxt / uvicorn |
| 前端 | React 19 / Vite 6 / lightweight-charts / lucide-react |
| 数据库 | SQLite（默认）/ MySQL（可选） |
| 构建 | hatchling（Python）/ Vite（前端） |
| 包管理 | uv（Python）/ npm（前端） |
