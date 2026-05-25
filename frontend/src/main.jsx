import React, { useCallback, useEffect, useId, useMemo, useRef, useState, useTransition } from "react";
import { createChart, CandlestickSeries, LineSeries, AreaSeries, ColorType, createSeriesMarkers } from "lightweight-charts";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  Check,
  FlaskConical,
  Gauge,
  Grid3X3,
  KeyRound,
  LineChart,
  LockKeyhole,
  Pencil,
  Pause,
  Play,
  Power,
  RefreshCw,
  RotateCcw,
  Square,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  TrendingUp,
  Wallet,
  WalletCards
} from "lucide-react";
import "./styles.css";

const MASK_PLACEHOLDER = "••••••••";

const NAV = [
  ["overview", "总览", Gauge],
  ["lab", "研究室", FlaskConical],
  ["strategies", "策略库", SlidersHorizontal],
  ["run", "运行中心", Activity],
  ["orders", "成交日志", WalletCards],
  ["accounts", "账户中心", Wallet],
  ["settings", "设置", Settings]
];

const RUN_MODES = [
  ["okx_demo", "OKX Demo", "okx_demo_running"],
  ["okx_live", "OKX Live", "okx_live_running"]
];

const TRADE_SOURCE_OPTIONS = [
  ["backtest", "回测"],
  ["okx_demo", "OKX Demo"],
  ["okx_live", "OKX Live"],
  ["all", "全部"]
];

const STATUS_LABELS = {
  draft: "草稿",
  enabled: "已启用",
  okx_demo_running: "Demo 运行中",
  okx_live_running: "Live 运行中",
  paused: "已暂停",
  stopped: "已停止",
  reset: "已重置"
};

const PROMOTION_LABELS = {
  none: "未标记",
  paper_candidate: "Demo 候选",
  live_candidate: "实盘候选",
  rejected: "已拒绝"
};

const DATA_SOURCE_LABELS = {
  cached: "本地缓存",
  auto_okx: "OKX 自动拉取",
  manual: "手动导入",
  sample: "样例数据",
  okx: "OKX"
};

const MARKET_OPTIONS = [
  ["spot", "现货"],
  ["swap", "USDT 永续"]
];

const SYMBOL_OPTIONS = [
  "BTC/USDT",
  "ETH/USDT",
  "SOL/USDT",
  "BNB/USDT",
  "XRP/USDT",
  "DOGE/USDT",
  "ADA/USDT",
  "AVAX/USDT"
];

const TIMEFRAME_OPTIONS = [
  ["1m", "1 分钟"],
  ["5m", "5 分钟"],
  ["15m", "15 分钟"],
  ["30m", "30 分钟"],
  ["1h", "1 小时"],
  ["4h", "4 小时"],
  ["1d", "1 天"]
];

const TIMEFRAME_SECONDS = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "30m": 1800,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400
};

const FETCH_BATCH_CANDLES = 5000;

const PARAM_META = {
  fast: ["快线周期", "更短的均线或 EMA，反应更快。"],
  slow: ["慢线周期", "更长的均线或 EMA，过滤噪声。"],
  signal: ["信号周期", "MACD 信号线平滑周期。"],
  period: ["计算周期", "RSI 或布林带的观察窗口。"],
  oversold: ["超卖阈值", "RSI 低于该值时触发买入。"],
  overbought: ["超买阈值", "RSI 高于该值时触发卖出。"],
  std_dev: ["标准差倍数", "布林带上下轨宽度。"],
  lookback: ["突破窗口", "通道突破观察的历史 K 线数。"],
  lower_price: ["网格下沿", "网格策略的价格区间下限。"],
  upper_price: ["网格上沿", "网格策略的价格区间上限。"],
  grid_count: ["网格数量", "区间内切分的网格层数。"]
};

async function api(path, options = {}) {
  const { body, ...rest } = options;
  const payload = body && typeof body !== "string" ? JSON.stringify(body) : body;
  const res = await fetch(path, {
    ...rest,
    headers: { "Content-Type": "application/json", ...(rest.headers || {}) },
    body: payload
  });
  if (!res.ok) {
    let message = await res.text();
    try {
      const parsed = JSON.parse(message);
      message = parsed.detail || message;
    } catch {
      // keep original body
    }
    throw new Error(message || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollExperimentJob(jobId, onUpdate) {
  let delay = 700;
  for (;;) {
    await sleep(delay);
    const job = await api(`/api/experiments/jobs/${jobId}`);
    onUpdate?.(job);
    if (job.status === "completed") {
      return job.result;
    }
    if (job.status === "failed") {
      throw new Error(job.error || job.progress?.message || "实验运行失败");
    }
    delay = Math.min(1800, delay + 150);
  }
}

function App() {
  const [view, setView] = useState("overview");
  const [dashboard, setDashboard] = useState(null);
  const [strategies, setStrategies] = useState([]);
  const [instances, setInstances] = useState([]);
  const [instancePerformance, setInstancePerformance] = useState({});
  const [accounts, setAccounts] = useState([]);
  const [accountSummaries, setAccountSummaries] = useState([]);
  const [dataSummary, setDataSummary] = useState([]);
  const [experiments, setExperiments] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  const [runsPage, setRunsPage] = useState({ items: [], total: 0, page: 1, page_size: 20 });
  const [trades, setTrades] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [runDetail, setRunDetail] = useState(null);
  const [status, setStatus] = useState({ kind: "idle", text: "" });
  const [isPending, startTransition] = useTransition();

  const fetchRuns = useCallback(async (page = 1) => {
    const data = await api(`/api/runs?page=${page}&page_size=20`);
    startTransition(() => {
      setRunsPage(data);
    });
    return data;
  }, []);

  const refresh = useCallback(async () => {
    const [dash, templates, instanceRows, performanceRows, accountRows, accountSummaryRows, dataRows, experimentRows, lbRows, runsData, tradeRows] = await Promise.all([
      api("/api/dashboard"),
      api("/api/strategies"),
      api("/api/instances"),
      api("/api/instances/performance"),
      api("/api/accounts"),
      api("/api/accounts/summary"),
      api("/api/data/summary"),
      api("/api/experiments"),
      api("/api/runs/leaderboard"),
      api("/api/runs?page=1&page_size=20"),
      api("/api/trades?limit=120")
    ]);
    startTransition(() => {
      setDashboard(dash);
      setStrategies(templates);
      setInstances(instanceRows);
      setInstancePerformance(performanceRows);
      setAccounts(accountRows);
      setAccountSummaries(accountSummaryRows);
      setDataSummary(dataRows);
      setExperiments(experimentRows);
      setLeaderboard(lbRows);
      setRunsPage(runsData);
      setTrades(tradeRows);
      const firstRun = lbRows.top?.[0]?.id || lbRows.recent?.[0]?.id || runsData.items?.[0]?.id || null;
      setSelectedRun((current) => current || firstRun || null);
    });
  }, []);

  useEffect(() => {
    refresh().catch((err) => setStatus({ kind: "error", text: err.message }));
  }, [refresh]);

  useEffect(() => {
    if (!selectedRun) {
      setRunDetail(null);
      return;
    }
    api(`/api/runs/${selectedRun}`)
      .then(setRunDetail)
      .catch((err) => setStatus({ kind: "error", text: err.message }));
  }, [selectedRun]);

  async function mutate(path, body) {
    const result = await api(path, { method: "POST", body });
    await refresh();
    setStatus({ kind: "ok", text: "已更新" });
    return result;
  }

  async function patch(path, body) {
    const result = await api(path, { method: "PATCH", body });
    await refresh();
    setStatus({ kind: "ok", text: "已更新" });
    return result;
  }

  async function runAction(fn) {
    try {
      return await fn();
    } catch (err) {
      setStatus({ kind: "error", text: err.message });
      return null;
    }
  }

  const currentView = NAV.find(([key]) => key === view);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">Q</div>
          <div>
            <strong>OKX Quant</strong>
            <span>Workbench</span>
          </div>
        </div>
        <nav>
          {NAV.map(([key, label, Icon]) => (
            <button
              key={key}
              aria-label={label}
              className={view === key ? "nav-item active" : "nav-item"}
              onClick={() => setView(key)}
            >
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{currentView?.[1]}</h1>
            <p>{dashboard?.settings?.database_kind || "sqlite"} · {dashboard?.settings?.database_url || "loading"}</p>
          </div>
          <div className="topbar-actions">
            <StatusPill dashboard={dashboard} onClick={() => setView("run")} />
            <button className="icon-btn" onClick={() => runAction(refresh)} title="刷新">
              <RefreshCw size={18} className={isPending ? "spin" : ""} />
            </button>
          </div>
        </header>

        {status.text ? <div className={`toast ${status.kind}`}>{status.text}</div> : null}

        {view === "overview" && (
          <Overview
            dashboard={dashboard}
            leaderboard={leaderboard}
            accountSummaries={accountSummaries}
            runDetail={runDetail}
            setView={setView}
            setSelectedRun={setSelectedRun}
          />
        )}
        {view === "strategies" && (
          <Strategies strategies={strategies} instances={instances} accounts={accounts} mutate={mutate} patch={patch} runAction={runAction} refresh={refresh} />
        )}
        {view === "lab" && (
          <ResearchLab
            strategies={strategies}
            instances={instances}
            dataSummary={dataSummary}
            experiments={experiments}
            leaderboard={leaderboard}
            runsPage={runsPage}
            fetchRuns={fetchRuns}
            runDetail={runDetail}
            mutate={mutate}
            runAction={runAction}
            refresh={refresh}
            setSelectedRun={setSelectedRun}
            setView={setView}
            selectedRun={selectedRun}
          />
        )}
        {view === "run" && (
          <RunCenter instances={instances} accounts={accounts} accountSummaries={accountSummaries} instancePerformance={instancePerformance} mutate={mutate} patch={patch} runAction={runAction} refresh={refresh} setView={setView} />
        )}
        {view === "orders" && <TradeLogs trades={trades} runAction={runAction} setSelectedRun={setSelectedRun} setView={setView} />}
        {view === "accounts" && (
          <AccountCenter runAction={runAction} accountSummaries={accountSummaries} refresh={refresh} />
        )}
        {view === "settings" && (
          <SettingsView dashboard={dashboard} dataSummary={dataSummary} setView={setView} />
        )}
      </main>
    </div>
  );
}

function StatusPill({ dashboard, onClick }) {
  const liveEnabled = dashboard?.settings?.allow_live_trading;
  return (
    <button className={liveEnabled ? "status-pill live" : "status-pill safe"} onClick={onClick}>
      <ShieldCheck size={16} />
      <span>{liveEnabled ? "实盘就绪" : "实盘锁定"}</span>
    </button>
  );
}

function Overview({ dashboard, leaderboard, accountSummaries, runDetail, setView, setSelectedRun }) {
  const stats = [
    ["策略库", dashboard?.instances ?? 0, "strategies"],
    ["实验批次", dashboard?.experiments ?? 0, "lab"],
    ["回测结果", dashboard?.backtests ?? 0, "lab"],
    ["K 线缓存", dashboard?.candles ?? 0, "settings"],
    ["成交日志", dashboard?.trades ?? 0, "orders"]
  ];
  return (
    <section className="stack">
      <div className="metric-grid">
        {stats.map(([label, value, targetView]) => (
          <button className="metric" key={label} onClick={() => setView(targetView)}>
            <span>{label}</span>
            <strong>{value}</strong>
          </button>
        ))}
      </div>
      <div className="two-col">
        <Panel title="资金曲线 vs 标的">
          <LWEquityChart equity={runDetail?.equity_curve || []} benchmark={runDetail?.benchmark_curve || []} />
        </Panel>
        <Panel title="排行榜">
          <LeaderboardDisplay
            leaderboard={leaderboard}
            onSelect={(run) => {
              setSelectedRun(run.id);
              setView("lab");
            }}
          />
        </Panel>
      </div>
      <Panel title="账户与应用策略">
        <AccountStrategyOverview summaries={accountSummaries} setView={setView} />
      </Panel>
    </section>
  );
}

function AccountStrategyOverview({ summaries, setView }) {
  if (!summaries?.length) return <div className="empty-state">还没有账户。先在账户中心配置 OKX Demo 或 OKX Live。</div>;
  return (
    <div className="account-summary-grid">
      {summaries.map((summary) => {
        const account = summary.account;
        const stats = summary.trade_stats || {};
        const totalEq = summary.balance?.ok ? summary.balance.total_eq : null;
        return (
          <button className="account-summary-card" key={account.id} type="button" onClick={() => setView("accounts")}>
            <div className="account-summary-head">
              <span className={`mode-chip ${modeTone(account.account_type)}`}>{modeLabel(account.account_type)}</span>
              <strong>{account.name}</strong>
            </div>
            <div className="runtime-summary">
              <div><span>权益</span><strong>{totalEq ? formatNumber(totalEq) : "-"}</strong></div>
              <div><span>绑定策略</span><strong>{summary.instances?.length || 0}</strong></div>
              <div><span>运行中</span><strong>{summary.running_instances || 0}</strong></div>
              <div><span>成交</span><strong>{formatInteger(stats.trades_count)}</strong></div>
              <div><span>已实现 PnL</span><strong className={Number(stats.realized_pnl || 0) >= 0 ? "buy" : "sell"}>{formatSignedNumber(stats.realized_pnl)}</strong></div>
              <div><span>最近成交</span><strong>{shortDateTime(stats.last_trade_ts)}</strong></div>
            </div>
            <div className="strategy-tags">
              {(summary.instances || []).slice(0, 4).map((instance) => (
                <span key={instance.id}>{instance.name}</span>
              ))}
              {!summary.instances?.length ? <span>未绑定策略</span> : null}
            </div>
          </button>
        );
      })}
    </div>
  );
}

function DatasetTable({ rows }) {
  if (!rows.length) return <div className="empty-state">还没有缓存记录。首次回测会自动拉取 OKX K 线。</div>;
  return (
    <div className="table">
      <div className="table-head dataset">
        <span>来源</span><span>市场</span><span>交易对</span><span>周期</span><span>完成</span><span>范围</span>
      </div>
      {rows.map((row) => (
        <div className="table-row dataset" key={`${row.source}-${row.market_type}-${row.symbol}-${row.timeframe}`}>
          <span>{row.source}</span>
          <span>{row.market_type}</span>
          <span>{row.symbol}</span>
          <span>{row.timeframe}</span>
          <span>{row.completed}/{row.count}</span>
          <span>{shortDate(row.start_ts)} - {shortDate(row.end_ts)}</span>
        </div>
      ))}
    </div>
  );
}

function ResearchLab({ strategies, instances, dataSummary, experiments, leaderboard, runsPage, fetchRuns, runDetail, mutate, runAction, refresh, setSelectedRun, setView, selectedRun }) {
  return (
    <div className="stack">
      <ExperimentLab
        strategies={strategies}
        instances={instances}
        dataSummary={dataSummary}
        experiments={experiments}
        leaderboard={leaderboard}
        mutate={mutate}
        runAction={runAction}
        refreshDashboardData={refresh}
        setSelectedRun={setSelectedRun}
        setView={setView}
        selectedRun={selectedRun}
      />
      <Backtest
        runDetail={runDetail}
        leaderboard={leaderboard}
        runsPage={runsPage}
        fetchRuns={fetchRuns}
        selectedRun={selectedRun}
        setSelectedRun={setSelectedRun}
      />
    </div>
  );
}

function ExperimentLab({ strategies, instances, dataSummary, experiments, leaderboard, mutate, runAction, refreshDashboardData, setSelectedRun, setView, selectedRun }) {
  const [mode, setMode] = useState("custom");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pendingExperiment, setPendingExperiment] = useState(null);
  const [form, setForm] = useState({
    name: "BTC 1h MA 参数扫描",
    strategy_instance_id: null,
    strategy_key: "ma_crossover",
    symbol: "BTC/USDT",
    timeframe: "1h",
    market_type: "spot",
    initial_equity: 10000,
    order_usdt: 500,
    fee_rate: 0.001,
    slippage_rate: 0.0005,
    start_date: dateDaysAgo(30),
    end_date: todayDateInput(),
    fixed_params: {},
    param_grid: { fast: [5, 8, 13], slow: [20, 34, 55] },
    data_source: "cached"
  });
  const selectedStrategy = useMemo(
    () => strategies.find((strategy) => strategy.key === form.strategy_key),
    [strategies, form.strategy_key]
  );
  const selectedInstance = instances.find((item) => item.id === Number(form.strategy_instance_id));
  const rangeCheck = backtestRangeCheck(form);
  const canSubmit = !isSubmitting && !rangeCheck.blocked && (mode !== "instance" || Boolean(form.strategy_instance_id));

  async function submit(event) {
    event.preventDefault();
    if (!canSubmit) return;
    setIsSubmitting(true);
    setPendingExperiment({
      name: form.name,
      symbol: form.symbol,
      timeframe: form.timeframe,
      start_date: form.start_date,
      end_date: form.end_date,
      estimate: rangeCheck.estimate,
      batches: rangeCheck.batches,
      progress: { stage: "queued", message: "创建实验任务" }
    });
    const startedAt = Date.now();
    try {
      const job = await runAction(() => api("/api/experiments/jobs", { method: "POST", body: form }));
      if (!job) return;
      setPendingExperiment((current) => ({ ...current, job_id: job.id, progress: job.progress }));
      const result = await runAction(() => pollExperimentJob(job.id, (nextJob) => {
        setPendingExperiment((current) => current ? { ...current, progress: nextJob.progress, error: nextJob.error } : current);
      }));
      if (!result) return;
      await refreshDashboardData();
      if (result?.runs?.[0]) {
        setSelectedRun(result.runs[0].id);
        setView("lab");
      }
    } finally {
      const remaining = 450 - (Date.now() - startedAt);
      if (remaining > 0) {
        await new Promise((resolve) => setTimeout(resolve, remaining));
      }
      setIsSubmitting(false);
      setPendingExperiment(null);
    }
  }

  function changeStrategy(strategyKey) {
    const strategy = strategies.find((item) => item.key === strategyKey);
    setForm({
      ...form,
      name: `${strategy?.name || strategyKey} 参数扫描`,
      strategy_key: strategyKey,
      param_grid: defaultGridForStrategy(strategy)
    });
  }

  function useInstance(id) {
    const instance = instances.find((item) => item.id === Number(id));
    if (!instance) return;
    setForm({
      ...form,
      strategy_instance_id: instance.id,
      strategy_key: instance.strategy_key,
      market_type: instance.market_type,
      symbol: instance.symbol,
      timeframe: instance.timeframe,
      initial_equity: instance.initial_equity,
      order_usdt: instance.order_usdt,
      fee_rate: instance.fee_rate,
      slippage_rate: instance.slippage_rate,
      fixed_params: instance.params,
      param_grid: {},
      name: `${instance.name} 回测`
    });
  }

  return (
    <section className="stack">
      <div className="two-col wide-left">
        <Panel title="创建回测实验">
          <div className="segmented">
            <button type="button" className={mode === "custom" ? "active" : ""} onClick={() => setMode("custom")}>临时参数实验</button>
            <button type="button" className={mode === "instance" ? "active" : ""} onClick={() => setMode("instance")}>已保存策略实例</button>
          </div>
          <form className="form-grid" onSubmit={submit}>
            <TextInput label="实验名称" value={form.name} onChange={(name) => setForm({ ...form, name })} />
            {mode === "instance" ? (
              <label>
                策略实例
                <select aria-label="策略实例" value={form.strategy_instance_id || ""} onChange={(event) => useInstance(event.target.value)}>
                  <option value="">选择策略实例</option>
                  {instances.map((instance) => (
                    <option key={instance.id} value={instance.id}>{instance.name}</option>
                  ))}
                </select>
              </label>
            ) : (
              <label>
                策略
                <select aria-label="策略" value={form.strategy_key} onChange={(event) => changeStrategy(event.target.value)}>
                  {strategies.map((strategy) => (
                    <option key={strategy.key} value={strategy.key}>{strategy.name}</option>
                  ))}
                </select>
              </label>
            )}
            <ComboInput label="交易对" value={form.symbol} options={SYMBOL_OPTIONS} onChange={(symbol) => setForm({ ...form, symbol, strategy_instance_id: null })} />
            <SelectInput label="周期" value={form.timeframe} options={TIMEFRAME_OPTIONS} onChange={(timeframe) => setForm({ ...form, timeframe, strategy_instance_id: null })} />
            <SelectInput label="市场" value={form.market_type} options={MARKET_OPTIONS} onChange={(market_type) => setForm({ ...form, market_type, strategy_instance_id: null })} />
            <DateInput label="起始日期" value={form.start_date} onChange={(start_date) => setForm({ ...form, start_date })} />
            <DateInput label="结束日期" value={form.end_date} onChange={(end_date) => setForm({ ...form, end_date })} />
            <NumberInput label="初始资金" value={form.initial_equity} onChange={(initial_equity) => setForm({ ...form, initial_equity })} />
            <NumberInput label="每次下单" value={form.order_usdt} onChange={(order_usdt) => setForm({ ...form, order_usdt })} />
            <PercentInput label="手续费" value={form.fee_rate} onChange={(fee_rate) => setForm({ ...form, fee_rate })} />
            <PercentInput label="滑点" value={form.slippage_rate} onChange={(slippage_rate) => setForm({ ...form, slippage_rate })} />
            <div className={rangeCheck.warning ? "callout warning full" : "callout ok full"}>
              <strong>{rangeCheck.blocked ? "回测范围需要调整" : "回测范围"}</strong>
              <span>{rangeCheck.message}</span>
            </div>
            {mode === "custom" ? (
              <ParameterGridEditor
                strategy={selectedStrategy}
                grid={form.param_grid}
                onChange={(param_grid) => setForm({ ...form, param_grid })}
              />
            ) : (
              <div className="param-grid-editor full">
                <div className="section-label">策略参数</div>
                <pre className="param-summary">{JSON.stringify(selectedInstance?.params || {}, null, 2)}</pre>
              </div>
            )}
            <button className="primary full" type="submit" disabled={!canSubmit}>
              {isSubmitting ? <RefreshCw size={17} className="spin" /> : <Play size={17} />}
              <span>{isSubmitting ? "准备数据并运行中..." : "运行回测实验"}</span>
            </button>
          </form>
        </Panel>
        <Panel title="参数说明">
          <StrategyHelp strategy={selectedStrategy} />
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="实验列表">
          <ExperimentList
            rows={experiments}
            pending={pendingExperiment}
            onDelete={(id) => runAction(async () => {
              await api(`/api/experiments/${id}`, { method: "DELETE" });
              await refreshDashboardData();
            })}
          />
        </Panel>
        <Panel title="排行榜">
          <LeaderboardDisplay
            leaderboard={leaderboard}
            onSelect={(run) => {
              setSelectedRun(run.id);
              setView("lab");
            }}
          />
        </Panel>
      </div>
    </section>
  );
}

function Strategies({ strategies, instances, accounts, mutate, patch, runAction, refresh }) {
  const [draft, setDraft] = useState({
    name: "BTC 1h MA 趋势 v1",
    strategy_key: "ma_crossover",
    account_id: null,
    broker_mode: "okx_demo",
    market_type: "spot",
    symbol: "BTC/USDT",
    timeframe: "1h",
    initial_equity: 10000,
    order_usdt: 500,
    fee_rate: 0.001,
    slippage_rate: 0.0005,
    enabled: false,
    allow_live: false,
    params: { fast: 5, slow: 20 }
  });
  const [editingId, setEditingId] = useState(null);
  const selectedStrategy = strategies.find((strategy) => strategy.key === draft.strategy_key);

  useEffect(() => {
    setDraft((current) => {
      if (current.account_id && accountMatchesMode(accounts, current.account_id, current.broker_mode)) return current;
      const accountId = defaultAccountId(accounts, current.broker_mode);
      return accountId ? { ...current, account_id: accountId } : current;
    });
  }, [accounts]);

  function changeStrategy(strategyKey) {
    const strategy = strategies.find((item) => item.key === strategyKey);
    setDraft({
      ...draft,
      name: `${strategy?.name || strategyKey} 实例 v1`,
      strategy_key: strategyKey,
      params: singleParamsForStrategy(strategy)
    });
  }

  function editInstance(item) {
    setEditingId(item.id);
    setDraft({
      name: item.name,
      strategy_key: item.strategy_key,
      account_id: item.account_id || defaultAccountId(accounts, normalizeRunMode(item.broker_mode)),
      broker_mode: normalizeRunMode(item.broker_mode),
      market_type: item.market_type,
      symbol: item.symbol,
      timeframe: item.timeframe,
      initial_equity: item.initial_equity,
      order_usdt: item.order_usdt,
      fee_rate: item.fee_rate,
      slippage_rate: item.slippage_rate,
      enabled: item.enabled,
      allow_live: item.allow_live || false,
      params: item.params || {}
    });
  }

  function cancelEdit() {
    setEditingId(null);
    setDraft({
      name: "BTC 1h MA 趋势 v1",
      strategy_key: "ma_crossover",
      account_id: defaultAccountId(accounts, "okx_demo"),
      broker_mode: "okx_demo",
      market_type: "spot",
      symbol: "BTC/USDT",
      timeframe: "1h",
      initial_equity: 10000,
      order_usdt: 500,
      fee_rate: 0.001,
      slippage_rate: 0.0005,
      enabled: false,
      allow_live: false,
      params: { fast: 5, slow: 20 }
    });
  }

  return (
    <section className="two-col wide-left">
      <Panel title="策略实例">
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            if (editingId) {
              runAction(async () => {
                await patch(`/api/instances/${editingId}`, draft);
                setEditingId(null);
              });
            } else {
              runAction(() => mutate("/api/instances", draft));
            }
          }}
        >
          <TextInput label="实例名称" value={draft.name} onChange={(name) => setDraft({ ...draft, name })} />
          <label>
            策略
            <select aria-label="策略" value={draft.strategy_key} onChange={(event) => changeStrategy(event.target.value)}>
              {strategies.map((strategy) => (
                <option key={strategy.key} value={strategy.key}>{strategy.name}</option>
              ))}
            </select>
          </label>
          <ComboInput label="交易对" value={draft.symbol} options={SYMBOL_OPTIONS} onChange={(symbol) => setDraft({ ...draft, symbol })} />
          <SelectInput label="周期" value={draft.timeframe} options={TIMEFRAME_OPTIONS} onChange={(timeframe) => setDraft({ ...draft, timeframe })} />
          <SelectInput label="市场" value={draft.market_type} options={MARKET_OPTIONS} onChange={(market_type) => setDraft({ ...draft, market_type })} />
          <SelectInput
            label="运行环境"
            value={draft.broker_mode}
            options={RUN_MODES.map(([key, label]) => [key, label])}
            onChange={(broker_mode) => setDraft({ ...draft, broker_mode, account_id: defaultAccountId(accounts, broker_mode) })}
          />
          <AccountSelect
            label="运行账户"
            mode={draft.broker_mode}
            value={draft.account_id}
            accounts={accounts}
            onChange={(account_id) => setDraft({ ...draft, account_id })}
          />
          <NumberInput label="初始资金" value={draft.initial_equity} onChange={(initial_equity) => setDraft({ ...draft, initial_equity })} />
          <NumberInput label="每次下单" value={draft.order_usdt} onChange={(order_usdt) => setDraft({ ...draft, order_usdt })} />
          <PercentInput label="手续费" value={draft.fee_rate} onChange={(fee_rate) => setDraft({ ...draft, fee_rate })} />
          <PercentInput label="滑点" value={draft.slippage_rate} onChange={(slippage_rate) => setDraft({ ...draft, slippage_rate })} />
          <SingleParamEditor strategy={selectedStrategy} params={draft.params} onChange={(params) => setDraft({ ...draft, params })} />
          <label className="checkbox-field full">
            <input type="checkbox" checked={draft.allow_live} onChange={(event) => setDraft({ ...draft, allow_live: event.target.checked })} />
            <span>允许此实例进入 OKX Live 门禁</span>
          </label>
          <button className="primary full" type="submit"><Check size={17} /><span>{editingId ? "更新策略实例" : "保存策略实例"}</span></button>
          {editingId && <button className="full subtle" type="button" onClick={cancelEdit}>取消编辑</button>}
        </form>
      </Panel>
      <Panel title="已保存实例">
        <div className="instance-list">
          {!instances.length ? <div className="empty-state">还没有策略实例。保存后可以在研究室直接选择实例回测。</div> : null}
          {instances.map((item) => {
            const Icon = item.strategy_key === "grid" ? Grid3X3 : Activity;
            const account = accountById(accounts, item.account_id);
            return (
              <article className={item.enabled ? "instance-row enabled" : "instance-row"} key={item.id}>
                <Icon size={18} />
                <div>
                  <strong>{item.name}</strong>
                  <span>{item.strategy_key} · {item.symbol} · {item.timeframe} · {accountLabel(account)} · {statusLabel(item.status)}</span>
                </div>
                <div className="instance-actions">
                  <button title="编辑" onClick={() => editInstance(item)}><Pencil size={14} /></button>
                  <button
                    title={item.enabled ? "禁用" : "启用"}
                    className={item.enabled ? "toggle-on" : ""}
                    onClick={() => runAction(() => patch(`/api/instances/${item.id}`, { ...item, enabled: !item.enabled }))}
                  >
                    <Power size={14} />
                  </button>
                  <button title="删除" className="danger" onClick={() => {
                    if (confirm(`确定删除实例 "${item.name}"？`)) {
                      runAction(async () => {
                        await api(`/api/instances/${item.id}`, { method: "DELETE" });
                        await refresh();
                      });
                    }
                  }}><Trash2 size={14} /></button>
                </div>
              </article>
            );
          })}
        </div>
      </Panel>
    </section>
  );
}

function Backtest({ runDetail, leaderboard, runsPage, fetchRuns, selectedRun, setSelectedRun }) {
  const run = runDetail?.run;
  const { items: runs, total, page, page_size } = runsPage;
  const totalPages = Math.max(1, Math.ceil(total / page_size));
  return (
    <section className="stack">
      <div className="two-col wide-right">
        <Panel title="回测结果列表">
          <RunTable runs={runs} selectedRun={selectedRun} onSelect={setSelectedRun} />
          {totalPages > 1 && (
            <div className="pagination">
              <button disabled={page <= 1} onClick={() => fetchRuns(page - 1)}>上一页</button>
              <span>{page} / {totalPages}（共 {total} 条）</span>
              <button disabled={page >= totalPages} onClick={() => fetchRuns(page + 1)}>下一页</button>
            </div>
          )}
        </Panel>
        <Panel title="回测结果详情">
          {run ? (
            <>
              <div className="detail-title">
                <div>
                  <strong>{run.experiment_name || `Run #${run.id}`}</strong>
                  <span>{run.strategy_key} · {run.symbol} · {run.timeframe} · {dataSourceLabel(run.data_source)} · {dateRangeLabel(run)}</span>
                </div>
                <span>{formatPct(run.total_return_pct)}</span>
              </div>
              <MetricStrip run={run} />
              <BacktestComparison run={run} benchmark={runDetail.benchmark_curve || []} />
              <div className="chart-stack">
                <ChartBlock title="K 线与成交点" meta={`${(runDetail.candles || []).length} 个图表点 · ${(runDetail.trades || []).length} 笔成交`}>
                  <LWCandleChart candles={runDetail.candles || []} trades={runDetail.trades || []} />
                </ChartBlock>
                <ChartBlock title="策略 vs 买入持有" meta="绿色为策略净值，黄色为买入持有">
                  <LWEquityChart equity={runDetail.equity_curve || []} benchmark={runDetail.benchmark_curve || []} />
                </ChartBlock>
                <ChartBlock title="回撤曲线" meta="越接近 0 表示从高点回撤越小">
                  <LWDrawdownChart points={runDetail.drawdown_curve || []} />
                </ChartBlock>
              </div>
            </>
          ) : (
            <div className="empty-state">选择一个回测结果查看详情。</div>
          )}
        </Panel>
      </div>
    </section>
  );
}

function BacktestComparison({ run, benchmark }) {
  const benchmarkReturn = benchmark?.length >= 2
    ? ((Number(benchmark[benchmark.length - 1].equity) / Number(benchmark[0].equity)) - 1) * 100
    : null;
  const excess = benchmarkReturn == null ? null : Number(run.total_return_pct || 0) - benchmarkReturn;
  const items = [
    ["策略收益", formatPct(run.total_return_pct)],
    ["买入持有", benchmarkReturn == null ? "-" : formatPct(benchmarkReturn)],
    ["超额收益", excess == null ? "-" : formatPct(excess)],
    ["样本 K 线", run.candles_count || "-"]
  ];
  return (
    <div className="compare-grid">
      {items.map(([label, value]) => (
        <div key={label}>
          <span>{label}</span>
          <strong className={Number.parseFloat(value) < 0 ? "sell" : ""}>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function ChartBlock({ title, meta, children }) {
  return (
    <div className="chart-block">
      <div className="chart-heading">
        <strong>{title}</strong>
        <span>{meta}</span>
      </div>
      {children}
    </div>
  );
}

function RunCenter({ instances, accounts, accountSummaries, instancePerformance, mutate, patch, runAction, refresh, setView }) {
  const [modeDrafts, setModeDrafts] = useState({});
  const [confirmDrafts, setConfirmDrafts] = useState({});
  const [liveChecks, setLiveChecks] = useState({});
  const [selectedInstanceId, setSelectedInstanceId] = useState(null);
  const [instanceTrades, setInstanceTrades] = useState([]);
  const [tradeDetail, setTradeDetail] = useState(null);
  const [orderActions, setOrderActions] = useState({});
  const tradesPanelRef = useRef(null);

  useEffect(() => {
    setModeDrafts((current) => {
      const next = {};
      for (const instance of instances) {
        next[instance.id] = current[instance.id] || normalizeRunMode(instance.broker_mode);
      }
      return next;
    });
    setSelectedInstanceId((current) => current || instances[0]?.id || null);
  }, [instances]);

  useEffect(() => {
    if (!selectedInstanceId) {
      setInstanceTrades([]);
      setTradeDetail(null);
      return;
    }
    api(`/api/instances/${selectedInstanceId}/trades`)
      .then(setInstanceTrades)
      .catch(() => setInstanceTrades([]));
  }, [selectedInstanceId]);

  function modeForInstance(instance) {
    return normalizeRunMode(modeDrafts[instance.id] || instance.broker_mode);
  }

  function clearLiveCheck(instanceId) {
    setLiveChecks((current) => {
      const next = { ...current };
      delete next[instanceId];
      return next;
    });
  }

  function changeInstanceMode(instance, nextMode) {
    setModeDrafts((current) => ({ ...current, [instance.id]: nextMode }));
    clearLiveCheck(instance.id);
    const accountId = defaultAccountId(accounts, nextMode);
    if (accountId && (normalizeRunMode(instance.broker_mode) !== nextMode || instance.account_id !== accountId)) {
      runAction(() => patch(`/api/instances/${instance.id}`, { ...instance, broker_mode: nextMode, account_id: accountId }));
    }
  }

  function changeInstanceAccount(instance, accountId) {
    if (!accountId || instance.account_id === accountId) return;
    const account = accountById(accounts, accountId);
    const brokerMode = account?.account_type || modeForInstance(instance);
    setModeDrafts((current) => ({ ...current, [instance.id]: brokerMode }));
    clearLiveCheck(instance.id);
    runAction(() => patch(`/api/instances/${instance.id}`, { ...instance, broker_mode: brokerMode, account_id: accountId }));
  }

  async function startInstanceRun(instance) {
    const nextMode = modeForInstance(instance);
    const modeMeta = RUN_MODES.find(([key]) => key === nextMode);
    if (!modeMeta) return;
    if (!accountMatchesMode(accounts, instance.account_id, nextMode)) {
      const accountId = defaultAccountId(accounts, nextMode);
      if (!accountId) {
        await runAction(async () => { throw new Error(`${modeLabel(nextMode)} 需要先选择匹配账户`); });
        return;
      }
      await runAction(() => patch(`/api/instances/${instance.id}`, { ...instance, broker_mode: nextMode, account_id: accountId }));
    }
    if (nextMode === "okx_live") {
      const validation = await runAction(async () => api("/api/live/validate", {
        method: "POST",
        body: { broker_mode: "okx_live", instance_allow_live: instance.allow_live, confirmation: confirmDrafts[instance.id] || "" }
      }));
      if (!validation) return;
      setLiveChecks((current) => ({ ...current, [instance.id]: validation }));
      if (!validation.allowed) return;
    }
    await runAction(() => mutate(`/api/instances/${instance.id}/status`, {
      status: modeMeta[2],
      confirmation: confirmDrafts[instance.id] || ""
    }));
  }

  function updateInstanceStatus(instance, status) {
    clearLiveCheck(instance.id);
    runAction(() => mutate(`/api/instances/${instance.id}/status`, { status }));
  }

  async function reloadInstanceTrades(instanceId) {
    const rows = await api(`/api/instances/${instanceId}/trades`);
    setInstanceTrades(rows);
    return rows;
  }

  function setOrderAction(instanceId, action) {
    setOrderActions((current) => ({ ...current, [instanceId]: action }));
  }

  function focusInstanceTrades(instanceId) {
    setSelectedInstanceId(instanceId);
    requestAnimationFrame(() => {
      tradesPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  async function placeTestOrder(instance, side) {
    const quote = Math.min(Math.max(Number(instance.order_usdt || 5), 1), 5);
    const label = side === "buy" ? "测试买入" : "测试卖出";
    setOrderAction(instance.id, { kind: "loading", text: `${label}提交中...` });
    focusInstanceTrades(instance.id);
    try {
      const trade = await api(`/api/instances/${instance.id}/test-order`, {
        method: "POST",
        body: { side, quote_usdt: quote, confirmation: confirmDrafts[instance.id] || "" }
      });
      setTradeDetail(trade);
      await reloadInstanceTrades(instance.id);
      await refresh();
      setOrderAction(instance.id, {
        kind: isFailedTrade(trade) ? "warning" : "ok",
        text: `${label}${isFailedTrade(trade) ? "失败" : "已提交"}：${orderStatus(trade).reason || orderDisplayId(trade)}`,
        tradeId: trade.id
      });
    } catch (err) {
      setOrderAction(instance.id, { kind: "warning", text: `${label}失败：${err.message}` });
      await reloadInstanceTrades(instance.id).catch(() => {});
      await refresh().catch(() => {});
    }
  }

  async function openTradeDetail(trade) {
    const detail = await runAction(() => api(`/api/trades/${trade.id}`));
    if (detail) setTradeDetail(detail);
  }

  async function showInstanceTrades(instance) {
    focusInstanceTrades(instance.id);
    setTradeDetail(null);
    setOrderAction(instance.id, { kind: "info", text: `已切换到 ${instance.name} 的成交订单` });
    await reloadInstanceTrades(instance.id).catch(() => {});
  }

  const selectedInstance = instances.find((item) => item.id === selectedInstanceId);
  const selectedOrderAction = selectedInstanceId ? orderActions[selectedInstanceId] : null;

  return (
    <section className="stack">
      <Panel title="运行实例">
        <div className="run-instance-list">
          {!instances.length ? (
            <div className="empty-state">
              还没有策略实例。先去策略库保存一个实例；网格也在策略库里作为策略类型创建。
              <div className="actions-row">
                <button type="button" onClick={() => setView("strategies")}>去策略库</button>
              </div>
            </div>
          ) : null}
          {instances.map((instance) => {
            const Icon = instance.strategy_key === "grid" ? Grid3X3 : Activity;
            const runningMode = statusRunMode(instance.status);
            const instanceMode = modeForInstance(instance);
            const liveCheck = liveChecks[instance.id];
            const performance = instancePerformance?.[instance.id] || {};
            const account = accountById(accounts, instance.account_id);
            const summary = summaryForAccount(accountSummaries, instance.account_id);
            const accountOk = accountMatchesMode(accounts, instance.account_id, instanceMode);
            return (
              <article
                className={[
                  "run-instance-card",
                  runningMode ? "running" : "",
                  selectedInstanceId === instance.id ? "selected" : "",
                ].filter(Boolean).join(" ")}
                key={instance.id}
              >
                <div className="run-instance-head">
                  <Icon size={18} />
                  <div className="instance-main">
                    <strong>{instance.name}</strong>
                    <span>{instance.strategy_key} · {instance.symbol} · {instance.timeframe} · {accountLabel(account)}</span>
                  </div>
                  <span className={`mode-chip ${modeTone(instanceMode)}`}>{modeLabel(instanceMode)}</span>
                </div>
                <div className="runtime-stack">
                  <span className={`mode-badge ${modeTone(instance.broker_mode)}`}>
                    <small>默认模式</small>
                    <strong>{modeLabel(instance.broker_mode)}</strong>
                  </span>
                  <span className={`mode-badge ${runningMode ? modeTone(runningMode) : "mode-neutral"}`}>
                    <small>{runningMode ? "运行中" : "状态"}</small>
                    <strong>{runningMode ? modeLabel(runningMode) : statusLabel(instance.status)}</strong>
                  </span>
                  <span className={`mode-badge ${accountOk ? modeTone(account?.account_type) : "mode-neutral"}`}>
                    <small>运行账户</small>
                    <strong>{account ? account.name : "未选择"}</strong>
                  </span>
                  <span className="mode-badge mode-neutral">
                    <small>账户权益</small>
                    <strong>{summary?.balance?.ok && summary.balance.total_eq ? formatNumber(summary.balance.total_eq) : "-"}</strong>
                  </span>
                </div>
                <div className="runtime-performance">
                  <div className="performance-heading">
                    <strong>在线表现</strong>
                    <span>{performanceSourceLabel(performance)}</span>
                  </div>
                  <div className="performance-grid">
                    <div>
                      <span>上线收益</span>
                      <strong className={Number(performance.return_pct || 0) >= 0 ? "buy" : "sell"}>{formatPct(performance.return_pct)}</strong>
                    </div>
                    <div>
                      <span>已实现 PnL</span>
                      <strong className={Number(performance.realized_pnl || 0) >= 0 ? "buy" : "sell"}>{formatSignedNumber(performance.realized_pnl)}</strong>
                    </div>
                    <div>
                      <span>成交</span>
                      <strong>{formatInteger(performance.trades_count)}</strong>
                    </div>
                    <div>
                      <span>失败</span>
                      <strong className={Number(performance.failed_trades_count || 0) > 0 ? "sell" : ""}>{formatInteger(performance.failed_trades_count)}</strong>
                    </div>
                    <div>
                      <span>买 / 卖</span>
                      <strong>{formatInteger(performance.buy_count)} / {formatInteger(performance.sell_count)}</strong>
                    </div>
                    <div>
                      <span>净持仓</span>
                      <strong>{Number(performance.net_position || 0).toFixed(6)}</strong>
                    </div>
                    <div>
                      <span>手续费</span>
                      <strong>{formatNumber(performance.fee_paid)}</strong>
                    </div>
                    <div>
                      <span>最近成交</span>
                      <strong>{shortDateTime(performance.last_trade_ts)}</strong>
                    </div>
                  </div>
                  <LatestOrderStatus performance={performance} />
                </div>
                <div className="instance-mode-control">
                  <span>启动模式</span>
                  <div className="segmented">
                    {RUN_MODES.map(([key, label]) => (
                      <button type="button" key={key} className={instanceMode === key ? "active" : ""} onClick={() => changeInstanceMode(instance, key)}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <AccountSelect
                  label="本次运行账户"
                  mode={instanceMode}
                  value={instance.account_id}
                  accounts={accounts}
                  onChange={(accountId) => changeInstanceAccount(instance, accountId)}
                />
                {instanceMode === "okx_live" ? (
                  <div className="callout warning">
                    <strong>OKX Live 门禁</strong>
                    <span>需要环境变量 ALLOW_LIVE_TRADING=1、实例允许 Live，并输入确认短语。通过后会使用绑定的 Live 账户调用 OKX 官方接口。</span>
                    <label>
                      确认短语
                      <input
                        value={confirmDrafts[instance.id] || ""}
                        onChange={(event) => setConfirmDrafts((current) => ({ ...current, [instance.id]: event.target.value }))}
                        placeholder="输入环境变量中配置的确认短语"
                      />
                    </label>
                  </div>
                ) : null}
                <div className="run-card-actions">
                  {orderActions[instance.id] ? (
                    <div className={`action-feedback ${orderActions[instance.id].kind}`}>
                      {orderActions[instance.id].kind === "loading" ? <RefreshCw size={14} className="spin" /> : orderActions[instance.id].kind === "ok" ? <Check size={14} /> : <AlertTriangle size={14} />}
                      <span>{orderActions[instance.id].text}</span>
                    </div>
                  ) : null}
                  <button className="primary" type="button" disabled={!accountOk} onClick={() => startInstanceRun(instance)}><Play size={15} />启动</button>
                  <button type="button" onClick={() => updateInstanceStatus(instance, "paused")}><Pause size={15} />暂停</button>
                  <button type="button" onClick={() => updateInstanceStatus(instance, "stopped")}><Square size={15} />停止</button>
                  <button type="button" onClick={() => updateInstanceStatus(instance, "reset")}><RotateCcw size={15} />重置</button>
                  <button type="button" disabled={!accountOk || orderActions[instance.id]?.kind === "loading"} onClick={() => placeTestOrder(instance, "buy")}><TrendingUp size={15} />测试买入</button>
                  <button type="button" disabled={!accountOk || orderActions[instance.id]?.kind === "loading"} onClick={() => placeTestOrder(instance, "sell")}><WalletCards size={15} />测试卖出</button>
                  <button type="button" className={selectedInstanceId === instance.id ? "toggle-on" : ""} onClick={() => showInstanceTrades(instance)}><Wallet size={15} />成交</button>
                  <button type="button" onClick={() => setView("lab")}><LineChart size={15} />去回测</button>
                </div>
                {!accountOk ? (
                  <div className="callout warning">
                    <span>{modeLabel(instanceMode)} 只能选择 {modeLabel(instanceMode)} 类型账户。</span>
                  </div>
                ) : null}
                {liveCheck ? (
                  <div className={liveCheck.allowed ? "callout ok" : "callout warning"}>
                    <strong>{liveCheck.allowed ? "Live 门禁通过" : "Live 仍锁定"}</strong>
                    <span>{liveCheck.reasons?.length ? liveCheck.reasons.join("；") : "所有 Live 门禁条件已满足。"}</span>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      </Panel>
      <Panel title="实例成交订单">
        <div ref={tradesPanelRef} className="panel-anchor" />
        {!selectedInstance ? (
          <div className="empty-state">选择一个运行实例查看成交订单。</div>
        ) : (
          <div className="stack">
            <div className="detail-title">
              <div>
                <strong>{selectedInstance.name}</strong>
                <span>{selectedInstance.symbol} · {accountLabel(accountById(accounts, selectedInstance.account_id))}</span>
              </div>
              <span className={`mode-chip ${modeTone(selectedInstance.broker_mode)}`}>{modeLabel(selectedInstance.broker_mode)}</span>
            </div>
            {selectedOrderAction ? (
              <div className={`action-feedback panel-action ${selectedOrderAction.kind}`}>
                {selectedOrderAction.kind === "loading" ? <RefreshCw size={14} className="spin" /> : selectedOrderAction.kind === "ok" ? <Check size={14} /> : <AlertTriangle size={14} />}
                <span>{selectedOrderAction.text}</span>
              </div>
            ) : null}
            <InstanceTradesTable trades={instanceTrades} onOpen={openTradeDetail} />
            <OrderDetailPanel detail={tradeDetail} />
          </div>
        )}
      </Panel>
    </section>
  );
}

function InstanceTradesTable({ trades, onOpen }) {
  if (!trades?.length) return <div className="empty-state">这个实例还没有成交订单。</div>;
  return (
    <div className="table">
      <div className="table-head instance-orders"><span>订单</span><span>时间</span><span>方向</span><span>价格</span><span>数量/尝试</span><span>PnL</span><span>状态 / 错误</span></div>
      {trades.map((trade) => {
        const failed = isFailedTrade(trade);
        const status = orderStatus(trade);
        return (
          <button key={trade.id} className={failed ? "table-row instance-orders failed" : "table-row instance-orders"} onClick={() => onOpen(trade)}>
            <span>{orderDisplayId(trade)}</span>
            <span>{shortDateTime(trade.ts)}</span>
            <span className={trade.side === "buy" ? "buy" : "sell"}>{trade.side}</span>
            <span>{formatNumber(trade.price)}</span>
            <span>{formatOrderAmount(trade)}</span>
            <span className={Number(trade.pnl || 0) >= 0 ? "buy" : "sell"}>{formatSignedNumber(trade.pnl)}</span>
            <span className="order-status-cell">
              <OrderStatusPill status={status} />
              {failed ? <small>{orderErrorSummary(trade)}</small> : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function OrderDetailPanel({ detail }) {
  if (!detail) return <div className="empty-state">点击一笔成交查看 OKX 订单详情。</div>;
  const okxRow = Array.isArray(detail.okx_order?.data) ? detail.okx_order.data[0] : null;
  const status = orderStatus(detail);
  const okxState = okxRow?.state || status.label;
  const rawError = status.error || detail.okx_order_error || detail.meta?.error || "";
  return (
    <div className={isFailedTrade(detail) ? "order-detail failed" : "order-detail"}>
      <div className="detail-title">
        <div>
          <strong>{orderDisplayId(detail)}</strong>
          <span>{detail.instance_name || detail.strategy_key || "-"} · {detail.account_name || "-"} · {detail.symbol}</span>
        </div>
        <OrderStatusPill status={status} />
      </div>
      <dl className="kv order-kv">
        <dt>下单状态</dt><dd>{status.label}</dd>
        <dt>方向</dt><dd className={detail.side === "buy" ? "buy" : "sell"}>{detail.side}</dd>
        <dt>OKX 状态</dt><dd>{okxState}</dd>
        <dt>错误码</dt><dd>{status.code || "-"}</dd>
        <dt>失败原因</dt><dd className={isFailedTrade(detail) ? "error-text" : ""}>{status.reason || detail.okx_order_error || "-"}</dd>
        <dt>成交均价</dt><dd>{okxRow?.avgPx || formatNumber(detail.price)}</dd>
        <dt>委托数量</dt><dd>{okxRow?.sz || formatOrderAmount(detail)}</dd>
        <dt>尝试数量</dt><dd>{status.attempted_amount != null ? Number(status.attempted_amount || 0).toFixed(8) : "-"}</dd>
        <dt>累计成交</dt><dd>{okxRow?.accFillSz || "-"}</dd>
        <dt>手续费</dt><dd>{okxRow?.fee || formatNumber(detail.fee)}</dd>
        <dt>创建时间</dt><dd>{okxRow?.cTime ? new Date(Number(okxRow.cTime)).toLocaleString() : shortDateTime(detail.ts)}</dd>
        <dt>原始错误</dt><dd className="raw-error">{rawError || "-"}</dd>
      </dl>
    </div>
  );
}

function TradeLogs({ trades, runAction, setSelectedRun, setView }) {
  const [source, setSource] = useState("all");
  const [tradeDetail, setTradeDetail] = useState(null);
  const rows = trades.filter((trade) => source === "all" || tradeSource(trade) === source);
  const isBacktest = (trade) => trade.broker_mode === "backtest";

  async function handleClick(trade) {
    if (isBacktest(trade) && trade.run_id) {
    setSelectedRun(trade.run_id);
    setView("lab");
      return;
    }
    const detail = await runAction(() => api(`/api/trades/${trade.id}`));
    if (detail) setTradeDetail(detail);
  }

  return (
    <section className="stack">
    <Panel title="成交日志">
      <div className="source-tabs">
        {TRADE_SOURCE_OPTIONS.map(([key, label]) => (
          <button key={key} type="button" className={source === key ? "active" : ""} onClick={() => setSource(key)}>
            {label}
          </button>
        ))}
      </div>
      {!rows.length ? (
        <div className="empty-state">当前来源还没有成交记录。</div>
      ) : (
        <div className="table">
          <div className="table-head orders"><span>来源/归属</span><span>账户</span><span>订单</span><span>时间</span><span>方向</span><span>价格</span><span>数量</span><span>状态/盈亏</span></div>
          {rows.map((trade) => (
            <button
              className={isFailedTrade(trade) ? "table-row orders failed" : "table-row orders"}
              key={trade.id}
              onClick={() => handleClick(trade)}
            >
              <span>{tradeSourceLabel(trade)} · {trade.experiment_name || trade.strategy_key || `#${trade.run_id || trade.instance_id || trade.id}`}</span>
              <span>{trade.account_name || "-"}</span>
              <span>{orderDisplayId(trade)}</span>
              <span>{new Date(trade.ts).toLocaleString()}</span>
              <span className={trade.side === "buy" ? "buy" : "sell"}>{trade.side}</span>
              <span>{formatNumber(trade.price)}</span>
              <span>{formatOrderAmount(trade)}</span>
              {isFailedTrade(trade) ? (
                <span className="order-status-cell">
                  <OrderStatusPill status={orderStatus(trade)} />
                  <small>{orderErrorSummary(trade)}</small>
                </span>
              ) : (
                <span className="order-status-cell">
                  <OrderStatusPill status={orderStatus(trade)} />
                  <small>{formatNumber(trade.pnl)}</small>
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </Panel>
    <Panel title="成交订单详情">
      <OrderDetailPanel detail={tradeDetail} />
    </Panel>
    </section>
  );
}

function LatestOrderStatus({ performance }) {
  const status = performance?.last_order_status;
  if (!status) return null;
  const failed = status.state === "failed";
  return (
    <div className={failed ? "latest-order-alert failed" : "latest-order-alert"}>
      <div>
        {failed ? <AlertTriangle size={15} /> : <Check size={15} />}
        <strong>最近下单：{status.label}</strong>
        <span>{shortDateTime(performance.last_order_ts)}</span>
      </div>
      {failed ? <p>{status.code ? `错误码 ${status.code}：` : ""}{status.reason || status.error || "未知错误"}</p> : null}
    </div>
  );
}

function OrderStatusPill({ status }) {
  const state = status?.state || "recorded";
  return <span className={`order-status ${state}`}>{status?.label || "已记录"}</span>;
}

function AccountCenter({ runAction, accountSummaries, refresh }) {
  const [accounts, setAccounts] = useState([]);
  const [selectedAccount, setSelectedAccount] = useState(null);
  const [accountDetail, setAccountDetail] = useState(null);
  const [adjustResult, setAdjustResult] = useState(null);
  const [isAdjusting, setIsAdjusting] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [form, setForm] = useState({
    name: "",
    account_type: "okx_demo",
    api_key: "",
    api_secret: "",
    passphrase: "",
    is_active: true,
  });
  const [adjustForm, setAdjustForm] = useState({
    type: "increase",
    ccy: "USDT",
    amt: "5000",
  });

  const loadAccounts = useCallback(async () => {
    const data = await api("/api/accounts");
    setAccounts(data);
  }, []);

  const loadAccountDetail = useCallback(async (accountId) => {
    if (!accountId) {
      setAccountDetail(null);
      return;
    }
    try {
      const [balance, positions] = await Promise.all([
        api(`/api/accounts/${accountId}/balance`),
        api(`/api/accounts/${accountId}/positions`),
      ]);
      setAccountDetail({ balance, positions });
    } catch (err) {
      setAccountDetail({ error: err.message });
    }
  }, []);

  useEffect(() => {
    loadAccounts().catch(() => {});
  }, [loadAccounts]);

  useEffect(() => {
    if (selectedAccount) {
      setAdjustResult(null);
      loadAccountDetail(selectedAccount.id);
    }
  }, [selectedAccount, loadAccountDetail]);

  function resetForm() {
    setForm({
      name: "",
      account_type: "okx_demo",
      api_key: "",
      api_secret: "",
      passphrase: "",
      is_active: true,
    });
    setIsEditing(false);
  }

  function editAccount(account) {
    setForm({
      name: account.name,
      account_type: account.account_type,
      api_key: account.api_key,
      api_secret: "",
      passphrase: "",
      is_active: account.is_active,
    });
    setIsEditing(true);
    setSelectedAccount(account);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const payload = { ...form };
    // If editing and secret/passphrase are empty, don't update them
    if (isEditing && selectedAccount) {
      if (!payload.api_secret) delete payload.api_secret;
      if (!payload.passphrase) delete payload.passphrase;
      await runAction(() => api(`/api/accounts/${selectedAccount.id}`, { method: "PUT", body: payload }));
    } else {
      await runAction(() => api("/api/accounts", { method: "POST", body: payload }));
    }
    resetForm();
    await loadAccounts();
    await refresh();
  }

  async function handleDelete(account) {
    if (!confirm(`确定删除账户 "${account.name}"？`)) return;
    await runAction(async () => {
      await api(`/api/accounts/${account.id}`, { method: "DELETE" });
      await loadAccounts();
      await refresh();
      if (selectedAccount?.id === account.id) {
        setSelectedAccount(null);
        setAccountDetail(null);
      }
    });
  }

  async function handleAdjustDemoBalance(e) {
    e.preventDefault();
    if (!selectedAccount || selectedAccount.account_type !== "okx_demo") return;
    setIsAdjusting(true);
    setAdjustResult(null);
    try {
      const result = await runAction(() => api(`/api/accounts/${selectedAccount.id}/demo-balance-adjust`, {
        method: "POST",
        body: adjustForm,
      }));
      if (result?.ok) {
        setAdjustResult({ kind: "ok", text: "OKX Demo 余额已更新" });
        await loadAccountDetail(selectedAccount.id);
        await refresh();
      } else if (result?.error) {
        setAdjustResult({ kind: "warning", text: result.error });
      }
    } finally {
      setIsAdjusting(false);
    }
  }

  const accountTypeLabel = (type) => {
    return type === "okx_live" ? "OKX Live" : "OKX Demo";
  };
  const selectedSummary = summaryForAccount(accountSummaries, selectedAccount?.id);

  return (
    <section className="two-col wide-left">
      <Panel title="账户列表">
        <form className="form-grid compact" onSubmit={handleSubmit}>
          <TextInput label="账户名称" value={form.name} onChange={(name) => setForm({ ...form, name })} />
          <SelectInput
            label="账户类型"
            value={form.account_type}
            options={[["okx_demo", "OKX Demo"], ["okx_live", "OKX Live"]]}
            onChange={(account_type) => setForm({ ...form, account_type })}
          />
          <TextInput label="API Key" value={form.api_key} onChange={(api_key) => setForm({ ...form, api_key })} />
          <SecretInput
            label={isEditing ? "API Secret (留空不更新)" : "API Secret"}
            value={form.api_secret}
            onChange={(api_secret) => setForm({ ...form, api_secret })}
          />
          <SecretInput
            label={isEditing ? "Passphrase (留空不更新)" : "Passphrase"}
            value={form.passphrase}
            onChange={(passphrase) => setForm({ ...form, passphrase })}
          />
          <button className="primary full" type="submit">
            <Check size={17} />
            <span>{isEditing ? "更新账户" : "添加账户"}</span>
          </button>
          {isEditing && (
            <button className="full subtle" type="button" onClick={resetForm}>取消编辑</button>
          )}
        </form>

        <div className="instance-list" style={{ marginTop: 16 }}>
          {accounts.length === 0 ? (
            <div className="empty-state">还没有账户配置。添加一个 OKX API 账户开始使用。</div>
          ) : (
            accounts.map((account) => (
              (() => {
                const summary = summaryForAccount(accountSummaries, account.id);
                return (
              <article
                key={account.id}
                className={selectedAccount?.id === account.id ? "instance-row selected" : "instance-row"}
                onClick={() => setSelectedAccount(account)}
              >
                <Wallet size={18} />
                <div>
                  <strong>{account.name}</strong>
                  <span>{accountTypeLabel(account.account_type)} · {account.api_key_masked} · 策略 {summary?.instances?.length || 0} · 成交 {formatInteger(summary?.trade_stats?.trades_count)}</span>
                </div>
                <div className="instance-actions">
                  <button title="编辑" onClick={(e) => { e.stopPropagation(); editAccount(account); }}>
                    <Pencil size={14} />
                  </button>
                  <button title="删除" className="danger" onClick={(e) => { e.stopPropagation(); handleDelete(account); }}>
                    <Trash2 size={14} />
                  </button>
                </div>
              </article>
                );
              })()
            ))
          )}
        </div>
      </Panel>

      <Panel title="账户详情">
        {!selectedAccount ? (
          <div className="empty-state">选择一个账户查看详情。</div>
        ) : (
          <div className="stack">
            <div className="detail-title">
              <div>
                <strong>{selectedAccount.name}</strong>
                <span>{accountTypeLabel(selectedAccount.account_type)}</span>
              </div>
            </div>

            <div className="runtime-summary account-performance">
              <div><span>绑定策略</span><strong>{selectedSummary?.instances?.length || 0}</strong></div>
              <div><span>运行中</span><strong>{selectedSummary?.running_instances || 0}</strong></div>
              <div><span>成交</span><strong>{formatInteger(selectedSummary?.trade_stats?.trades_count)}</strong></div>
              <div><span>已实现 PnL</span><strong className={Number(selectedSummary?.trade_stats?.realized_pnl || 0) >= 0 ? "buy" : "sell"}>{formatSignedNumber(selectedSummary?.trade_stats?.realized_pnl)}</strong></div>
              <div><span>手续费</span><strong>{formatNumber(selectedSummary?.trade_stats?.fee_paid)}</strong></div>
              <div><span>最近成交</span><strong>{shortDateTime(selectedSummary?.trade_stats?.last_trade_ts)}</strong></div>
            </div>

            <div className="section-label">应用策略</div>
            {selectedSummary?.instances?.length ? (
              <div className="strategy-tags">
                {selectedSummary.instances.map((instance) => <span key={instance.id}>{instance.name} · {statusLabel(instance.status)}</span>)}
              </div>
            ) : (
              <div className="empty-state">当前账户还没有绑定策略实例。</div>
            )}

            <div className="section-label">余额</div>
            {accountDetail?.balance?.ok ? (
              Object.keys(accountDetail.balance.balances).length === 0 ? (
                <div className="empty-state">{accountDetail.balance.message || "OKX 官方 API 返回空余额"}</div>
              ) : (
                <div className="table">
                  <div className="table-head balance"><span>币种</span><span>可用</span><span>冻结</span><span>总计</span></div>
                  {Object.entries(accountDetail.balance.balances).map(([currency, data]) => (
                    <div key={currency} className="table-row balance">
                      <span>{currency}</span>
                      <span>{Number(data.free).toFixed(4)}</span>
                      <span>{Number(data.used).toFixed(4)}</span>
                      <span>{Number(data.total).toFixed(4)}</span>
                    </div>
                  ))}
                </div>
              )
            ) : accountDetail?.balance?.error ? (
              <div className="callout warning">{accountDetail.balance.error}</div>
            ) : (
              <div className="empty-state">加载中...</div>
            )}

            {selectedAccount.account_type === "okx_demo" ? (
              <>
                <div className="section-label">模拟盘余额调整</div>
                <form className="form-grid compact" onSubmit={handleAdjustDemoBalance}>
                  <SelectInput
                    label="方向"
                    value={adjustForm.type}
                    options={[["increase", "增加"], ["reduce", "减少"]]}
                    onChange={(type) => setAdjustForm({ ...adjustForm, type })}
                  />
                  <SelectInput
                    label="币种"
                    value={adjustForm.ccy}
                    options={[["USDT", "USDT"], ["BTC", "BTC"], ["ETH", "ETH"], ["OKB", "OKB"]]}
                    onChange={(ccy) => setAdjustForm({ ...adjustForm, ccy })}
                  />
                  <TextInput label="数量" value={adjustForm.amt} onChange={(amt) => setAdjustForm({ ...adjustForm, amt })} />
                  <button className="primary full" type="submit" disabled={isAdjusting}>
                    {isAdjusting ? <RefreshCw size={17} className="spin" /> : <Check size={17} />}
                    <span>{isAdjusting ? "提交中..." : "提交余额调整"}</span>
                  </button>
                </form>
                {adjustResult ? (
                  <div className={`callout ${adjustResult.kind}`}>
                    <span>{adjustResult.text}</span>
                  </div>
                ) : null}
              </>
            ) : null}

            <div className="section-label">持仓</div>
            {accountDetail?.positions?.ok ? (
              accountDetail.positions.positions.length === 0 ? (
                <div className="empty-state">{accountDetail.positions.message || "OKX 官方 API 返回空持仓"}</div>
              ) : (
                <div className="table">
                  <div className="table-head positions"><span>交易对</span><span>方向</span><span>数量</span><span>未实现盈亏</span></div>
                  {accountDetail.positions.positions.map((pos, idx) => (
                    <div key={idx} className="table-row positions">
                      <span>{pos.instId}</span>
                      <span>{pos.pos > 0 ? "多" : pos.pos < 0 ? "空" : "-"}</span>
                      <span>{pos.pos}</span>
                      <span className={Number(pos.upl) >= 0 ? "buy" : "sell"}>{Number(pos.upl || 0).toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              )
            ) : accountDetail?.positions?.error ? (
              <div className="callout warning">{accountDetail.positions.error}</div>
            ) : (
              <div className="empty-state">加载中...</div>
            )}
          </div>
        )}
      </Panel>
    </section>
  );
}

function SettingsView({ dashboard, dataSummary, setView }) {
  const settings = dashboard?.settings || {};

  return (
    <section className="two-col">
      <Panel title="系统配置">
        <dl className="kv">
          <dt>数据库</dt><dd>{settings.database_kind} · {settings.database_url}</dd>
          <dt>仪表盘地址</dt><dd>{settings.dashboard_host}:{settings.dashboard_port}</dd>
          <dt>实盘环境</dt><dd>{settings.allow_live_trading ? "ALLOW_LIVE_TRADING=1" : "ALLOW_LIVE_TRADING=0"}</dd>
          <dt>默认手续费率</dt><dd>{settings.default_fee_rate != null ? (settings.default_fee_rate * 100).toFixed(2) + "%" : "-"}</dd>
          <dt>默认滑点率</dt><dd>{settings.default_slippage_rate != null ? (settings.default_slippage_rate * 100).toFixed(3) + "%" : "-"}</dd>
          <dt>Live 确认口令</dt><dd>{settings.live_confirm_phrase_configured ? "已配置" : "未配置"}</dd>
        </dl>
        <div className="callout ok" style={{ marginTop: 12 }}>
          OKX API 凭据请在「账户中心」管理，支持多账户配置。
        </div>
      </Panel>
      <div className="stack">
        <Panel title="运行门禁">
          <p className="helper">OKX Demo、OKX Live 的启动、暂停、停止、重置和 Live 门禁校验都在运行中心完成。</p>
          <div className="actions-row">
            <button type="button" onClick={() => setView("run")}><LockKeyhole size={15} />去运行中心</button>
          </div>
        </Panel>
        <Panel title="数据诊断">
          <p className="helper">K 线缓存由回测流程自动维护；这里仅用于确认当前缓存范围。</p>
          <DatasetTable rows={dataSummary} />
        </Panel>
      </div>
    </section>
  );
}

function Panel({ title, children }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function ParameterGridEditor({ strategy, grid, onChange }) {
  const entries = Object.entries(strategy?.param_schema || {});
  if (!entries.length) {
    return (
      <div className="param-grid-editor full">
        <div className="section-label">参数候选值</div>
        <div className="empty-state">当前策略没有可配置参数</div>
      </div>
    );
  }
  return (
    <div className="param-grid-editor full">
      <div className="section-label">参数候选值</div>
      <div className="param-grid">
        {entries.map(([key, schema]) => {
          const values = grid[key] || [schema.default];
          const meta = paramMeta(key);
          return (
            <label className="param-field" key={key}>
              <span><strong>{meta.label}</strong><small><code>{key}</code> · {schemaSummary(schema)}</small></span>
              <input
                value={values.join(", ")}
                onChange={(event) => onChange({ ...grid, [key]: parseCandidateValues(event.target.value, schema) })}
                placeholder={String(schema.default)}
              />
              <em>{meta.help}</em>
            </label>
          );
        })}
      </div>
    </div>
  );
}

function SingleParamEditor({ strategy, params, onChange }) {
  const entries = Object.entries(strategy?.param_schema || {});
  return (
    <div className="param-grid-editor full">
      <div className="section-label">策略参数</div>
      <div className="param-grid">
        {entries.map(([key, schema]) => {
          const meta = paramMeta(key);
          return (
            <label className="param-field" key={key}>
              <span><strong>{meta.label}</strong><small><code>{key}</code> · {schemaSummary(schema)}</small></span>
              <input value={params[key] ?? schema.default} onChange={(event) => onChange({ ...params, [key]: parseSingleValue(event.target.value, schema) })} />
              <em>{meta.help}</em>
            </label>
          );
        })}
      </div>
    </div>
  );
}

function StrategyHelp({ strategy }) {
  const entries = Object.entries(strategy?.param_schema || {});
  if (!strategy) return <div className="empty-state">选择策略后显示参数。</div>;
  return (
    <div className="strategy-help">
      <p>{strategy.description}</p>
      <div className="help-list">
        {entries.map(([key, schema]) => {
          const meta = paramMeta(key);
          return (
            <div key={key}>
              <strong>{meta.label}</strong>
              <span><code>{key}</code> · {schemaSummary(schema)}</span>
              <small>{meta.help}</small>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function LeaderboardDisplay({ leaderboard, onSelect }) {
  const top = leaderboard?.top || [];
  const recent = leaderboard?.recent || [];
  if (!top.length && !recent.length) return <div className="empty-state">还没有回测结果。</div>;
  return (
    <div className="leaderboard">
      {top.length ? (
        <div className="leaderboard-section">
          <div className="leaderboard-label">Top 10 收益</div>
          <RunList runs={top} onSelect={onSelect} />
        </div>
      ) : null}
      {recent.length ? (
        <div className="leaderboard-section">
          <div className="leaderboard-label">最近运行</div>
          <RunList runs={recent} onSelect={onSelect} />
        </div>
      ) : null}
    </div>
  );
}

function formatParams(params) {
  if (!params || !Object.keys(params).length) return "";
  return Object.entries(params).map(([k, v]) => `${k}=${v}`).join(", ");
}

function RunList({ runs, onSelect }) {
  if (!runs.length) return <div className="empty-state">还没有回测结果。</div>;
  return (
    <div className="run-list">
      {runs.map((run) => (
        <button key={run.id} onClick={() => onSelect(run)}>
          <div className="run-list-main">
            <strong>{run.experiment_name || run.strategy_key}</strong>
            <span className="run-list-params">{run.strategy_key} · {formatParams(run.strategy_params)}</span>
          </div>
          <div className="run-list-metrics">
            <span className={run.total_return_pct >= 0 ? "buy" : "sell"}>{formatPct(run.total_return_pct)}</span>
            <span className="run-list-dd">DD {formatPct(run.max_drawdown_pct)}</span>
            <span>Sharpe {Number(run.sharpe || 0).toFixed(2)}</span>
          </div>
        </button>
      ))}
    </div>
  );
}

function ExperimentList({ rows, pending, onDelete }) {
  if (!rows.length && !pending) return <div className="empty-state">还没有实验。先在研究室运行一个回测。</div>;
  return (
    <div className="instance-list">
      {pending ? (
        <div className="pending-experiment">
          <RefreshCw size={17} className="spin" />
          <div>
            <strong>{pending.name}</strong>
            <span>{pending.symbol} · {pending.timeframe} · {shortDate(pending.start_date)} - {shortDate(pending.end_date)} · {progressMessage(pending)}</span>
            <div className={pending.progress?.percent != null ? "progress-track determinate" : "progress-track"}>
              <i style={pending.progress?.percent != null ? { width: `${Math.min(100, Math.max(2, pending.progress.percent))}%` } : undefined} />
            </div>
          </div>
          <small>{pending.estimate ? `约 ${formatInteger(pending.estimate)} 根 · ${formatInteger(pending.batches || 1)} 批` : "运行中"}</small>
        </div>
      ) : null}
      {rows.slice(0, 10).map((row) => (
        <article key={row.id} className="instance-row">
          <FlaskConical size={18} />
          <div>
            <strong>{row.name}</strong>
            <span>{row.request?.symbol} · {row.request?.timeframe} · {dataSourceLabel(row.request?.data_source)} · {shortDate(row.request?.start_ts)}</span>
          </div>
          {onDelete && (
            <div className="instance-actions">
              <button
                title="删除"
                className="danger"
                onClick={() => {
                  if (confirm(`确定删除实验 "${row.name}" 及其所有回测结果？`)) {
                    onDelete(row.id);
                  }
                }}
              >
                <Trash2 size={14} />
              </button>
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

function RunTable({ runs, selectedRun, onSelect }) {
  if (!runs.length) return <div className="empty-state">还没有回测结果。先去研究室运行一个实验。</div>;
  return (
    <div className="table">
      <div className="table-head run"><span>ID</span><span>实验</span><span>参数</span><span>收益</span><span>回撤</span><span>状态</span></div>
      {runs.map((run) => (
        <button key={run.id} className={selectedRun === run.id ? "table-row run selected" : "table-row run"} onClick={() => onSelect(run.id)}>
          <span>#{run.id}</span>
          <span>{run.experiment_name || "-"}</span>
          <span title={formatParams(run.strategy_params)}>{run.strategy_key} · {formatParams(run.strategy_params)}</span>
          <span className={run.total_return_pct >= 0 ? "buy" : "sell"}>{formatPct(run.total_return_pct)}</span>
          <span>{formatPct(run.max_drawdown_pct)}</span>
          <span>{promotionLabel(run.promotion_status)}</span>
        </button>
      ))}
    </div>
  );
}

function MetricStrip({ run }) {
  const items = [
    ["收益", formatPct(run.total_return_pct)],
    ["最大回撤", formatPct(run.max_drawdown_pct)],
    ["Sharpe", Number(run.sharpe).toFixed(2)],
    ["胜率", formatPct(run.win_rate * 100)],
    ["成交", run.trades_count],
    ["手续费", formatNumber(run.fee_paid)]
  ];
  return (
    <div className="mini-metrics">
      {items.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
    </div>
  );
}

function toLW(points, valueKey) {
  return (points || []).map((p) => ({ time: Math.floor(new Date(p.time).getTime() / 1000), value: Number(p[valueKey] || 0) }));
}

function LWCandleChart({ candles, trades }) {
  const ref = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!ref.current || !candles?.length) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#59645e", fontSize: 12 },
      grid: { vertLines: { color: "#f0f3f1" }, horzLines: { color: "#f0f3f1" } },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: "#dfe4e1" },
      timeScale: { borderColor: "#dfe4e1", timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#0a8f62", downColor: "#c93b3b",
      borderVisible: false,
      wickUpColor: "#0a8f62", wickDownColor: "#c93b3b",
    });
    series.setData(candles.map((c) => ({
      time: Math.floor(new Date(c.time).getTime() / 1000),
      open: c.open, high: c.high, low: c.low, close: c.close,
    })));

    if (trades?.length) {
      const markers = createSeriesMarkers(series);
      const sorted = [...trades].sort((a, b) => new Date(a.ts) - new Date(b.ts));
      markers.setMarkers(sorted.map((t) => ({
        time: Math.floor(new Date(t.ts).getTime() / 1000),
        position: t.side === "buy" ? "belowBar" : "aboveBar",
        color: t.side === "buy" ? "#0a8f62" : "#c93b3b",
        shape: t.side === "buy" ? "arrowUp" : "arrowDown",
        text: t.side === "buy" ? "B" : "S",
        size: 1,
      })));
    }

    chart.timeScale().fitContent();
    return () => { chart.remove(); chartRef.current = null; };
  }, [candles, trades]);

  if (!candles?.length) return <div className="empty-state">没有 K 线数据。</div>;
  return <div ref={ref} className="chart-container" />;
}

function LWEquityChart({ equity, benchmark }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current || !equity?.length) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#59645e", fontSize: 12 },
      grid: { vertLines: { color: "#f0f3f1" }, horzLines: { color: "#f0f3f1" } },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: "#dfe4e1" },
      timeScale: { borderColor: "#dfe4e1" },
    });

    const equitySeries = chart.addSeries(LineSeries, {
      color: "#159a68", lineWidth: 2, title: "策略净值",
      lastValueVisible: true, priceLineVisible: false,
    });
    equitySeries.setData(toLW(equity, "equity"));

    if (benchmark?.length) {
      const benchSeries = chart.addSeries(LineSeries, {
        color: "#d6a419", lineWidth: 2, lineStyle: 2, title: "买入持有",
        lastValueVisible: true, priceLineVisible: false,
      });
      benchSeries.setData(toLW(benchmark, "equity"));
    }

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [equity, benchmark]);

  if (!equity?.length) return <div className="empty-state">没有资金曲线数据。</div>;
  return <div ref={ref} className="chart-container" />;
}

function LWDrawdownChart({ points }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current || !points?.length) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#59645e", fontSize: 12 },
      grid: { vertLines: { color: "#f0f3f1" }, horzLines: { color: "#f0f3f1" } },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: "#dfe4e1" },
      timeScale: { borderColor: "#dfe4e1" },
    });

    const ddSeries = chart.addSeries(AreaSeries, {
      lineColor: "#cf4a4a", lineWidth: 1,
      topColor: "rgba(207, 74, 74, 0.4)", bottomColor: "rgba(207, 74, 74, 0.0)",
      lastValueVisible: true, priceLineVisible: false,
    });
    ddSeries.setData(toLW(points, "drawdown"));

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [points]);

  if (!points?.length) return <div className="empty-state">没有回撤数据。</div>;
  return <div ref={ref} className="chart-container compact-chart" />;
}


function TextInput({ label, value, onChange }) {
  const id = useId();
  return <label htmlFor={id}>{label}<input id={id} value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}

function ComboInput({ label, value, options, onChange }) {
  const id = useId();
  const listId = `${id}-options`;
  return (
    <label htmlFor={id}>
      {label}
      <input id={id} list={listId} value={value} onChange={(event) => onChange(event.target.value)} />
      <datalist id={listId}>
        {options.map((option) => <option key={option} value={option} />)}
      </datalist>
    </label>
  );
}

function SelectInput({ label, value, options, onChange }) {
  const id = useId();
  return (
    <label htmlFor={id}>
      {label}
      <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}
      </select>
    </label>
  );
}

function AccountSelect({ label, mode, value, accounts, onChange }) {
  const id = useId();
  const options = accountsForMode(accounts, mode);
  return (
    <label htmlFor={id}>
      {label}
      <select id={id} value={value || ""} disabled={!options.length} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}>
        <option value="">{options.length ? "选择账户" : `没有可用的 ${modeLabel(mode)} 账户`}</option>
        {options.map((account) => (
          <option key={account.id} value={account.id}>{account.name} · {account.api_key_masked}</option>
        ))}
      </select>
    </label>
  );
}

function DateInput({ label, value, onChange }) {
  const id = useId();
  const handleChange = (event) => onChange(event.target.value);
  return (
    <label htmlFor={id}>
      {label}
      <input id={id} type="date" value={value || ""} onInput={handleChange} onChange={handleChange} />
    </label>
  );
}

function PercentInput({ label, value, onChange }) {
  const id = useId();
  const display = Number.isFinite(Number(value)) ? Number(value) * 100 : 0;
  return (
    <label htmlFor={id}>
      {label}
      <input id={id} type="number" step="0.001" min="0" value={display} onChange={(event) => onChange(Number(event.target.value) / 100)} />
    </label>
  );
}

function SecretInput({ label, value, onChange }) {
  const id = useId();
  const isMasked = value === MASK_PLACEHOLDER;
  return (
    <label htmlFor={id}>
      {label}
      <input
        id={id}
        type={isMasked ? "text" : "password"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onFocus={() => { if (isMasked) onChange(""); }}
      />
    </label>
  );
}

function credentialValue(raw, masked, configured) {
  if (raw) return raw;
  if (masked || configured) return MASK_PLACEHOLDER;
  return "";
}

function credentialPayload(value) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  // Don't send masked values (asterisks) back to server
  if (/^\*+$/.test(trimmed)) return null;
  return trimmed;
}

function NumberInput({ label, value, onChange }) {
  const id = useId();
  return <label htmlFor={id}>{label}<input id={id} type="number" value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>;
}

function paramMeta(key) {
  const [label, help] = PARAM_META[key] || [key, ""];
  return { label, help };
}

function schemaSummary(schema) {
  const typeLabel = schema.type === "int" ? "整数" : schema.type === "float" ? "小数" : schema.type;
  const range = schema.min != null && schema.max != null ? ` · ${schema.min}-${schema.max}` : "";
  return `${typeLabel} · 默认 ${schema.default}${range}`;
}

function defaultGridForStrategy(strategy) {
  const schema = strategy?.param_schema || {};
  return Object.fromEntries(
    Object.entries(schema).map(([key, spec]) => {
      const base = Number(spec.default);
      if (!Number.isFinite(base)) return [key, [spec.default]];
      if (spec.type === "int") {
        const step = Number(spec.step || 1);
        return [key, [Math.max(Number(spec.min ?? base), base - step), base, Math.min(Number(spec.max ?? base), base + step)]];
      }
      if (spec.type === "float") {
        const step = Number(spec.step || 0.1);
        return [key, [roundCandidate(Math.max(Number(spec.min ?? base), base - step)), roundCandidate(base), roundCandidate(Math.min(Number(spec.max ?? base), base + step))]];
      }
      return [key, [spec.default]];
    })
  );
}

function singleParamsForStrategy(strategy) {
  const schema = strategy?.param_schema || {};
  return Object.fromEntries(Object.entries(schema).map(([key, spec]) => [key, spec.default]));
}

function parseCandidateValues(raw, schema) {
  const values = raw.split(",").map((item) => item.trim()).filter(Boolean).map((item) => parseSingleValue(item, schema)).filter((item) => typeof item === "number" ? Number.isFinite(item) : Boolean(item));
  return values.length ? values : [schema.default];
}

function parseSingleValue(raw, schema) {
  if (schema.type === "int") return Number.parseInt(raw, 10);
  if (schema.type === "float") return Number.parseFloat(raw);
  return raw;
}

function roundCandidate(value) {
  return Number(value.toFixed(8));
}

function accountTypeForMode(value) {
  return value === "okx_live" ? "okx_live" : "okx_demo";
}

function accountsForMode(accounts, mode) {
  const accountType = accountTypeForMode(mode);
  return (accounts || []).filter((account) => account.account_type === accountType && account.is_active !== false);
}

function accountById(accounts, accountId) {
  if (!accountId) return null;
  return (accounts || []).find((account) => Number(account.id) === Number(accountId)) || null;
}

function defaultAccountId(accounts, mode) {
  return accountsForMode(accounts, mode)[0]?.id || null;
}

function accountMatchesMode(accounts, accountId, mode) {
  const account = accountById(accounts, accountId);
  return Boolean(account && account.account_type === accountTypeForMode(mode) && account.is_active !== false);
}

function accountLabel(account) {
  if (!account) return "未选择账户";
  return `${modeLabel(account.account_type)} · ${account.name}`;
}

function summaryForAccount(summaries, accountId) {
  if (!accountId) return null;
  return (summaries || []).find((summary) => Number(summary.account?.id) === Number(accountId)) || null;
}

function normalizeRunMode(value) {
  return RUN_MODES.some(([key]) => key === value) ? value : "okx_demo";
}

function statusRunMode(status) {
  if (status === "okx_demo_running") return "okx_demo";
  if (status === "okx_live_running") return "okx_live";
  return null;
}

function modeTone(value) {
  return `mode-${normalizeRunMode(value).replaceAll("_", "-")}`;
}

function modeLabel(value) {
  return RUN_MODES.find(([key]) => key === normalizeRunMode(value))?.[1] || "OKX Demo";
}

function statusLabel(value) {
  return STATUS_LABELS[value] || value || "-";
}

function progressMessage(pending) {
  if (pending.error) return pending.error;
  const progress = pending.progress || {};
  if (progress.message) return progress.message;
  if (progress.current != null && progress.total) {
    return `已处理 ${formatInteger(progress.current)}/${formatInteger(progress.total)} 根`;
  }
  return "准备行情并运行回测";
}

function orderStatus(trade) {
  if (trade?.order_status) return trade.order_status;
  if (trade?.meta?.status === "failed") {
    return {
      state: "failed",
      label: "下单失败",
      reason: trade.meta.error || "未知错误",
      error: trade.meta.error,
      attempted_amount: trade.meta.attempted_amount
    };
  }
  const orderId = trade?.external_order_id || trade?.meta?.order_id;
  return {
    state: orderId ? "submitted" : "recorded",
    label: orderId ? "已提交" : "已记录",
    order_id: orderId || null,
    attempted_amount: trade?.amount
  };
}

function isFailedTrade(trade) {
  return orderStatus(trade).state === "failed";
}

function orderDisplayId(trade) {
  return trade?.external_order_id || trade?.meta?.order_id || trade?.order_status?.order_id || `#${trade?.id || "-"}`;
}

function formatOrderAmount(trade) {
  const status = orderStatus(trade);
  const value = status.state === "failed" && status.attempted_amount != null ? status.attempted_amount : trade?.amount;
  return Number(value || 0).toFixed(6);
}

function orderErrorSummary(trade) {
  const status = orderStatus(trade);
  return status.reason || status.exchange_message || status.error || trade?.meta?.error || "未知错误";
}

function tradeSource(trade) {
  if (trade.broker_mode === "backtest") return "backtest";
  if (trade.broker_mode === "okx_demo") return "okx_demo";
  if (trade.broker_mode === "okx_live") return "okx_live";
  return "okx_demo";
}

function tradeSourceLabel(trade) {
  return TRADE_SOURCE_OPTIONS.find(([key]) => key === tradeSource(trade))?.[1] || trade.broker_mode || "-";
}

function performanceSourceLabel(performance) {
  const modes = performance?.broker_modes || [];
  if (!Number(performance?.trades_count || 0)) return "暂无上线成交";
  if (modes.includes("okx_live") && modes.includes("okx_demo")) return "Demo / Live 成交";
  if (modes.includes("okx_live")) return "Live 成交";
  return "Demo 成交";
}

function dataSourceLabel(value) {
  return DATA_SOURCE_LABELS[value] || value || "-";
}

function promotionLabel(value) {
  return PROMOTION_LABELS[value] || value || "-";
}

function dateRangeLabel(run) {
  const start = run?.requested_start_ts || run?.start_ts;
  const end = run?.requested_end_ts || run?.end_ts;
  if (!start || !end) return "-";
  return `${shortDate(start)} - ${shortDate(end)}`;
}

function formatDateInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function todayDateInput() {
  return formatDateInput(new Date());
}

function dateDaysAgo(days) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return formatDateInput(date);
}

function parseDateInput(value) {
  if (!value) return null;
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return null;
  return new Date(year, month - 1, day);
}

function estimateBacktestCandles(startValue, endValue, timeframe) {
  const start = parseDateInput(startValue);
  const end = parseDateInput(endValue);
  const seconds = TIMEFRAME_SECONDS[timeframe];
  if (!start || !end || !seconds) return null;
  if (end < start) return -1;
  const inclusiveDays = Math.floor((end.getTime() - start.getTime()) / 86400000) + 1;
  return Math.ceil((inclusiveDays * 86400) / seconds);
}

function backtestRangeCheck(form) {
  const estimate = estimateBacktestCandles(form.start_date, form.end_date, form.timeframe);
  if (estimate == null) {
    return { blocked: true, estimate, message: "请选择起始日期和结束日期。" };
  }
  if (estimate < 0) {
    return { blocked: true, estimate, message: "结束日期不能早于起始日期。" };
  }
  const batches = Math.max(1, Math.ceil(estimate / FETCH_BATCH_CANDLES));
  if (estimate > FETCH_BATCH_CANDLES) {
    return {
      blocked: false,
      warning: true,
      estimate,
      batches,
      message: `当前范围约 ${formatInteger(estimate)} 根 K 线；系统会按约 ${formatInteger(batches)} 批自动拉取，每批最多 ${formatInteger(FETCH_BATCH_CANDLES)} 根。`
    };
  }
  return {
    blocked: false,
    warning: false,
    estimate,
    batches,
    message: `当前范围约 ${formatInteger(estimate)} 根 K 线；运行时会自动从 OKX 补齐缺口。`
  };
}

function formatInteger(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatSignedNumber(value) {
  const number = Number(value || 0);
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatPct(value) {
  return `${Number(value || 0).toFixed(2)}%`;
}

function shortDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleDateString();
}

function shortDateTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString(undefined, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

createRoot(document.getElementById("root")).render(<App />);
