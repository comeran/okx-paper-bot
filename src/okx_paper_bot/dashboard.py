"""Web Dashboard - 查看持仓、交易、收益。"""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import time
from string import Template
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
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
  :root {
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --yellow: #d29922;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }
  a { color: var(--accent); text-decoration: none; }

  /* Nav */
  .nav { position: sticky; top: 0; z-index: 100; background: var(--card); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 0; padding: 0 16px; overflow-x: auto; }
  .nav .brand { font-weight: 700; color: var(--accent); font-size: 16px; padding: 12px 16px 12px 0; white-space: nowrap; border-right: 1px solid var(--border); margin-right: 8px; }
  .nav a { padding: 12px 14px; color: var(--muted); font-size: 14px; white-space: nowrap; border-bottom: 2px solid transparent; transition: color .2s, border-color .2s; }
  .nav a:hover, .nav a.active { color: var(--text); border-bottom-color: var(--accent); }

  /* Sections */
  .section { padding: 20px 20px 8px; scroll-margin-top: 56px; }
  .section-title { font-size: 18px; font-weight: 600; color: var(--accent); margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }

  /* Cards */
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 12px; }
  .metrics { display: flex; flex-wrap: wrap; gap: 12px; }
  .metric { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px 18px; min-width: 140px; flex: 1; }
  .metric .label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }
  .metric .value { font-size: 24px; font-weight: 700; margin-top: 4px; }

  /* Tables */
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .5px; }
  tr:hover { background: rgba(88,166,255,.04); }

  /* Buttons */
  .btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border: 1px solid var(--border); border-radius: 6px; background: var(--card); color: var(--text); font-size: 14px; cursor: pointer; transition: border-color .2s, background .2s; }
  .btn:hover { border-color: var(--accent); background: rgba(88,166,255,.08); }
  .btn-primary { background: #238636; border-color: #2ea043; color: #fff; }
  .btn-primary:hover { background: #2ea043; }
  .btn-danger { background: #da3633; border-color: #f85149; color: #fff; }
  .btn-danger:hover { background: #f85149; }
  .btn:disabled { opacity: .5; cursor: not-allowed; }

  /* Filters */
  .filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; align-items: center; }
  .filters select, .filters input { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; color: var(--text); font-size: 14px; }
  .filters label { font-size: 13px; color: var(--muted); }

  /* Chart containers */
  .chart-container { position: relative; width: 100%; max-width: 800px; margin: 0 auto; }
  .chart-container canvas { width: 100% !important; }

  /* Colors */
  .green { color: var(--green); } .red { color: var(--red); } .yellow { color: var(--yellow); }

  /* Spinner */
  .spinner { display: inline-block; width: 20px; height: 20px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .6s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 14px; padding: 20px; }

  /* Error */
  .error-msg { background: rgba(248,81,73,.1); border: 1px solid var(--red); border-radius: 6px; padding: 12px; color: var(--red); font-size: 14px; margin-bottom: 12px; display: none; }

  /* Pagination */
  .pagination { display: flex; align-items: center; gap: 8px; margin-top: 12px; justify-content: center; }
  .pagination .btn { padding: 6px 12px; font-size: 13px; }
  .pagination .info { font-size: 13px; color: var(--muted); }

  /* Form */
  .form-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
  .form-grid label { font-size: 13px; color: var(--muted); display: block; margin-bottom: 4px; }
  .form-grid input { width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px; color: var(--text); font-size: 14px; }

  /* Config list */
  .config-list { list-style: none; }
  .config-list li { padding: 8px 0; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; font-size: 14px; }
  .config-list li span:first-child { color: var(--muted); }
  .config-list li span:last-child { font-weight: 600; color: var(--text); }

  /* Responsive */
  @media (max-width: 768px) {
    .nav { font-size: 13px; }
    .nav a { padding: 10px 10px; }
    .metrics { flex-direction: column; }
    .metric .value { font-size: 20px; }
    .form-grid { grid-template-columns: 1fr; }
    .section { padding: 12px; }
    table { font-size: 12px; }
    th, td { padding: 6px 8px; }
  }

  /* Grid visualization */
  .grid-viz { position: relative; padding: 12px 0; }
  .grid-row { display: flex; align-items: center; gap: 10px; padding: 4px 8px; border-bottom: 1px solid var(--border); font-size: 14px; }
  .grid-row:last-child { border-bottom: none; }
  .grid-dot { width: 14px; height: 14px; border-radius: 50%; flex-shrink: 0; }
  .grid-dot.available { background: var(--green); }
  .grid-dot.bought { background: var(--yellow); }
  .grid-dot.completed { background: var(--muted); }
  .grid-price { font-weight: 600; min-width: 100px; }
  .grid-label { font-size: 12px; color: var(--muted); min-width: 80px; }
  .grid-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
  .grid-unavailable { text-align: center; padding: 40px 20px; color: var(--muted); }
  .grid-unavailable .icon { font-size: 48px; margin-bottom: 12px; }
"""

HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OKX Paper Bot Dashboard</title>
<style>$css</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head><body>

<nav class="nav">
  <span class="brand">🤖 OKX Bot</span>
  <a href="#overview" class="active" data-nav>总览</a>
  <a href="#equity" data-nav>权益</a>
  <a href="#trades" data-nav>交易</a>
  <a href="#stats" data-nav>统计</a>
  <a href="#backtest" data-nav>回测</a>
  <a href="#grid" data-nav>网格</a>
  <a href="#settings" data-nav>设置</a>
</nav>

<div class="error-msg" id="errorBox"></div>

<!-- Overview -->
<div class="section" id="overview">
  <div class="section-title">📊 账户总览</div>
  <div class="metrics">
    <div class="metric"><div class="label">余额 (USDT)</div><div class="value" id="vBalance">--</div></div>
    <div class="metric"><div class="label">持仓价值</div><div class="value" id="vPosValue">--</div></div>
    <div class="metric"><div class="label">账户总值</div><div class="value" id="vEquity">--</div></div>
    <div class="metric"><div class="label">总收益</div><div class="value" id="vReturn">--</div></div>
    <div class="metric"><div class="label">策略</div><div class="value" id="vStrategy" style="font-size:16px">--</div></div>
    <div class="metric"><div class="label">交易数</div><div class="value" id="vTrades">--</div></div>
  </div>
  <div class="card" style="margin-top:12px">
    <div class="section-title">📦 持仓明细</div>
    <div id="positionsArea"><div class="loading"><div class="spinner"></div> 加载中...</div></div>
  </div>
</div>

<!-- Equity -->
<div class="section" id="equity">
  <div class="section-title">📈 权益曲线</div>
  <div class="card">
    <div class="chart-container"><canvas id="equityChart"></canvas></div>
    <div class="loading" id="equityLoading"><div class="spinner"></div> 加载中...</div>
  </div>
  <div class="metrics" style="margin-top:12px">
    <div class="metric"><div class="label">Sharpe Ratio</div><div class="value" id="vSharpe">--</div></div>
    <div class="metric"><div class="label">最大回撤</div><div class="value" id="vDrawdown">--</div></div>
  </div>
</div>

<!-- Stats -->
<div class="section" id="stats">
  <div class="section-title">📉 交易统计</div>
  <div class="metrics">
    <div class="metric"><div class="label">总交易</div><div class="value" id="vTotalTrades">--</div></div>
    <div class="metric"><div class="label">胜率</div><div class="value" id="vWinRate">--</div></div>
    <div class="metric"><div class="label">盈亏比</div><div class="value" id="vPF">--</div></div>
    <div class="metric"><div class="label">平均盈利</div><div class="value" id="vAvgWin">--</div></div>
    <div class="metric"><div class="label">平均亏损</div><div class="value" id="vAvgLoss">--</div></div>
    <div class="metric"><div class="label">总盈亏</div><div class="value" id="vTotalPnl">--</div></div>
  </div>
  <div class="card" style="margin-top:12px">
    <div class="chart-container" style="max-width:320px"><canvas id="statsChart"></canvas></div>
  </div>
</div>

<!-- Trades -->
<div class="section" id="trades">
  <div class="section-title">📋 交易记录</div>
  <div class="card">
    <div class="filters">
      <label>交易对</label>
      <select id="fSymbol"><option value="">全部</option></select>
      <label>方向</label>
      <select id="fSide"><option value="">全部</option><option value="buy">买入</option><option value="sell">卖出</option><option value="stop_loss">止损</option><option value="take_profit">止盈</option></select>
      <button class="btn" onclick="fetchTrades(1)">筛选</button>
    </div>
    <div id="tradesTable"><div class="loading"><div class="spinner"></div> 加载中...</div></div>
    <div class="pagination" id="tradesPagination"></div>
  </div>
</div>

<!-- Backtest -->
<div class="section" id="backtest">
  <div class="section-title">🧪 回测</div>
  <div class="card">
    <form id="btForm" onsubmit="runBacktest(event)">
      <div class="form-grid">
        <div><label>交易对</label><input id="btSymbol" value="$default_symbol"></div>
        <div><label>时间框架</label><input id="btTF" value="$default_tf"></div>
        <div><label>天数</label><input id="btDays" type="number" value="30"></div>
        <div><label>快线</label><input id="btFast" type="number" value="$default_fast"></div>
        <div><label>慢线</label><input id="btSlow" type="number" value="$default_slow"></div>
      </div>
      <div style="margin-top:12px"><button class="btn btn-primary" type="submit" id="btRun">运行回测</button></div>
    </form>
    <div id="btResult" style="margin-top:16px;display:none">
      <div class="metrics" id="btMetrics"></div>
      <div class="card" style="margin-top:12px">
        <div class="chart-container"><canvas id="btChart"></canvas></div>
      </div>
    </div>
  </div>
</div>

<!-- Grid -->
<div class="section" id="grid">
  <div class="section-title">🔲 网格策略</div>
  <div class="card">
    <div id="gridArea"><div class="loading"><div class="spinner"></div> 加载中...</div></div>
  </div>
</div>

<!-- Settings -->
<div class="section" id="settings">
  <div class="section-title">⚙️ 设置</div>
  <div class="card">
    <ul class="config-list" id="configList"><li><span>加载中...</span></li></ul>
  </div>
  <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
    <button class="btn" onclick="location.reload()">🔄 刷新页面</button>
    <button class="btn" onclick="controlBot('restart')">🔄 重启机器人</button>
    <button class="btn btn-danger" onclick="controlBot('stop')">⛔ 停止机器人</button>
  </div>
</div>

<div style="text-align:center;padding:20px;color:var(--muted);font-size:12px">
  OKX Paper Trading Bot &mdash; SSE 实时更新 &mdash; <span id="sseStatus">连接中...</span>
</div>

<script>
(function() {
  let equityChartObj = null, statsChartObj = null, btChartObj = null;

  // ── Helpers ──
  function $(id) { return document.getElementById(id); }
  function showError(msg) { var e = $('errorBox'); e.textContent = msg; e.style.display = 'block'; setTimeout(function() { e.style.display = 'none'; }, 8000); }
  function fmt(n, d) { return n !== undefined && n !== null ? Number(n).toFixed(d !== undefined ? d : 2) : '--'; }
  function cls(n) { return n >= 0 ? 'green' : 'red'; }

  // ── Nav ──
  document.querySelectorAll('[data-nav]').forEach(function(a) {
    a.addEventListener('click', function(e) {
      document.querySelectorAll('[data-nav]').forEach(function(x) { x.classList.remove('active'); });
      this.classList.add('active');
    });
  });

  // ── SSE for real-time overview ──
  var evtSrc = new EventSource('/api/stream');
  evtSrc.onopen = function() { $('sseStatus').textContent = '已连接'; $('sseStatus').className = 'green'; };
  evtSrc.onerror = function() { $('sseStatus').textContent = '已断开'; $('sseStatus').className = 'red'; };
  evtSrc.onmessage = function(e) {
    try {
      var d = JSON.parse(e.data);
      $('vBalance').textContent = fmt(d.balance);
      $('vPosValue').textContent = fmt(d.positions_value);
      $('vEquity').textContent = fmt(d.total_equity);
      $('vEquity').className = 'value ' + cls(d.total_equity - d.initial_balance);
      $('vReturn').textContent = fmt(d.return_pct, 2) + '%';
      $('vReturn').className = 'value ' + cls(d.return_pct);
      $('vStrategy').textContent = d.strategy || '--';
      $('vTrades').textContent = d.trades_count !== undefined ? d.trades_count : '--';
      // Positions table
      var area = $('positionsArea');
      if (d.positions && d.positions.length > 0) {
        var html = '<table><tr><th>交易对</th><th>数量</th><th>价格</th><th>价值</th></tr>';
        d.positions.forEach(function(p) {
          html += '<tr><td>' + p.symbol + '</td><td>' + fmt(p.amount, 6) + '</td><td>' + fmt(p.price) + '</td><td>' + fmt(p.value) + '</td></tr>';
        });
        html += '</table>';
        area.innerHTML = html;
      } else {
        area.innerHTML = '<p style="color:var(--muted)">空仓</p>';
      }
    } catch(err) {}
  };

  // ── Equity Chart ──
  function loadEquity() {
    fetch('/api/equity').then(function(r) { return r.json(); }).then(function(d) {
      $('equityLoading').style.display = 'none';
      $('vSharpe').textContent = fmt(d.sharpe, 4);
      $('vDrawdown').textContent = fmt(d.max_drawdown * 100, 2) + '%';
      if (!d.history || d.history.length === 0) return;
      var labels = d.history.map(function(h) { return h.timestamp; });
      var data = d.history.map(function(h) { return h.total_equity; });
      var ctx = $('equityChart').getContext('2d');
      if (equityChartObj) equityChartObj.destroy();
      equityChartObj = new Chart(ctx, {
        type: 'line',
        data: { labels: labels, datasets: [{ label: '权益 (USDT)', data: data, borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.08)', fill: true, tension: 0.3, pointRadius: 2 }] },
        options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { display: true, ticks: { color: '#8b949e', maxTicksLimit: 8, font: { size: 10 } }, grid: { color: '#21262d' } }, y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } } } }
      });
    }).catch(function(e) { $('equityLoading').textContent = '加载失败: ' + e.message; });
  }
  loadEquity();

  // ── Stats + Pie Chart ──
  function loadStats() {
    fetch('/api/stats').then(function(r) { return r.json(); }).then(function(d) {
      $('vTotalTrades').textContent = d.total_trades;
      $('vWinRate').textContent = fmt(d.win_rate * 100, 1) + '%';
      $('vPF').textContent = fmt(d.profit_factor);
      $('vAvgWin').textContent = fmt(d.avg_win);
      $('vAvgWin').className = 'value green';
      $('vAvgLoss').textContent = fmt(d.avg_loss);
      $('vAvgLoss').className = 'value red';
      $('vTotalPnl').textContent = fmt(d.total_pnl);
      $('vTotalPnl').className = 'value ' + cls(d.total_pnl);
      // Pie chart
      var ctx = $('statsChart').getContext('2d');
      if (statsChartObj) statsChartObj.destroy();
      statsChartObj = new Chart(ctx, {
        type: 'doughnut',
        data: { labels: ['盈利', '亏损'], datasets: [{ data: [d.winning_trades || 0, d.losing_trades || 0], backgroundColor: ['#3fb950', '#f85149'], borderWidth: 0 }] },
        options: { responsive: true, plugins: { legend: { position: 'bottom', labels: { color: '#c9d1d9' } } } }
      });
    }).catch(function(e) { showError('统计数据加载失败'); });
  }
  loadStats();

  // ── Trades Table ──
  function fetchTrades(page) {
    var sym = $('fSymbol').value;
    var side = $('fSide').value;
    var url = '/api/trades?page=' + (page || 1) + '&per_page=15';
    if (sym) url += '&symbol=' + encodeURIComponent(sym);
    if (side) url += '&side=' + encodeURIComponent(side);
    fetch(url).then(function(r) { return r.json(); }).then(function(d) {
      var area = $('tradesTable');
      if (!d.trades || d.trades.length === 0) { area.innerHTML = '<p style="color:var(--muted)">暂无交易记录</p>'; $('tradesPagination').innerHTML = ''; return; }
      var html = '<table><tr><th>时间</th><th>方向</th><th>交易对</th><th>数量</th><th>价格</th><th>盈亏</th></tr>';
      d.trades.forEach(function(t) {
        var sc = t.side === 'buy' ? 'green' : 'red';
        var pnlStr = '--';
        if (t.pnl !== undefined && t.pnl !== null) { pnlStr = '<span class="' + cls(t.pnl) + '">' + fmt(t.pnl) + '</span>'; }
        html += '<tr><td>' + (t.ts || '') + '</td><td class="' + sc + '">' + t.side.toUpperCase() + '</td><td>' + t.symbol + '</td><td>' + fmt(t.amount, 6) + '</td><td>' + fmt(t.price) + '</td><td>' + pnlStr + '</td></tr>';
      });
      html += '</table>';
      area.innerHTML = html;
      // Pagination
      var pg = $('tradesPagination');
      var pgHtml = '';
      if (d.page > 1) pgHtml += '<button class="btn" onclick="fetchTrades(' + (d.page - 1) + ')">上一页</button>';
      pgHtml += '<span class="info">第 ' + d.page + ' / ' + d.pages + ' 页 (共 ' + d.total + ' 条)</span>';
      if (d.page < d.pages) pgHtml += '<button class="btn" onclick="fetchTrades(' + (d.page + 1) + ')">下一页</button>';
      pg.innerHTML = pgHtml;
      // Populate symbol filter
      var sel = $('fSymbol');
      if (sel.options.length <= 1) {
        var seen = {};
        d.trades.forEach(function(t) { seen[t.symbol] = true; });
        // Fetch all to get symbols — or just use config
      }
    }).catch(function(e) { showError('交易数据加载失败'); });
  }
  fetchTrades(1);
  // Expose to global for onclick
  window.fetchTrades = fetchTrades;

  // ── Config for symbol filter + settings ──
  fetch('/api/config').then(function(r) { return r.json(); }).then(function(d) {
    // Symbol filter
    var sel = $('fSymbol');
    if (d.symbols) {
      d.symbols.forEach(function(s) { var o = document.createElement('option'); o.value = s; o.textContent = s; sel.appendChild(o); });
    }
    // Settings list
    var list = $('configList');
    var html = '';
    var keys = Object.keys(d);
    keys.forEach(function(k) {
      html += '<li><span>' + k + '</span><span>' + JSON.stringify(d[k]) + '</span></li>';
    });
    list.innerHTML = html;
    // Backtest defaults
    if (d.symbols && d.symbols[0]) $('btSymbol').value = d.symbols[0];
    if (d.timeframe) $('btTF').value = d.timeframe;
    if (d.fast_window) $('btFast').value = d.fast_window;
    if (d.slow_window) $('btSlow').value = d.slow_window;
  }).catch(function(e) {});

  // ── Backtest ──
  window.runBacktest = function(e) {
    e.preventDefault();
    var btn = $('btRun');
    btn.disabled = true; btn.textContent = '运行中...';
    var body = { symbol: $('btSymbol').value, timeframe: $('btTF').value, days: parseInt($('btDays').value) || 30, fast: parseInt($('btFast').value) || 5, slow: parseInt($('btSlow').value) || 20 };
    fetch('/api/backtest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(function(r) { return r.json(); }).then(function(d) {
      btn.disabled = false; btn.textContent = '运行回测';
      if (d.error) { showError('回测失败: ' + d.error); return; }
      $('btResult').style.display = 'block';
      var m = $('btMetrics');
      m.innerHTML = '<div class="metric"><div class="label">总收益</div><div class="value ' + cls(d.total_return) + '">' + fmt(d.total_return * 100, 2) + '%</div></div>' +
        '<div class="metric"><div class="label">交易数</div><div class="value">' + d.total_trades + '</div></div>' +
        '<div class="metric"><div class="label">胜率</div><div class="value">' + fmt(d.win_rate * 100, 1) + '%</div></div>' +
        '<div class="metric"><div class="label">盈亏比</div><div class="value">' + fmt(d.profit_factor) + '</div></div>' +
        '<div class="metric"><div class="label">最大回撤</div><div class="value red">' + fmt(d.max_drawdown * 100, 2) + '%</div></div>';
      if (d.equity_curve && d.equity_curve.length > 0) {
        var ctx = $('btChart').getContext('2d');
        if (btChartObj) btChartObj.destroy();
        btChartObj = new Chart(ctx, {
          type: 'line',
          data: { labels: d.equity_curve.map(function(_, i) { return i; }), datasets: [{ label: '回测权益', data: d.equity_curve, borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.08)', fill: true, tension: 0.3, pointRadius: 0 }] },
          options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#8b949e', maxTicksLimit: 10 }, grid: { color: '#21262d' } }, y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } } } }
        });
      }
    }).catch(function(e) { btn.disabled = false; btn.textContent = '运行回测'; showError('回测请求失败: ' + e.message); });
  };

  // ── Grid Visualization ──
  function loadGrid() {
    fetch('/api/grid').then(function(r) {
      if (!r.ok) throw new Error('not available');
      return r.json();
    }).then(function(d) {
      if (!d.enabled) {
        $('gridArea').innerHTML = '<div class="grid-unavailable"><div class="icon">🔲</div><div>网格策略未启用</div><div style="font-size:13px;margin-top:8px">启动网格策略后将显示实时状态</div></div>';
        return;
      }
      var area = $('gridArea');
      var boughtPending = 0, available = 0;
      d.levels.forEach(function(l) {
        if (l.buy_filled && !l.sell_filled) boughtPending++;
        if (!l.buy_filled) available++;
      });
      // Stats row
      var html = '<div class="grid-stats">' +
        '<div class="metric"><div class="label">累计利润</div><div class="value green">' + fmt(d.total_profit) + ' USDT</div></div>' +
        '<div class="metric"><div class="label">完成循环</div><div class="value">' + d.completed_grids + '</div></div>' +
        '<div class="metric"><div class="label">买入待卖</div><div class="value yellow">' + boughtPending + '</div></div>' +
        '<div class="metric"><div class="label">可买入</div><div class="value green">' + available + '</div></div>' +
        '</div>';
      // Grid info
      html += '<div style="margin-bottom:12px;font-size:13px;color:var(--muted)">' + d.symbol + ' | 区间: ' + fmt(d.lower_price) + ' - ' + fmt(d.upper_price) + ' | 每格: ' + fmt(d.grid_step) + ' USDT | 每单: ' + d.order_usdt + ' USDT</div>';
      // Grid levels (top = highest price)
      var levels = d.levels.slice().reverse();
      html += '<div class="grid-viz">';
      levels.forEach(function(l) {
        var cls, label;
        if (l.buy_filled && l.sell_filled) { cls = 'completed'; label = '已完成'; }
        else if (l.buy_filled && !l.sell_filled) { cls = 'bought'; label = '待卖出'; }
        else { cls = 'available'; label = '可买入'; }
        html += '<div class="grid-row"><div class="grid-dot ' + cls + '"></div><div class="grid-price">' + fmt(l.price) + '</div><div class="grid-label">' + label + '</div></div>';
      });
      html += '</div>';
      area.innerHTML = html;
    }).catch(function() {
      $('gridArea').innerHTML = '<div class="grid-unavailable"><div class="icon">🔲</div><div>网格策略未启用</div><div style="font-size:13px;margin-top:8px">请在启动时启用网格策略以查看状态</div></div>';
    });
  }
  loadGrid();

  // ── Bot Control ──
  window.controlBot = function(action) {
    var labels = { restart: '重启', stop: '停止' };
    if (!confirm('确定要' + labels[action] + '机器人吗？')) return;
    fetch('/api/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: action }) })
    .then(function(r) { return r.json(); }).then(function(d) {
      if (d.error) { showError('操作失败: ' + d.error); }
      else { showError(''); alert('机器人' + labels[action] + '指令已发送'); }
    }).catch(function(e) { showError('控制请求失败: ' + e.message); });
  };
})();
</script>
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
    """Build the modern single-page dashboard HTML."""
    return HTML_TEMPLATE.safe_substitute(
        css=CSS,
        default_symbol=config.symbol,
        default_tf=config.timeframe,
        default_fast=config.fast_window,
        default_slow=config.slow_window,
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


def _get_grid_state_file(config: BotConfig) -> Path:
    """Resolve grid state file path."""
    env_path = os.getenv("GRID_STATE_FILE")
    if env_path:
        return Path(env_path)
    return config.db_path.parent / "grid_state.json"


def _normalize_grid_payload(data: dict, enabled: bool) -> dict:
    """Normalize a serialized GridState-like dict for the dashboard API."""
    cfg = data.get("config", {}) or {}
    lower = float(cfg.get("lower_price", 70000))
    upper = float(cfg.get("upper_price", 90000))
    grid_count = int(cfg.get("grid_count", 10))
    levels = [
        {
            "price": float(l["price"]),
            "buy_filled": bool(l.get("buy_filled", False)),
            "sell_filled": bool(l.get("sell_filled", False)),
        }
        for l in data.get("levels", [])
    ]
    bought_pending = sum(1 for l in levels if l["buy_filled"] and not l["sell_filled"])
    available = sum(1 for l in levels if not l["buy_filled"])
    return {
        "enabled": enabled,
        "symbol": cfg.get("symbol", "BTC/USDT"),
        "lower_price": lower,
        "upper_price": upper,
        "grid_count": grid_count,
        "grid_step": round((upper - lower) / grid_count, 2) if grid_count else 0.0,
        "order_usdt": float(cfg.get("order_usdt", 500)),
        "levels": levels,
        "total_profit": float(data.get("total_profit", 0.0)),
        "completed_grids": int(data.get("completed_grids", 0)),
        "bought_pending": bought_pending,
        "available": available,
    }


def _build_api_grid(config: BotConfig) -> dict:
    """Grid strategy status: levels, profit, completion stats."""
    from okx_paper_bot.grid import GridConfig

    grid_file = _get_grid_state_file(config)
    if not grid_file.exists():
        gc = GridConfig()
        demo = {
            "config": {
                "symbol": gc.symbol,
                "lower_price": gc.lower_price,
                "upper_price": gc.upper_price,
                "grid_count": gc.grid_count,
                "order_usdt": gc.order_usdt,
            },
            "levels": [
                {"price": p, "buy_filled": False, "sell_filled": False}
                for p in gc.grid_prices()
            ],
            "total_profit": 0.0,
            "completed_grids": 0,
        }
        return _normalize_grid_payload(demo, enabled=False)

    data = json.loads(grid_file.read_text())
    return _normalize_grid_payload(data, enabled=True)


def _find_bot_pids() -> list[int]:
    """Find running bot worker PIDs, excluding the dashboard process."""
    pids: list[int] = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        except OSError:
            continue
        if "okx_paper_bot.cli" in cmd and " run" in cmd:
            pids.append(int(proc.name))
    return pids


def _systemctl_bot(action: str) -> bool:
    """Try systemd control first when dashboard runs inside the LXC."""
    if action not in ("restart", "stop"):
        return False
    try:
        result = subprocess.run(
            ["systemctl", action, "okx-bot.service"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0


def _build_api_control(action: str) -> dict:
    """Execute bot control action (restart/stop) safely from the dashboard."""
    if action not in ("restart", "stop"):
        return {"error": f"invalid action: {action}"}

    if _systemctl_bot(action):
        return {"status": "ok", "action": action, "method": "systemctl"}

    pids = _find_bot_pids()
    if not pids:
        return {"error": "bot process not found"}

    for pid in pids:
        os.kill(pid, signal.SIGTERM)
    return {"status": "ok", "action": action, "method": "sigterm", "pids": pids}


# ── HTTP Handler ─────────────────────────────────────────────────────────


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        config = BotConfig.from_env()
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/api/status":
            self._json_response(_build_api_status(config))

        elif path == "/api/stream":
            self._sse_stream(config)

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

        elif path == "/api/grid":
            self._json_response(_build_api_grid(config))

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

        elif path == "/api/control":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len)
            params = json.loads(body) if body else {}
            action = params.get("action", "")
            # Safety: only allow from localhost
            client_addr = self.client_address[0]
            if client_addr not in ("127.0.0.1", "::1"):
                self._json_response({"error": "only localhost allowed"}, status=403)
            else:
                self._json_response(_build_api_control(action))

        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "not found"}).encode())

    def _sse_stream(self, config: BotConfig) -> None:
        """SSE endpoint: push status updates every 5 seconds."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                status = _build_api_status(config)
                data = json.dumps(status)
                self.wfile.write(f"data: {data}\n\n".encode())
                self.wfile.flush()
                time.sleep(5)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # Client disconnected cleanly

    def _json_response(self, data: dict, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, *args):
        pass  # 静默日志


def run_dashboard(host: str = "0.0.0.0", port: int = 50001) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"🌐 Dashboard running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Dashboard stopped")
        server.server_close()
