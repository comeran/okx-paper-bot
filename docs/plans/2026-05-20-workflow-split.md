# OKX Quant Workbench Workflow Split Plan

Date: 2026-05-20

## Goal

Clarify the user workflow by separating research/backtesting, strategy management, live or simulated running, trade logs, and data cache management. Each task should be small enough to implement, verify, and review independently.

## Principles

- Keep each task independently testable.
- Do not bundle adjacent UX or security changes unless they are required by the task.
- Preserve existing behavior unless the task explicitly changes it.
- Prefer renaming and layout separation before changing backend behavior.
- Data cache management should support the main workflow, not block it.

## Task 1: Navigation And Naming Cleanup

Status: implemented

### Purpose

Make the top-level workflow understandable before changing deeper behavior.

### Scope

- Rename or reorganize navigation around user tasks:
  - Overview
  - Research Lab
  - Strategy Library
  - Run Center
  - Trade Logs
  - Data Cache
  - Settings
- Move the current experiment and backtest surfaces under the Research Lab concept.
- Rename the current Data page to Data Cache.
- Keep existing backend APIs and core behavior unchanged.
- Keep existing strategy creation, backtest creation, result viewing, and data sync actions available.

### Out Of Scope

- No automatic OKX data fetch on backtest yet.
- No new run engine.
- No real OKX Demo or live execution changes.
- No schema migration.
- No removal of grid behavior yet.

### Acceptance Checks

- Navigation labels clearly distinguish research, strategies, running, logs, and cache.
- Existing backtest flow still works.
- Existing strategy instance save flow still works.
- Existing data sync/cache table still works.
- Existing settings page still works.
- `uv run --group dev pytest -q` passes.
- `cd frontend && npm run build` passes.

## Task 2: Grid Positioning Cleanup

Status: implemented

### Purpose

Make grid a strategy type instead of a competing top-level workflow.

### Scope

- Remove Grid as an independent top-level navigation item.
- Present grid as one strategy type in Strategy Library and Research Lab.
- Keep grid parameter creation and grid backtest available.
- Remove or relocate grid-specific simulated run controls from the grid strategy creation area.

### Out Of Scope

- No live grid trading implementation.
- No run engine work.
- No data auto-fetch work.

### Acceptance Checks

- A user can create a grid strategy configuration.
- A user can backtest a grid strategy.
- The UI no longer suggests Grid is a separate product area from research or running.

### Execution Notes

- Strategy Library owns all strategy instance creation, including `strategy_key=grid`.
- Research Lab owns historical backtests for both temporary parameters and saved strategy instances.
- Run Center should list saved strategy instances and runtime state only; it should not contain grid-specific creation or backtest controls.

## Task 3: Automatic Backtest Data Preparation

Status: implemented

### Purpose

Let users run backtests without manually syncing K-lines first.

### Scope

- Add a backend ensure-data step before backtests.
- Check local cache for the requested market, symbol, timeframe, and requested data size or range.
- If cache is missing or insufficient, fetch OKX candles and cache them.
- Run the backtest after data is available.
- Keep Data Cache page for inspection, manual refresh, and troubleshooting.

### Out Of Scope

- No UI-wide workflow redesign beyond messages needed for the data state.
- No live trading changes.
- No long-running async job queue unless the synchronous flow proves too slow for this task.

### Acceptance Checks

- A backtest can run for a new symbol/timeframe without visiting Data Cache first.
- Successful auto-fetch creates visible cache rows.
- OKX fetch failures show a clear error.
- Existing manual cache sync still works.

### Execution Notes

- API backtest and experiment creation now normalize `candles_limit` and check the latest completed cache first.
- If cache is insufficient, the API fetches OKX public candles, upserts them into the cache, records `data_source=auto_okx`, then runs the backtest.
- Research Lab no longer blocks execution when cache is empty; it tells the user data will be prepared automatically.

## Task 4: Run Center Separation

Status: implemented

### Purpose

Separate simulated, OKX Demo, and live running from historical backtesting.

### Scope

- Add or flesh out Run Center as the only place for start, pause, stop, reset, and live gate checks.
- Remove trading-start actions from Research Lab and grid strategy editing surfaces.
- Make run mode explicit:
  - Paper simulation
  - OKX Demo
  - OKX Live
- Keep live trading gate visible only in the run flow.

### Out Of Scope

- No strategy research changes unless required to link a saved strategy into Run Center.
- No trade log redesign.

### Acceptance Checks

- Research Lab only shows historical experiment actions.
- Run Center clearly owns runtime actions.
- Live checks are not mixed into backtest result review.

### Execution Notes

- Run Center now lists saved strategy instances and owns start, pause, stop, and reset status changes.
- Run mode is explicit: Paper simulation, OKX Demo, or OKX Live.
- OKX Live confirmation and gate validation moved into Run Center; Settings only manages connection and credentials.

## Task 5: Trade Log Source Filtering

Status: implemented

### Purpose

Prevent backtest, paper simulation, OKX Demo, and live trades from appearing as one undifferentiated list.

### Scope

- Add source filters for trade logs:
  - Backtest
  - Paper simulation
  - OKX Demo
  - OKX Live
- Make the selected source obvious in the UI.
- Keep row details and run/strategy links where possible.

### Out Of Scope

- No new execution engine.
- No PnL accounting redesign.

### Acceptance Checks

- Backtest trades can be viewed separately.
- Runtime trades can be viewed separately when present.
- The default view does not confuse historical and live-like trades.

### Execution Notes

- Trade Logs default to the Backtest source.
- Filters are available for Backtest, Paper simulation, OKX Demo, OKX Live, and All.
- `/api/trades` accepts a `source` query parameter for backend-side filtering.

## Follow-up: Data Cache Demotion

Status: implemented

### Purpose

Remove manual data cache management from the normal user workflow now that backtests automatically prepare OKX K-line data.

### Scope

- Remove Data Cache from top-level navigation.
- Remove manual candle sync controls from the frontend.
- Keep backend candle cache and sync APIs available for system use and diagnostics.
- Show cache ranges only as read-only Data Diagnostics under Settings.
- Keep Research Lab focused on strategy selection and backtest execution; missing data should be handled automatically and failures surfaced as errors.

### Acceptance Checks

- Left navigation no longer contains Data Cache.
- Research Lab does not route users to a manual data sync page.
- Settings shows read-only cache diagnostics.
- Backtest data preparation remains automatic.

## Follow-up: Research Lab Form Cleanup

Status: implemented

### Purpose

Make the backtest workflow read as strategy research instead of manual data-cache operation.

### Scope

- Replace free-text timeframe with fixed candidates.
- Keep trading pair editable but add common OKX symbol candidates.
- Add start/end date range to backtest experiments.
- Remove K-line quantity and the Research Lab data-preparation panel from the normal flow.
- Treat 5,000 candles as an automatic fetch batch size, not a user-facing total range limit.
- Run experiments through a background job endpoint so the UI can poll progress while data is prepared.
- Show strategy-specific parameter labels and descriptions.
- Translate promotion status values into user-facing labels.
- Add a compact comparison block and chart titles in backtest detail.
- Keep `candles_limit` as an API compatibility fallback, but do not expose it in the Research Lab UI.

### Acceptance Checks

- Research Lab has trading pair candidates, timeframe options, and start/end dates.
- Different strategies render different parameter fields from `param_schema`.
- Running a date-range experiment automatically prepares OKX candles in batches and records requested/actual range.
- Backtest lists do not display raw `none`/`nono` status values.
- Backtest detail distinguishes strategy return from buy-and-hold benchmark.

### Execution Notes

- Real OKX smoke target: BTC/USDT spot, 1h, 2026-05-20 UTC.
- Smoke result: 24 expected candles, 24 cached candles, data source `auto_okx`, run #78.
- Regression coverage added for date-range auto-fetch and candle upsert after SQLite datetime reload.
- Follow-up update: frontend no longer blocks ranges above 5,000 candles; it shows estimated batch count and polls `/api/experiments/jobs/{job_id}` for progress.
