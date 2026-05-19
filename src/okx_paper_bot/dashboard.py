"""Web Dashboard v3 - 每策略独立看板 + 回测对比 + 全命令可用。"""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import time
import threading
from string import Template
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

from okx_paper_bot.config import BotConfig, StrategyInstance, load_strategy_instances, save_strategy_instances
from okx_paper_bot.store import TradeStore
from okx_paper_bot.stats import EquityTracker
from okx_paper_bot.backtest import BacktestResult

BJT = timezone(timedelta(hours=8))

CSS = """
  :root { --bg:#0b1018; --panel:#111827; --panel2:#161f2e; --border:#273244; --text:#dbe7ff; --muted:#8796ad; --accent:#35c2ff; --blue:#58a6ff; --green:#3fb950; --red:#ff6b6b; --yellow:#f2c94c; --purple:#b987ff; --shadow:0 14px 40px rgba(0,0,0,.28); }
  *{box-sizing:border-box} body{margin:0;background:radial-gradient(circle at top left,rgba(53,194,255,.10),transparent 34%),var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.45} a{color:inherit;text-decoration:none}
  .topbar{position:sticky;top:0;z-index:50;background:rgba(11,16,24,.86);backdrop-filter:blur(16px);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:14px;padding:10px 18px;overflow-x:auto}.brand{font-weight:800;color:var(--accent);white-space:nowrap}.brand small{display:block;color:var(--muted);font-weight:500;font-size:11px}.topbar a{padding:8px 10px;border-radius:999px;color:var(--muted);white-space:nowrap;font-size:13px}.topbar a:hover,.topbar a.active{background:rgba(53,194,255,.12);color:var(--text)}
  .wrap{max-width:1500px;margin:0 auto;padding:18px}.hero{display:grid;grid-template-columns:1.2fr .8fr;gap:14px;margin-bottom:14px}.card{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--border);border-radius:16px;padding:16px;box-shadow:var(--shadow)}.section{scroll-margin-top:68px;margin:16px 0}.section-title{font-size:18px;font-weight:800;margin:0 0 12px;display:flex;align-items:center;gap:8px}.sub{font-size:12px;color:var(--muted);margin-top:-6px;margin-bottom:12px}.grid{display:grid;gap:12px}.grid-2{grid-template-columns:repeat(2,minmax(0,1fr))}.grid-3{grid-template-columns:repeat(3,minmax(0,1fr))}.grid-4{grid-template-columns:repeat(4,minmax(0,1fr))}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.metric{background:rgba(255,255,255,.035);border:1px solid var(--border);border-radius:14px;padding:12px}.label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}.value{font-size:23px;font-weight:800;margin-top:5px}.green{color:var(--green)}.red{color:var(--red)}.yellow{color:var(--yellow)}.purple{color:var(--purple)}.muted{color:var(--muted)}
  .strategy-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px}.inst-card{position:relative;background:linear-gradient(180deg,rgba(53,194,255,.08),rgba(255,255,255,.03));border:1px solid var(--border);border-radius:16px;padding:14px;cursor:pointer;transition:.18s}.inst-card:hover,.inst-card.selected{border-color:var(--accent);transform:translateY(-1px)}.inst-name{font-weight:800;color:var(--accent);font-size:16px}.inst-meta{font-size:12px;color:var(--muted);margin:3px 0 8px}.pill{display:inline-flex;align-items:center;border:1px solid var(--border);border-radius:999px;padding:3px 8px;font-size:11px;color:var(--muted);margin:2px}.inst-pnl{font-size:24px;font-weight:900;margin:8px 0}.mini-row{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--muted);border-top:1px solid rgba(255,255,255,.06);padding-top:7px;margin-top:7px}.detail-panel{display:none}.detail-head{display:flex;justify-content:space-between;gap:10px;align-items:center}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.tab{padding:7px 10px;border:1px solid var(--border);border-radius:999px;background:transparent;color:var(--muted);cursor:pointer}.tab.active{border-color:var(--accent);color:var(--text);background:rgba(53,194,255,.10)}
  .table-wrap{overflow:auto;border:1px solid var(--border);border-radius:12px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid rgba(255,255,255,.07);white-space:nowrap}th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.4px;background:rgba(255,255,255,.03);position:sticky;top:0}tr:hover{background:rgba(53,194,255,.05)}.compare-best{background:rgba(63,185,80,.08)}.compare-worst{background:rgba(255,107,107,.08)}
  .filters,.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.filters label{font-size:12px;color:var(--muted)}input,select{background:#0b1018;border:1px solid var(--border);border-radius:10px;color:var(--text);padding:8px 10px}.form-grid,.config-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.form-grid label,.config-field label{display:block;font-size:12px;color:var(--muted);margin-bottom:4px}.form-grid input,.form-grid select,.config-field input,.config-field select{width:100%}.btn{display:inline-flex;gap:6px;align-items:center;border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,.035);color:var(--text);padding:8px 12px;cursor:pointer}.btn:hover{border-color:var(--accent)}.btn-primary{background:#238636;border-color:#2ea043;color:#fff}.btn-accent{background:#1f6feb;border-color:#58a6ff;color:#fff}.btn-danger{background:#da3633;border-color:#f85149;color:#fff}.btn:disabled{opacity:.55;cursor:not-allowed}.chart-container{position:relative;width:100%;height:330px}.chart-container canvas{width:100%!important;max-height:330px}.loading{display:flex;align-items:center;gap:8px;color:var(--muted);padding:16px}.spinner{width:18px;height:18px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.error-msg,.success-msg{position:fixed;right:16px;top:64px;z-index:80;max-width:520px;border-radius:12px;padding:12px 14px;display:none}.error-msg{background:rgba(255,107,107,.14);border:1px solid var(--red);color:#ffd1d1}.success-msg{background:rgba(63,185,80,.14);border:1px solid var(--green);color:#c8f7d0}.ops-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.ops-card{background:rgba(255,255,255,.035);border:1px solid var(--border);border-radius:14px;padding:14px;cursor:pointer}.ops-card:hover{border-color:var(--accent)}.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:90;justify-content:center;align-items:center}.modal-box{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:18px;width:92%;max-width:720px;max-height:88vh;overflow:auto}.pagination{display:flex;justify-content:center;gap:8px;align-items:center;margin-top:12px}.grid-viz{padding:8px 0}.grid-row{display:flex;gap:10px;align-items:center;border-bottom:1px solid rgba(255,255,255,.07);padding:5px}.grid-dot{width:12px;height:12px;border-radius:50%;background:var(--green)}.grid-dot.bought{background:var(--yellow)}.grid-dot.completed{background:var(--muted)}
  @media(max-width:900px){.hero,.grid-2,.grid-3,.grid-4{grid-template-columns:1fr}.wrap{padding:12px}.value{font-size:20px}.chart-container{height:280px}}
"""

HTML_TEMPLATE = Template("""
<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OKX Paper Bot Strategy Cockpit</title><style>$css</style><script src="/static/js/chart.js"></script><script src="/static/js/lightweight-charts.js"></script></head><body>
<nav class="topbar"><div class="brand">🤖 OKX Paper Bot<small>OctoBot-style bot control center</small></div><a href="#overview" class="active" data-nav>总览</a><a href="#strategies" data-nav>策略看板</a><a href="#compare" data-nav>策略对比</a><a href="#backtest" data-nav>回测实验室</a><a href="#trades" data-nav>交易</a><a href="#market" data-nav>行情</a><a href="#ops" data-nav>操作</a><a href="#settings" data-nav>设置</a></nav>
<div class="error-msg" id="errorBox"></div><div class="success-msg" id="successBox"></div><main class="wrap">
<section class="hero" id="overview"><div class="card"><h2 class="section-title">📊 账户总览</h2><p class="sub">统一账户、独立策略实例、实时运行状态集中展示。</p><div class="metrics"><div class="metric"><div class="label">余额 USDT</div><div class="value" id="vBalance">--</div></div><div class="metric"><div class="label">持仓价值</div><div class="value" id="vPosValue">--</div></div><div class="metric"><div class="label">账户总值</div><div class="value" id="vEquity">--</div></div><div class="metric"><div class="label">总收益</div><div class="value" id="vReturn">--</div></div><div class="metric"><div class="label">策略实例</div><div class="value" id="vStratCount">--</div></div><div class="metric"><div class="label">总交易</div><div class="value" id="vTrades">--</div></div></div></div><div class="card"><h2 class="section-title">🤖 运行状态</h2><div id="botStatusArea"><div class="loading"><div class="spinner"></div>检查中...</div></div><h2 class="section-title" style="margin-top:12px">📦 持仓明细</h2><div id="positionsArea"><div class="loading"><div class="spinner"></div>加载中...</div></div></div></section>
<section class="section" id="strategies"><h2 class="section-title">🎯 每个策略的独立看板</h2><p class="sub">每张卡片就是一个策略实例；点击后查看该策略的权益、持仓、交易、参数和快捷回测。</p><div class="strategy-grid" id="instCardsArea"><div class="loading"><div class="spinner"></div>加载中...</div></div><div class="actions" style="margin-top:12px"><button class="btn btn-primary" onclick="addInstance()">➕ 新增实例</button><button class="btn" onclick="loadAll()">🔄 刷新全部</button> <button class="btn btn-danger" onclick="resetAllStrategies()">🗑️ 重置全部策略</button></div><div class="detail-panel card" id="instDetailPanel" style="margin-top:14px"><div class="detail-head"><div><h2 class="section-title" id="detailName">--</h2><div class="sub" id="detailSub">--</div></div><button class="btn" onclick="closeDetail()">✕ 关闭</button></div><div class="metrics" id="detailMetrics"></div><div class="tabs"><button class="tab active" data-detail-tab="equity">权益曲线</button><button class="tab" data-detail-tab="trades">交易明细</button><button class="tab" data-detail-tab="positions">持仓/参数</button></div><div id="detailTabEquity"><div class="chart-container"><canvas id="detailEquityChart"></canvas></div><div class="loading" id="detailEqLoading"><div class="spinner"></div>加载中...</div></div><div id="detailTabTrades" style="display:none"><div id="detailTradesArea"></div></div><div id="detailTabPositions" style="display:none"><div class="grid grid-2"><div class="card"><h3 class="section-title" style="font-size:15px">当前持仓</h3><div id="detailPositionsArea"></div></div><div class="card"><h3 class="section-title" style="font-size:15px">策略参数</h3><div id="detailConfigArea"></div></div></div></div></div></section>
<section class="section grid grid-2" id="compare"><div class="card"><h2 class="section-title">⚖️ 实盘策略对比看板</h2><p class="sub">按照实例独立统计交易数、胜率、盈亏比、PnL、权益和回撤。</p><div id="compareArea"><div class="loading"><div class="spinner"></div>加载中...</div></div></div><div class="card"><h2 class="section-title">📊 PnL / 胜率 / 回撤</h2><div class="chart-container"><canvas id="compareChart"></canvas></div></div></section>
<section class="section" id="backtest"><div class="card"><h2 class="section-title">🧪 回测实验室</h2><p class="sub">参考 OctoBot 的模块化机器人控制台：单策略回测、策略类型对比、已配置实例批量对比；尽量复用同一组K线，减少重复请求。</p><form id="btForm" onsubmit="runBacktest(event)"><div class="filters"><label>实例参数</label><select id="btInstance"><option value="">手动参数</option></select><button class="btn" type="button" onclick="loadBtFromInstance()">📌 载入实例</button><button class="btn btn-accent" type="button" onclick="runCompareBacktest()">⚔️ 策略类型对比</button><button class="btn btn-primary" type="button" onclick="runInstanceBacktestCompare()">🧬 已配置实例对比</button></div><div class="form-grid" style="margin-top:12px"><div><label>交易对</label><input id="btSymbol" value="$default_symbol"></div><div><label>策略</label><select id="btStrategy"><option value="ma_crossover">MA交叉</option><option value="rsi">RSI</option><option value="bollinger">布林带</option><option value="macd">MACD</option></select></div><div><label>时间框架</label><input id="btTF" value="$default_tf"></div><div><label>天数</label><input id="btDays" type="number" value="30"></div><div><label>快线</label><input id="btFast" type="number" value="$default_fast"></div><div><label>慢线</label><input id="btSlow" type="number" value="$default_slow"></div><div><label>RSI周期</label><input id="btRsiP" type="number" value="14"></div><div><label>RSI买/卖阈值</label><input id="btRsiBS" value="30,70"></div><div><label>布林周期</label><input id="btBollP" type="number" value="20"></div><div><label>布林标准差</label><input id="btBollS" type="number" step="0.1" value="2.0"></div></div><div class="actions" style="margin-top:12px"><button class="btn btn-primary" type="submit" id="btRun">🚀 运行单策略回测</button></div></form><div id="btResult" style="display:none;margin-top:16px"><div class="metrics" id="btMetrics"></div><div class="chart-container"><canvas id="btChart"></canvas></div><div id="btTradesTable"></div></div><div id="btCompareResult" style="display:none;margin-top:16px"><h3 class="section-title" style="font-size:15px">⚔️ 回测对比结果</h3><div id="btCompareTable"></div><div class="chart-container"><canvas id="btCompareChart"></canvas></div></div></div></section>
<section class="section" id="trades"><div class="card"><h2 class="section-title">📋 交易流水</h2><div class="filters"><label>实例</label><select id="fInstance" onchange="fetchTrades(1)"><option value="">全部实例</option></select><label>交易对</label><select id="fSymbol" onchange="fetchTrades(1)"><option value="">全部</option></select><label>方向</label><select id="fSide" onchange="fetchTrades(1)"><option value="">全部</option><option value="buy">买入</option><option value="sell">卖出</option><option value="stop_loss">止损</option><option value="take_profit">止盈</option><option value="trailing_stop">追踪止损</option><option value="partial_tp">部分止盈</option></select></div><div id="tradesTable" style="margin-top:12px"></div><div class="pagination" id="tradesPagination"></div></div></section>
<section class="section grid grid-2" id="market"><div class="card"><h2 class="section-title">📈 K线图</h2><div class="filters"><label>交易对</label><select id="kSymbol" onchange="loadKlines()"><option value="BTC/USDT">BTC/USDT</option><option value="ETH/USDT">ETH/USDT</option></select><label>周期</label><select id="kTF" onchange="loadKlines()"><option value="1m">1m</option><option value="5m">5m</option><option value="15m">15m</option><option value="1h" selected>1h</option><option value="4h">4h</option><option value="1d">1d</option></select><label>天数</label><select id="kDays" onchange="loadKlines()"><option value="1">1天</option><option value="3">3天</option><option value="7" selected>7天</option><option value="14">14天</option><option value="30">30天</option></select><button class="btn" onclick="loadKlines()">🔄</button></div><div id="klineChart" style="width:100%;height:420px;margin-top:8px"></div><div class="loading" id="klineLoading"><div class="spinner"></div>加载中...</div><div id="klineInfo" class="sub"></div></div><div class="card"><h2 class="section-title">🔲 网格策略</h2><div id="gridArea"><div class="loading"><div class="spinner"></div>加载中...</div></div></div></section>
<section class="section" id="ops"><div class="card"><h2 class="section-title">🎮 操作中心</h2><div class="ops-grid"><div class="ops-card" onclick="opsRunOnce()">⚡<b> 运行一次</b><div class="sub">CLI once</div></div><div class="ops-card" onclick="opsStartBot()">▶️<b> 启动机器人</b></div><div class="ops-card" onclick="opsRestartBot()">🔄<b> 重启机器人</b></div><div class="ops-card" onclick="opsStopBot()">⛔<b> 停止机器人</b></div><div class="ops-card" onclick="opsViewStats()">📊<b> 查看统计</b></div><div class="ops-card" onclick="opsRefreshAll()">🔃<b> 刷新全部</b></div></div><pre id="opsOutput" style="background:#0b1018;border:1px solid var(--border);border-radius:12px;padding:12px;max-height:360px;overflow:auto;white-space:pre-wrap;margin-top:12px">等待操作...</pre></div></section>
<section class="section" id="settings"><div class="card"><h2 class="section-title">⚙️ 设置</h2><div id="settingsForm"><div class="loading"><div class="spinner"></div>加载中...</div></div><div class="actions" style="margin-top:12px"><button class="btn btn-primary" id="saveConfigBtn" onclick="saveConfig()" disabled>💾 保存设置</button> <button class="btn btn-danger" onclick="resetSettings()">🔄 重置设置</button><span id="saveStatus" class="sub"></span></div></div></section>
<div class="modal" id="instanceModal"><div class="modal-box"><div class="detail-head"><h3 id="modalTitle">编辑策略实例</h3><button class="btn" onclick="closeModal()">✕</button></div><div class="form-grid"><div><label>实例名称</label><input id="iName"></div><div><label>策略</label><select id="iStrategy"><option value="ma_crossover">MA交叉</option><option value="rsi">RSI</option><option value="bollinger">布林带</option><option value="macd">MACD</option></select></div><div><label>交易对</label><input id="iSymbols"></div><div><label>时间框架</label><select id="iTF"><option value="1m">1m</option><option value="5m">5m</option><option value="15m">15m</option><option value="1h">1h</option><option value="4h">4h</option><option value="1d">1d</option></select></div><div><label>快线</label><input id="iFast" type="number"></div><div><label>慢线</label><input id="iSlow" type="number"></div><div><label>RSI周期</label><input id="iRsiP" type="number"></div><div><label>RSI买入</label><input id="iRsiB" type="number" step="0.1"></div><div><label>RSI卖出</label><input id="iRsiS" type="number" step="0.1"></div><div><label>布林周期</label><input id="iBollP" type="number"></div><div><label>布林标准差</label><input id="iBollS" type="number" step="0.1"></div><div><label>每单金额</label><input id="iOrder" type="number"></div><div><label>分配权益(USDT)</label><input id="iEquity" type="number" step="100" placeholder="0=使用全局余额"></div><div><label>止损%</label><input id="iSL" type="number" step="0.01"></div><div><label>止盈%</label><input id="iTP" type="number" step="0.01"></div><div><label>追踪止损%</label><input id="iTrail" type="number" step="0.01"></div><div><label>TP1%</label><input id="iTP1" type="number" step="0.01"></div><div><label>TP1比例</label><input id="iTP1f" type="number" step="0.1"></div><div><label>TP2%</label><input id="iTP2" type="number" step="0.01"></div><div><label>TP2比例</label><input id="iTP2f" type="number" step="0.1"></div></div><input type="hidden" id="iIdx" value="-1"><div class="actions" style="justify-content:flex-end;margin-top:16px"><button class="btn" onclick="closeModal()">取消</button><button class="btn btn-primary" onclick="saveInstance()">保存</button></div></div></div>
<footer style="text-align:center;color:var(--muted);font-size:12px;padding:20px">OKX Paper Trading Bot Dashboard v5 · <span id="sseStatus">连接中...</span></footer></main><script src="/static/js/dashboard.js?v=1779111804"></script></body></html>
""")


def _reconstruct_account(config, trades):
    balance = config.initial_balance_usdt
    positions = {}
    for t in trades:
        if t["side"] == "buy":
            balance -= t["amount"] * t["price"]
            positions[t["symbol"]] = positions.get(t["symbol"], 0) + t["amount"]
        elif t["side"] in ("sell", "stop_loss", "take_profit", "trailing_stop", "partial_tp"):
            balance += t["amount"] * t["price"]
            positions[t["symbol"]] = positions.get(t["symbol"], 0) - t["amount"]
            if positions.get(t["symbol"], 0) <= 1e-12:
                positions.pop(t["symbol"], None)
    prices = {}
    for t in reversed(trades):
        if t["symbol"] not in prices:
            prices[t["symbol"]] = t["price"]
    return balance, positions, prices


def _build_dashboard(config):
    return HTML_TEMPLATE.safe_substitute(css=CSS, default_symbol=config.symbol, default_tf=config.timeframe, default_fast=config.fast_window, default_slow=config.slow_window)


def _get_equity_file(config):
    env_path = os.getenv("EQUITY_HISTORY_FILE")
    if env_path: return Path(env_path)
    return config.db_path.parent / "equity_history.json"


def _get_grid_state_file(config):
    env_path = os.getenv("GRID_STATE_FILE")
    if env_path: return Path(env_path)
    return config.db_path.parent / "grid_state.json"


EXIT_SIDES = {"sell", "stop_loss", "take_profit", "trailing_stop", "partial_tp"}


def _trade_instance_name(trade: dict, instances=None) -> str:
    """Return the canonical instance name for a trade.

    New trades store instance_name directly. Old rows are backfilled by matching
    symbol to configured instances so legacy data still appears in per-strategy
    dashboards.
    """
    name = (trade.get("instance_name") or "").strip()
    if name:
        return name
    if instances:
        matches = [i.name for i in instances if trade.get("symbol") in i.symbols]
        if len(matches) == 1:
            return matches[0]
    return "legacy"


def _trade_strategy_name(trade: dict, instances=None) -> str:
    strategy = (trade.get("strategy_name") or "").strip()
    if strategy:
        return strategy
    inst_name = _trade_instance_name(trade, instances)
    if instances:
        inst = next((i for i in instances if i.name == inst_name), None)
        if inst:
            return inst.strategy
    return ""


def _compute_pnl_map(trades):
    """FIFO realized PnL per row, isolated by (instance, symbol)."""
    instances = load_strategy_instances()
    open_positions = {}
    pnl_map = {}
    for i, t in enumerate(trades):
        inst = _trade_instance_name(t, instances)
        key = (inst, t["symbol"])
        side = t.get("side", "")
        if side == "buy":
            open_positions.setdefault(key, []).append([t["amount"], t["price"]])
            pnl_map[i] = None
        else:
            pnl = 0.0
            remaining = t["amount"]
            sell_price = t["price"]
            while remaining > 1e-12 and open_positions.get(key):
                buy_amt, buy_price = open_positions[key][0]
                matched = min(remaining, buy_amt)
                pnl += matched * (sell_price - buy_price)
                remaining -= matched
                if matched >= buy_amt - 1e-12:
                    open_positions[key].pop(0)
                else:
                    open_positions[key][0] = [buy_amt - matched, buy_price]
            pnl_map[i] = pnl
    return pnl_map


def _decorate_trades(trades: list[dict]) -> list[dict]:
    instances = load_strategy_instances()
    pnl_map = _compute_pnl_map(trades)
    out = []
    for i, t in enumerate(trades):
        row = dict(t)
        row["instance_name"] = _trade_instance_name(row, instances)
        row["strategy_name"] = _trade_strategy_name(row, instances)
        row["pnl"] = pnl_map.get(i)
        try:
            row["ts_text"] = datetime.fromtimestamp(float(row.get("ts", 0)), tz=BJT).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            row["ts_text"] = str(row.get("ts", ""))
        out.append(row)
    return out


def _stats_from_decorated(trades: list[dict]) -> dict:
    pnl_list = [float(t["pnl"]) for t in trades if t.get("pnl") is not None]
    exits = [t for t in trades if t.get("pnl") is not None]
    total_trades = len(pnl_list)
    winning = [p for p in pnl_list if p > 0]
    losing = [p for p in pnl_list if p <= 0]
    gross_profit = sum(winning)
    gross_loss = abs(sum(losing))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    total_pnl = sum(pnl_list)
    avg_pnl = total_pnl / total_trades if total_trades else 0.0
    best = max(pnl_list) if pnl_list else 0.0
    worst = min(pnl_list) if pnl_list else 0.0
    buys = sum(1 for t in trades if t.get("side") == "buy")
    sells = sum(1 for t in trades if t.get("side") != "buy")
    return {
        "total_trades": total_trades,
        "raw_trades": len(trades),
        "buy_count": buys,
        "sell_count": sells,
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "win_rate": round(len(winning) / total_trades, 4) if total_trades else 0.0,
        "avg_win": round(sum(winning) / len(winning), 2) if winning else 0.0,
        "avg_loss": round(sum(losing) / len(losing), 2) if losing else 0.0,
        "avg_pnl": round(avg_pnl, 2),
        "best_trade": round(best, 2),
        "worst_trade": round(worst, 2),
        "profit_factor": round(profit_factor, 2),
        "total_pnl": round(total_pnl, 2),
    }


def _positions_from_trades(trades: list[dict]) -> tuple[float, dict[str, float], dict[str, float]]:
    balance_delta = 0.0
    positions: dict[str, float] = {}
    prices: dict[str, float] = {}
    for t in trades:
        sym = t["symbol"]; amount = float(t["amount"]); price = float(t["price"])
        prices[sym] = price
        if t.get("side") == "buy":
            balance_delta -= amount * price
            positions[sym] = positions.get(sym, 0.0) + amount
        else:
            balance_delta += amount * price
            positions[sym] = positions.get(sym, 0.0) - amount
    positions = {s: a for s, a in positions.items() if a > 1e-12}
    return balance_delta, positions, prices


def _equity_from_trades(config, trades: list[dict]) -> dict:
    decorated = _decorate_trades(trades)
    balance = config.initial_balance_usdt
    positions: dict[str, float] = {}
    prices: dict[str, float] = {}
    history = []
    for t in decorated:
        sym = t["symbol"]; amount = float(t["amount"]); price = float(t["price"])
        prices[sym] = price
        if t.get("side") == "buy":
            balance -= amount * price
            positions[sym] = positions.get(sym, 0.0) + amount
        else:
            balance += amount * price
            positions[sym] = positions.get(sym, 0.0) - amount
        positions = {s: a for s, a in positions.items() if a > 1e-12}
        pos_value = sum(a * prices.get(s, 0.0) for s, a in positions.items())
        total = balance + pos_value
        history.append({"timestamp": t.get("ts_text", t.get("ts", "")), "balance_usdt": round(balance, 2), "positions_value": round(pos_value, 2), "total_equity": round(total, 2), "pnl": round(total - config.initial_balance_usdt, 2), "pnl_pct": round((total - config.initial_balance_usdt) / config.initial_balance_usdt * 100, 4)})
    equities = [h["total_equity"] for h in history]
    peak = equities[0] if equities else config.initial_balance_usdt
    max_dd = 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)
    return {"history": history, "sharpe": 0.0, "max_drawdown": round(max_dd, 4)}


def _build_api_status(config):
    store = TradeStore(config.db_path)
    trades = store.list_trades()
    equity_file = _get_equity_file(config)
    instances = load_strategy_instances()
    if equity_file.exists():
        try:
            eq_data = json.loads(equity_file.read_text())
            history = eq_data if isinstance(eq_data, list) else []
            if history:
                latest = history[-1]
                balance = latest.get("balance_usdt", config.initial_balance_usdt)
                pos_value = latest.get("positions_value", 0.0)
                total = latest.get("total_equity", balance + pos_value)
                ret_pct = (total - config.initial_balance_usdt) / config.initial_balance_usdt * 100
                prices = {}
                for t in reversed(trades):
                    if t["symbol"] not in prices: prices[t["symbol"]] = t["price"]
                pos_list = []
                if pos_value > 0 and prices:
                    net_positions = {}
                    for t in trades:
                        sym = t["symbol"]
                        if t["side"] == "buy": net_positions[sym] = net_positions.get(sym, 0) + t["amount"]
                        else: net_positions[sym] = net_positions.get(sym, 0) - t["amount"]
                    total_recon = sum(net_positions.get(s, 0) * prices.get(s, 0) for s in net_positions)
                    scale = pos_value / total_recon if total_recon > 0 else 0
                    for sym, amt in net_positions.items():
                        if amt > 1e-12:
                            scaled = amt * scale if scale < 1 else amt
                            pos_list.append({"symbol": sym, "amount": round(scaled, 8), "price": prices.get(sym, 0), "value": round(scaled * prices.get(sym, 0), 2)})
                return {"time": datetime.now(BJT).isoformat(), "balance": round(balance, 2), "positions_value": round(pos_value, 2), "total_equity": round(total, 2), "return_pct": round(ret_pct, 2), "initial_balance": config.initial_balance_usdt, "strategy": config.strategy_name, "positions": pos_list, "trades_count": len(trades), "instance_count": len(instances)}
        except (json.JSONDecodeError, KeyError, IndexError): pass
    balance, positions, prices = _reconstruct_account(config, trades)
    pos_value = sum(amount * prices.get(sym, 0) for sym, amount in positions.items())
    total = balance + pos_value
    ret_pct = (total - config.initial_balance_usdt) / config.initial_balance_usdt * 100
    pos_list = [{"symbol": sym, "amount": amount, "price": prices.get(sym, 0), "value": round(amount * prices.get(sym, 0), 2)} for sym, amount in positions.items()]
    return {"time": datetime.now(BJT).isoformat(), "balance": round(balance, 2), "positions_value": round(pos_value, 2), "total_equity": round(total, 2), "return_pct": round(ret_pct, 2), "initial_balance": config.initial_balance_usdt, "strategy": config.strategy_name, "positions": pos_list, "trades_count": len(trades), "instance_count": len(instances)}


def _build_api_trades(config, symbol=None, side=None, symbols_multi=None, instance=None, strategy=None, page=1, per_page=20):
    store = TradeStore(config.db_path)
    all_trades = _decorate_trades(store.list_trades())
    filtered = all_trades
    if symbol: filtered = [t for t in filtered if t["symbol"] == symbol]
    elif symbols_multi:
        sym_set = set(s.strip() for s in symbols_multi.split(",") if s.strip())
        filtered = [t for t in filtered if t["symbol"] in sym_set]
    if instance: filtered = [t for t in filtered if t.get("instance_name") == instance]
    if strategy: filtered = [t for t in filtered if t.get("strategy_name") == strategy]
    if side: filtered = [t for t in filtered if t["side"] == side]
    total = len(filtered)
    total_pages = math.ceil(total / per_page) if total > 0 else 0
    page = max(1, min(page, max(total_pages, 1)))
    start = (page - 1) * per_page
    page_rows = list(reversed(filtered))[start:start + per_page]
    return {"trades": page_rows, "total": total, "page": page, "pages": total_pages}


def _build_api_equity(equity_file, symbols_multi=None, store=None):
    equity_file = Path(equity_file)
    if symbols_multi:
        sym_set = set(s.strip() for s in symbols_multi.split(",") if s.strip())
        if store is None: store = TradeStore(Path("data/trades.sqlite3"))
        trades = [t for t in store.list_trades() if t["symbol"] in sym_set]
        if not trades: return {"history": [], "sharpe": 0.0, "max_drawdown": 0.0}
        open_positions = {}
        cum_pnl = 0.0
        points = []
        for t in trades:
            sym = t["symbol"]
            if t["side"] == "buy": open_positions.setdefault(sym, []).append([t["amount"], t["price"]])
            else:
                remaining = t["amount"]
                sell_price = t["price"]
                while remaining > 1e-12 and open_positions.get(sym):
                    buy_amt, buy_price = open_positions[sym][0]
                    matched = min(remaining, buy_amt)
                    cum_pnl += matched * (sell_price - buy_price)
                    remaining -= matched
                    if matched >= buy_amt - 1e-12: open_positions[sym].pop(0)
                    else: open_positions[sym][0] = [buy_amt - matched, buy_price]
            points.append({"timestamp": t.get("ts", ""), "total_equity": round(cum_pnl, 2)})
        equities = [p["total_equity"] for p in points]
        max_dd = 0.0; peak = 0.0
        for e in equities:
            if e > peak: peak = e
            dd = peak - e
            if dd > max_dd: max_dd = dd
        initial = 10000.0
        history = [{"timestamp": p["timestamp"], "total_equity": round(initial + p["total_equity"], 2), "balance_usdt": round(initial + p["total_equity"], 2), "positions_value": 0, "pnl": p["total_equity"], "pnl_pct": round(p["total_equity"] / initial * 100, 4)} for p in points]
        max_dd_pct = max_dd / initial * 100 if initial > 0 else 0
        return {"history": history, "sharpe": 0.0, "max_drawdown": round(max_dd_pct, 4)}
    if not equity_file.exists(): return {"history": [], "sharpe": 0.0, "max_drawdown": 0.0}
    tracker = EquityTracker(equity_file)
    history = [{"timestamp": s.timestamp, "balance_usdt": s.balance_usdt, "positions_value": s.positions_value, "total_equity": s.total_equity, "pnl": s.pnl, "pnl_pct": s.pnl_pct} for s in tracker.history]
    return {"history": history, "sharpe": tracker.sharpe_ratio(), "max_drawdown": tracker.max_drawdown()}


def _build_api_stats(config, symbols_multi=None, instance=None, strategy=None):
    store = TradeStore(config.db_path)
    trades = _decorate_trades(store.list_trades())
    if symbols_multi:
        sym_set = set(s.strip() for s in symbols_multi.split(",") if s.strip())
        trades = [t for t in trades if t["symbol"] in sym_set]
    if instance:
        trades = [t for t in trades if t.get("instance_name") == instance]
    if strategy:
        trades = [t for t in trades if t.get("strategy_name") == strategy]
    return _stats_from_decorated(trades)


def _build_api_config(config):
    # 只返回通用参数，策略特定参数由 strategies.json 中的实例管理
    return {
        "symbols": config.all_symbols, "demo": config.okx_demo,
        "initial_balance": config.initial_balance_usdt,
        "order_usdt": config.order_usdt, "max_position_fraction": config.max_position_fraction,
        "fee_pct": config.fee_pct, "slippage_pct": config.slippage_pct,
        "loop_interval_seconds": config.loop_interval_seconds,
        # OKX API (masked for security)
        "okx_api_key": config.api_key or "",
        "okx_api_secret": "***" if config.secret else "",
        "okx_api_password": "***" if config.password else "",
        "okx_demo": config.okx_demo,
    }


def _build_backtest_result_json(result):
    equity_curve = [result.initial_balance]
    for t in result.trades: equity_curve.append(equity_curve[-1] + t.pnl)
    trades_list = [{"entry_time": t.entry_time, "entry_price": t.entry_price, "exit_time": t.exit_time, "exit_price": t.exit_price, "amount": t.amount, "side": t.side, "pnl": round(t.pnl, 2), "pnl_pct": round(t.pnl_pct, 4), "exit_reason": t.exit_reason} for t in result.trades]
    return {"symbol": result.symbol, "timeframe": result.timeframe, "start_time": result.start_time, "end_time": result.end_time, "initial_balance": result.initial_balance, "final_balance": round(result.final_balance, 2), "total_return": round(result.total_return, 4), "total_trades": result.total_trades, "winning_trades": result.winning_trades, "losing_trades": result.losing_trades, "win_rate": round(result.win_rate, 4), "avg_win": round(result.avg_win, 2), "avg_loss": round(result.avg_loss, 2), "profit_factor": round(result.profit_factor, 2), "max_drawdown": round(result.max_drawdown, 4), "trades": trades_list, "equity_curve": [round(e, 2) for e in equity_curve]}


def _normalize_grid_payload(data, enabled):
    cfg = data.get("config", {}) or {}
    lower = float(cfg.get("lower_price", 70000)); upper = float(cfg.get("upper_price", 90000)); grid_count = int(cfg.get("grid_count", 10))
    levels = [{"price": float(l["price"]), "buy_filled": bool(l.get("buy_filled", False)), "sell_filled": bool(l.get("sell_filled", False))} for l in data.get("levels", [])]
    bought_pending = sum(1 for l in levels if l["buy_filled"] and not l["sell_filled"]); available = sum(1 for l in levels if not l["buy_filled"])
    return {"enabled": enabled, "symbol": cfg.get("symbol", "BTC/USDT"), "lower_price": lower, "upper_price": upper, "grid_count": grid_count, "grid_step": round((upper - lower) / grid_count, 2) if grid_count else 0.0, "order_usdt": float(cfg.get("order_usdt", 500)), "levels": levels, "total_profit": float(data.get("total_profit", 0.0)), "completed_grids": int(data.get("completed_grids", 0)), "bought_pending": bought_pending, "available": available}


def _build_api_grid(config):
    from okx_paper_bot.grid import GridConfig
    grid_file = _get_grid_state_file(config)
    if not grid_file.exists():
        gc = GridConfig()
        demo = {"config": {"symbol": gc.symbol, "lower_price": gc.lower_price, "upper_price": gc.upper_price, "grid_count": gc.grid_count, "order_usdt": gc.order_usdt}, "levels": [{"price": p, "buy_filled": False, "sell_filled": False} for p in gc.grid_prices()], "total_profit": 0.0, "completed_grids": 0}
        return _normalize_grid_payload(demo, enabled=False)
    return _normalize_grid_payload(json.loads(grid_file.read_text()), enabled=True)


def _instance_initial_balance(config, inst=None) -> float:
    """Approximate capital allocated to one strategy instance."""
    instances = load_strategy_instances()
    if inst is None or not instances:
        return float(config.initial_balance_usdt)
    return float(config.initial_balance_usdt) / max(len(instances), 1)


def _position_rows_from_trades(trades: list[dict]) -> tuple[float, list[dict]]:
    """Return cash delta and open positions reconstructed from the supplied rows."""
    cash_delta, positions, prices = _positions_from_trades(trades)
    rows = []
    for sym, amount in sorted(positions.items()):
        price = float(prices.get(sym, 0.0))
        rows.append({"symbol": sym, "amount": round(amount, 8), "price": round(price, 6), "value": round(amount * price, 2)})
    return cash_delta, rows


def _equity_history_for_decorated(config, trades: list[dict], initial_balance: float | None = None) -> dict:
    """Build an equity curve from already-filtered decorated trades."""
    initial = float(initial_balance if initial_balance is not None else config.initial_balance_usdt)
    balance = initial
    positions: dict[str, float] = {}
    prices: dict[str, float] = {}
    history = [{"timestamp": "初始", "balance_usdt": round(balance, 2), "positions_value": 0.0, "total_equity": round(initial, 2), "pnl": 0.0, "pnl_pct": 0.0}]
    for t in sorted(trades, key=lambda x: (float(x.get("ts") or 0), int(x.get("id") or 0))):
        sym = t["symbol"]; amount = float(t["amount"]); price = float(t["price"])
        prices[sym] = price
        if t.get("side") == "buy":
            balance -= amount * price
            positions[sym] = positions.get(sym, 0.0) + amount
        else:
            balance += amount * price
            positions[sym] = positions.get(sym, 0.0) - amount
        positions = {s: a for s, a in positions.items() if a > 1e-12}
        pos_value = sum(a * prices.get(s, 0.0) for s, a in positions.items())
        total = balance + pos_value
        history.append({"timestamp": t.get("ts_text", t.get("ts", "")), "balance_usdt": round(balance, 2), "positions_value": round(pos_value, 2), "total_equity": round(total, 2), "pnl": round(total - initial, 2), "pnl_pct": round((total - initial) / initial * 100, 4) if initial else 0.0})
    equities = [h["total_equity"] for h in history]
    peak = equities[0] if equities else initial
    max_dd = 0.0
    for e in equities:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak if peak else 0.0)
    return {"history": history, "sharpe": 0.0, "max_drawdown": round(max_dd, 4)}


def _summarize_scope(config, trades: list[dict], initial_balance: float | None = None) -> dict:
    """Common stats/positions/equity summary for account, strategy, or instance scope."""
    initial = float(initial_balance if initial_balance is not None else config.initial_balance_usdt)
    stats = _stats_from_decorated(trades)
    cash_delta, positions = _position_rows_from_trades(trades)
    pos_value = sum(p["value"] for p in positions)
    balance = initial + cash_delta
    total_equity = balance + pos_value
    equity = _equity_history_for_decorated(config, trades, initial)
    stats.update({
        "balance": round(balance, 2),
        "positions_value": round(pos_value, 2),
        "total_equity": round(total_equity, 2),
        "return_pct": round((total_equity - initial) / initial * 100, 4) if initial else 0.0,
        "initial_balance": round(initial, 2),
        "positions": positions,
        "max_drawdown": equity["max_drawdown"],
    })
    return {"stats": stats, "equity": equity}


def _build_api_instance_stats(config):
    """Return accurate per-instance dashboard rows grouped by canonical instance_name."""
    instances = load_strategy_instances()
    store = TradeStore(config.db_path)
    decorated = _decorate_trades(store.list_trades())
    if not instances:
        summary = _summarize_scope(config, decorated)["stats"]
        summary.update({"name": "default", "strategy": config.strategy_name, "symbols": config.all_symbols, "timeframe": config.timeframe})
        return {"instances": [summary]}
    results = []
    for inst in instances:
        rows = [t for t in decorated if t.get("instance_name") == inst.name]
        summary = _summarize_scope(config, rows, _instance_initial_balance(config, inst))["stats"]
        summary.update({"name": inst.name, "strategy": inst.strategy, "symbols": inst.symbols, "timeframe": inst.timeframe})
        results.append(summary)
    return {"instances": results}


def _build_api_strategy_compare(config):
    store = TradeStore(config.db_path)
    decorated = _decorate_trades(store.list_trades())
    strategies = sorted({t.get("strategy_name") or "unknown" for t in decorated} | {i.strategy for i in load_strategy_instances()})
    results = []
    for strategy in strategies:
        rows = [t for t in decorated if (t.get("strategy_name") or "unknown") == strategy]
        summary = _summarize_scope(config, rows)["stats"]
        summary.update({"strategy": strategy})
        results.append(summary)
    return {"strategies": results}


def _build_api_instance_detail(config, name):
    instances = load_strategy_instances()
    inst = next((i for i in instances if i.name == name), None)
    if not inst:
        return {"error": f"instance not found: {name}"}
    store = TradeStore(config.db_path)
    decorated = _decorate_trades(store.list_trades())
    inst_trades = [t for t in decorated if t.get("instance_name") == inst.name]
    summary = _summarize_scope(config, inst_trades, _instance_initial_balance(config, inst))
    return {
        "config": {"name": inst.name, "strategy": inst.strategy, "symbols": inst.symbols, "timeframe": inst.timeframe, "order_usdt": inst.order_usdt, "stop_loss_pct": inst.stop_loss_pct, "take_profit_pct": inst.take_profit_pct, "trailing_stop_pct": inst.trailing_stop_pct, "fast_window": inst.fast_window, "slow_window": inst.slow_window, "rsi_period": inst.rsi_period, "rsi_buy": inst.rsi_buy, "rsi_sell": inst.rsi_sell, "bollinger_period": inst.bollinger_period, "bollinger_std": inst.bollinger_std},
        "stats": summary["stats"],
        "equity": summary["equity"],
        "positions": summary["stats"].get("positions", []),
        "trades": list(reversed(inst_trades))[:80],
    }


def _build_api_dashboard_v4(config):
    """Single payload for Dashboard v4: account, per-instance, strategy compare."""
    store = TradeStore(config.db_path)
    decorated = _decorate_trades(store.list_trades())
    account = _summarize_scope(config, decorated)
    inst_stats = _build_api_instance_stats(config)["instances"]
    strat_compare = _build_api_strategy_compare(config)["strategies"]
    return {
        "version": "v4",
        "time": datetime.now(BJT).isoformat(),
        "mode": "demo" if config.okx_demo else "live",
        "live": _build_api_bot_status(),
        "account": account,
        "instances": inst_stats,
        "strategies": strat_compare,
        "totals": {"trades_count": len(decorated), "instance_count": len(load_strategy_instances()), "symbols": sorted({t["symbol"] for t in decorated} | set(config.all_symbols))},
    }

def _build_api_bot_status():
    pids = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit(): continue
        try: cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        except OSError: continue
        if "okx_paper_bot.cli" in cmd and " run" in cmd:
            pid = int(proc.name); mem_mb = 0.0; start_time = ""
            try:
                for line in (proc / "status").read_text().splitlines():
                    if line.startswith("VmRSS:"): mem_mb = int(line.split()[1]) / 1024.0; break
            except OSError: pass
            try:
                stat = (proc / "stat").read_text().split()
                start_ticks = int(stat[21]); clk = os.sysconf("SC_CLK_TCK")
                uptime_s = float(Path("/proc/uptime").read_text().split()[0])
                start_time = datetime.fromtimestamp(time.time() - (uptime_s - start_ticks / clk), tz=BJT).strftime("%Y-%m-%d %H:%M")
            except (OSError, IndexError, ValueError): pass
            pids.append({"pid": pid, "memory_mb": round(mem_mb, 1), "start_time": start_time})
    if pids:
        p = pids[0]
        return {"running": True, "pid": p["pid"], "memory_mb": p["memory_mb"], "start_time": p["start_time"]}
    return {"running": False, "pid": None, "memory_mb": 0, "start_time": ""}


def _build_api_klines(config, symbol, timeframe, days):
    try:
        from okx_paper_bot.exchange import create_okx_exchange
        exchange = create_okx_exchange(config)
        since_ms = int((datetime.now(BJT) - timedelta(days=days)).timestamp() * 1000)
        all_candles = []; fetch_since = since_ms
        tf_ms = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000, "1d": 86400000}
        step = tf_ms.get(timeframe, 3600000); limit = 100
        while True:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since=fetch_since, limit=limit)
            if not candles: break
            all_candles.extend(candles)
            if len(candles) < limit: break
            fetch_since = candles[-1][0] + step
        formatted = [{"time": c[0] // 1000, "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in all_candles]
        store = TradeStore(config.db_path); trades = store.list_trades(); trade_markers = []
        for t in trades:
            if t["symbol"] == symbol:
                ts = t.get("ts", "")
                try: t_ms = float(ts) * 1000 if ts.replace(".", "").isdigit() else 0
                except (ValueError, AttributeError): t_ms = 0
                if t_ms >= since_ms: trade_markers.append({"time": int(float(ts)) if ts.replace(".", "").isdigit() else 0, "side": t["side"], "price": t["price"], "amount": t["amount"]})
        return {"candles": formatted, "trades": trade_markers, "symbol": symbol, "timeframe": timeframe}
    except Exception as e: return {"error": str(e), "candles": [], "trades": []}


def _update_api_config(params):
    """Save config parameters to .env file."""
    env_path = Path(os.getenv("OKX_BOT_ENV_FILE", ".env"))
    key_map = {
        "symbols": "OKX_SYMBOLS", "symbol": "OKX_SYMBOL",
        "initial_balance": "INITIAL_BALANCE_USDT",
        "order_usdt": "ORDER_USDT", "max_position_fraction": "MAX_POSITION_FRACTION",
        "fee_pct": "FEE_PCT", "slippage_pct": "SLIPPAGE_PCT",
        "loop_interval_seconds": "LOOP_INTERVAL_SECONDS",
        "okx_api_key": "OKX_API_KEY", "okx_api_secret": "OKX_API_SECRET",
        "okx_api_password": "OKX_API_PASSWORD", "okx_demo": "OKX_DEMO",
    }
    masked_keys = {'okx_api_secret', 'okx_api_password'}
    # Read .env once
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    existing = {}
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1); existing[k.strip()] = v.strip()
    # Update from params
    for api_key, val in params.items():
        env_key = key_map.get(api_key)
        if not env_key: continue
        if api_key in masked_keys and val in ('***', '****', ''):
            continue  # skip masked/empty secrets
        str_val = str(val)
        existing[env_key] = str_val
    # Rebuild .env from original lines, updating values
    out_lines = []
    written_keys = set()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            k = stripped.split('=', 1)[0].strip()
            if k in existing:
                out_lines.append(f'{k}={existing[k]}')
                written_keys.add(k)
            else:
                out_lines.append(line)
        else:
            out_lines.append(line)
    for k, v in existing.items():
        if k not in written_keys:
            out_lines.append(f'{k}={v}')
    env_path.write_text(chr(10).join(out_lines) + chr(10))
    # Update process env
    for k, v in existing.items():
        os.environ[k] = v
    result = dict(params)
    if 'symbols' in result and isinstance(result['symbols'], str):
        result['symbols'] = [s.strip() for s in result['symbols'].split(',') if s.strip()]
    return result

def _find_bot_pids():
    pids = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit(): continue
        try: cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        except OSError: continue
        if "okx_paper_bot.cli" in cmd and " run" in cmd: pids.append(int(proc.name))
    return pids


def _systemctl_bot(action):
    if action not in ("restart", "stop"): return False
    try: result = subprocess.run(["systemctl", action, "okx-bot.service"], capture_output=True, text=True, timeout=10, check=False)
    except (FileNotFoundError, subprocess.SubprocessError, OSError): return False
    return result.returncode == 0


def _reset_settings(config):
    """Reset all settings to defaults."""
    env_path = Path(os.getenv("OKX_BOT_ENV_FILE", ".env"))
    # Default values
    defaults = {
        "OKX_SYMBOLS": "BTC/USDT,ETH/USDT",
        "INITIAL_BALANCE_USDT": "10000",
        "ORDER_USDT": "500",
        "MAX_POSITION_FRACTION": "0.25",
        "FEE_PCT": "0.001",
        "SLIPPAGE_PCT": "0.0005",
        "STOP_LOSS_PCT": "0.05",
        "TAKE_PROFIT_PCT": "0.10",
        "TRAILING_STOP_PCT": "0.0",
        "TP1_PCT": "0.0",
        "TP1_FRACTION": "0.5",
        "TP2_PCT": "0.0",
        "TP2_FRACTION": "1.0",
        "LOOP_INTERVAL_SECONDS": "60",
        "OKX_DEMO": "true",
    }
    # Read existing env to preserve API keys
    existing = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    # Update with defaults, but keep API keys
    for k, v in defaults.items():
        existing[k] = v
    # Write back
    lines = [f"{k}={v}" for k, v in existing.items()]
    env_path.write_text("\n".join(lines) + "\n")
    return {"status": "ok", "message": "设置已重置为默认值"}


def _reset_strategy(instance_name, config):
    """Reset strategy account state and optionally trades."""
    data_dir = Path(config.db_path).parent
    results = []
    
    # Delete account state files
    if instance_name:
        # Reset specific instance
        acct_file = data_dir / f"account_{instance_name}.json"
        if acct_file.exists():
            acct_file.unlink()
            results.append(f"已删除 {instance_name} 账户状态")
        else:
            results.append(f"{instance_name} 无账户状态文件")
    else:
        # Reset all instances
        for f in data_dir.glob("account_*.json"):
            f.unlink()
            results.append(f"已删除 {f.name}")
    
    # Delete trade database
    db_path = config.db_path
    if db_path.exists():
        db_path.unlink()
        results.append("已删除交易记录数据库")
    
    # Delete equity history
    eq_file = data_dir / "equity_history.json"
    if eq_file.exists():
        eq_file.unlink()
        results.append("已删除权益历史")
    
    # Delete notifications log
    notify_file = data_dir / "notifications.log"
    if notify_file.exists():
        notify_file.unlink()
        results.append("已删除通知日志")
    
    return {"status": "ok", "message": "策略已重置", "details": results}


def _build_api_control(action):
    if action not in ("restart", "stop"): return {"error": f"invalid action: {action}"}
    if _systemctl_bot(action): return {"status": "ok", "action": action, "method": "systemctl"}
    pids = _find_bot_pids()
    if not pids: return {"error": "bot process not found"}
    for pid in pids: os.kill(pid, signal.SIGTERM)
    return {"status": "ok", "action": action, "method": "sigterm", "pids": pids}


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        config = BotConfig.from_env()
        parsed = urlparse(self.path); path = parsed.path; qs = parse_qs(parsed.query)
        if path == "/api/status": self._json(_build_api_status(config))
        elif path == "/api/dashboard_v4": self._json(_build_api_dashboard_v4(config))
        elif path == "/api/stream": self._sse(config)
        elif path == "/api/trades": self._json(_build_api_trades(config, symbol=qs.get("symbol", [None])[0], side=qs.get("side", [None])[0], symbols_multi=qs.get("symbols", [None])[0], instance=qs.get("instance", [None])[0], strategy=qs.get("strategy", [None])[0], page=int(qs.get("page", ["1"])[0]), per_page=int(qs.get("per_page", ["20"])[0])))
        elif path == "/api/equity":
            instance = qs.get("instance", [None])[0]
            if instance:
                self._json(_build_api_instance_detail(config, instance).get("equity", {"history": [], "sharpe": 0.0, "max_drawdown": 0.0}))
            else:
                self._json(_build_api_equity(_get_equity_file(config), symbols_multi=qs.get("symbols", [None])[0], store=TradeStore(config.db_path)))
        elif path == "/api/stats": self._json(_build_api_stats(config, symbols_multi=qs.get("symbols", [None])[0], instance=qs.get("instance", [None])[0], strategy=qs.get("strategy", [None])[0]))
        elif path == "/api/config": self._json(_build_api_config(config))
        elif path == "/api/grid": self._json(_build_api_grid(config))
        elif path == "/api/instances":
            insts = load_strategy_instances()
            data = [{"name": i.name, "strategy": i.strategy, "symbols": i.symbols, "timeframe": i.timeframe, "fast_window": i.fast_window, "slow_window": i.slow_window, "rsi_period": i.rsi_period, "rsi_buy": i.rsi_buy, "rsi_sell": i.rsi_sell, "bollinger_period": i.bollinger_period, "bollinger_std": i.bollinger_std, "order_usdt": i.order_usdt, "stop_loss_pct": i.stop_loss_pct, "take_profit_pct": i.take_profit_pct, "trailing_stop_pct": i.trailing_stop_pct, "tp1_pct": i.tp1_pct, "tp1_fraction": i.tp1_fraction, "tp2_pct": i.tp2_pct, "tp2_fraction": i.tp2_fraction} for i in insts]
            self._json({"instances": data})
        elif path == "/api/instances/stats": self._json(_build_api_instance_stats(config))
        elif path == "/api/instance_detail": self._json(_build_api_instance_detail(config, qs.get("name", [None])[0]))
        elif path == "/api/klines": self._json(_build_api_klines(config, qs.get("symbol", ["BTC/USDT"])[0], qs.get("timeframe", ["1h"])[0], int(qs.get("days", ["7"])[0])))
        elif path == "/api/bot_status": self._json(_build_api_bot_status())
        elif path.startswith("/static/"):
            import mimetypes
            static_dir = Path(__file__).resolve().parent.parent.parent / "static"
            file_path = static_dir / path[len("/static/"):]
            if file_path.is_file():
                ct = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
                self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Cache-Control", "public, max-age=86400"); self.end_headers()
                self.wfile.write(file_path.read_bytes())
            else: self.send_response(404); self.end_headers()
        else:
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"); self.end_headers()
            self.wfile.write(_build_dashboard(config).encode())

    def do_POST(self):
        config = BotConfig.from_env()
        parsed = urlparse(self.path); path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len else b""
        params = json.loads(body) if body else {}
        if path == "/api/backtest":
            try:
                from okx_paper_bot.backtester import fetch_historical_candles, run_backtest
                from okx_paper_bot.exchange import create_okx_exchange
                symbol = params.get("symbol", config.symbol); strategy = params.get("strategy", config.strategy_name)
                timeframe = params.get("timeframe", config.timeframe); days = int(params.get("days", 30))
                fast = int(params.get("fast", config.fast_window)); slow = int(params.get("slow", config.slow_window))
                rsi_period = int(params.get("rsi_period", config.rsi_period)); rsi_buy = float(params.get("rsi_buy", config.rsi_buy)); rsi_sell = float(params.get("rsi_sell", config.rsi_sell))
                bollinger_period = int(params.get("bollinger_period", config.bollinger_period)); bollinger_std = float(params.get("bollinger_std", config.bollinger_std))
                bt_config = BotConfig(symbol=symbol, timeframe=timeframe, fast_window=fast, slow_window=slow, rsi_period=rsi_period, rsi_buy=rsi_buy, rsi_sell=rsi_sell, bollinger_period=bollinger_period, bollinger_std=bollinger_std, initial_balance_usdt=config.initial_balance_usdt, order_usdt=config.order_usdt, max_position_fraction=config.max_position_fraction, fee_pct=config.fee_pct, slippage_pct=config.slippage_pct, stop_loss_pct=config.stop_loss_pct, take_profit_pct=config.take_profit_pct, trailing_stop_pct=config.trailing_stop_pct, strategy_name=strategy)
                since_ms = int((datetime.now(BJT) - timedelta(days=days)).timestamp() * 1000)
                exchange = create_okx_exchange(config)
                candles = fetch_historical_candles(exchange, symbol, timeframe, since_ms=since_ms)
                result = run_backtest(candles, bt_config, strategy_name=strategy)
                r = _build_backtest_result_json(result); r["strategy"] = strategy; self._json(r)
            except Exception as e: self._json({"error": str(e)}, 400)
        elif path == "/api/backtest_compare":
            try:
                from okx_paper_bot.backtester import fetch_historical_candles, run_backtest
                from okx_paper_bot.exchange import create_okx_exchange
                symbol = params.get("symbol", config.symbol); timeframe = params.get("timeframe", config.timeframe); days = int(params.get("days", 30))
                since_ms = int((datetime.now(BJT) - timedelta(days=days)).timestamp() * 1000)
                exchange = create_okx_exchange(config)
                candles = fetch_historical_candles(exchange, symbol, timeframe, since_ms=since_ms)
                results = []
                for strat_name in ["ma_crossover", "rsi", "bollinger", "macd"]:
                    bt_config = BotConfig(symbol=symbol, timeframe=timeframe, initial_balance_usdt=config.initial_balance_usdt, order_usdt=config.order_usdt, max_position_fraction=config.max_position_fraction, fee_pct=config.fee_pct, slippage_pct=config.slippage_pct, stop_loss_pct=config.stop_loss_pct, take_profit_pct=config.take_profit_pct, trailing_stop_pct=config.trailing_stop_pct, strategy_name=strat_name)
                    try:
                        result = run_backtest(candles, bt_config, strategy_name=strat_name)
                        r = _build_backtest_result_json(result); r["strategy"] = strat_name; results.append(r)
                    except Exception as e: results.append({"strategy": strat_name, "error": str(e), "total_return": 0, "total_trades": 0, "win_rate": 0, "profit_factor": 0, "max_drawdown": 0, "final_balance": 0, "equity_curve": []})
                self._json({"results": results, "symbol": symbol, "timeframe": timeframe, "days": days})
            except Exception as e: self._json({"error": str(e)}, 400)
        elif path == "/api/instances":
            try:
                raw_list = params.get("instances", []); instances = []
                for item in raw_list: instances.append(StrategyInstance(name=item.get("name", "default"), strategy=item.get("strategy", "ma_crossover"), symbols=item.get("symbols", ["BTC/USDT"]), timeframe=item.get("timeframe", "1h"), fast_window=int(item.get("fast_window", 5)), slow_window=int(item.get("slow_window", 20)), rsi_period=int(item.get("rsi_period", 14)), rsi_buy=float(item.get("rsi_buy", 30)), rsi_sell=float(item.get("rsi_sell", 70)), bollinger_period=int(item.get("bollinger_period", 20)), bollinger_std=float(item.get("bollinger_std", 2.0)), stop_loss_pct=float(item.get("stop_loss_pct", 0.05)), take_profit_pct=float(item.get("take_profit_pct", 0.10)), trailing_stop_pct=float(item.get("trailing_stop_pct", 0)), tp1_pct=float(item.get("tp1_pct", 0)), tp1_fraction=float(item.get("tp1_fraction", 0.5)), tp2_pct=float(item.get("tp2_pct", 0)), tp2_fraction=float(item.get("tp2_fraction", 1.0)), order_usdt=float(item.get("order_usdt", 500))))
                save_strategy_instances(instances); self._json({"status": "ok", "count": len(instances)})
            except Exception as e: self._json({"error": str(e)}, 400)
        elif path == "/api/config":
            try: self._json(_update_api_config(params))
            except Exception as e: self._json({"error": str(e)}, 400)
        elif path == "/api/control":
            # Allow from any client since this is an internal LAN dashboard
            self._json(_build_api_control(params.get("action", "")))
        elif path == "/api/reset":
            try:
                reset_type = params.get("type", "")
                if reset_type == "settings":
                    # Reset settings to defaults
                    self._json(_reset_settings(config))
                elif reset_type == "strategy":
                    # Reset strategy account and trades
                    instance_name = params.get("instance", "")
                    self._json(_reset_strategy(instance_name, config))
                else:
                    self._json({"error": "invalid reset type"}, 400)
            except Exception as e:
                self._json({"error": str(e)}, 500)
        elif path == "/api/run_once":
            try:
                result = subprocess.run(["python", "-m", "okx_paper_bot.cli", "once"], capture_output=True, text=True, timeout=60, cwd=str(Path(__file__).resolve().parent.parent.parent))
                self._json({"status": "ok", "output": result.stdout + result.stderr, "returncode": result.returncode})
            except Exception as e: self._json({"error": str(e)}, 500)
        elif path == "/api/start_bot":
            try:
                if _find_bot_pids(): self._json({"error": "bot already running", "pid": _find_bot_pids()[0]}); return
                log_path = Path("data/bot.log"); log_path.parent.mkdir(parents=True, exist_ok=True)
                log_file = open(log_path, "a")
                proc = subprocess.Popen(["python", "-m", "okx_paper_bot.cli", "run"], stdout=log_file, stderr=subprocess.STDOUT, cwd=str(Path(__file__).resolve().parent.parent.parent), env={**os.environ, "PYTHONUNBUFFERED": "1"})
                self._json({"status": "ok", "pid": proc.pid})
            except Exception as e: self._json({"error": str(e)}, 500)
        else:
            self.send_response(404); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"error": "not found"}).encode())

    def _sse(self, config):
        self.send_response(200); self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache"); self.send_header("Connection", "keep-alive"); self.end_headers()
        try:
            while True:
                # Use dashboard_v4 data (reconstructed from trades) instead of status (equity_history.json)
                # to avoid flickering when PaperAccount isn't persisted across restarts
                data = json.dumps(_build_api_dashboard_v4(config))
                self.wfile.write(f"data: {data}\n\n".encode()); self.wfile.flush(); time.sleep(5)
        except (BrokenPipeError, ConnectionResetError, OSError): pass

    def _json(self, data, status=200):
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, *args): pass


def run_dashboard(host="0.0.0.0", port=50001):
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"\U0001f310 Dashboard v3 running at http://{host}:{port}")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\n\U0001f6d1 Dashboard stopped"); server.server_close()
