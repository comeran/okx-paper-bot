#!/usr/bin/env python3
"""OKX Quant Workbench - Hourly monitoring and auto-adjustment script.
Called by Hermes cron job. Reports status, detects issues, suggests adjustments.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone

BASE = "http://192.168.1.111:50001"

def api(method, path, data=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report = [f"📊 OKX 量化监控 {now}", ""]
    issues = []

    # 1. Health check
    health = api("GET", "/api/health")
    if "error" in health:
        print(f"❌ 系统离线: {health['error']}")
        return
    report.append("✅ 系统正常运行")

    # 2. Instance status + auto-activate
    instances = api("GET", "/api/instances")
    if isinstance(instances, list):
        report.append(f"\n📈 策略实例 ({len(instances)} 个)")
        for inst in instances:
            status = inst.get("status", "?")
            enabled = inst.get("enabled", False)
            if enabled and status not in ("okx_demo_running", "okx_live_running"):
                # Auto-activate instance
                inst_id = inst["id"]
                broker = inst.get("broker_mode", "okx_demo")
                target_status = "okx_demo_running" if "demo" in broker else "okx_live_running"
                r = api("POST", f"/api/instances/{inst_id}/status", {"status": target_status})
                status = r.get("status", "activate_failed")
                issues.append(f"自动激活 #{inst_id} {inst['name']} → {status}")

            icon = "🟢" if "running" in status else "🔴" if enabled else "⚪"
            report.append(f"  {icon} #{inst['id']} {inst['name']} | {inst['strategy_key']} | {inst['symbol']} {inst['timeframe']} | {status}")

    # 3. Recent trades
    trades = api("GET", "/api/trades")
    if isinstance(trades, list) and trades:
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        pnl_icon = "🟢" if total_pnl >= 0 else "🔴"
        report.append(f"\n💰 交易: {len(trades)} 笔 | 总盈亏: {pnl_icon} {total_pnl:+.2f} USDT")
        for t in trades[:3]:
            ts = t.get("ts", "")[:16]
            report.append(f"  {ts} {t.get('side','?').upper()} {t.get('symbol','?')} pnl={t.get('pnl',0):+.4f}")
    else:
        report.append("\n💰 暂无交易记录")

    # 4. Data freshness
    data_summary = api("GET", "/api/data/summary")
    if isinstance(data_summary, list):
        report.append(f"\n📡 数据源 ({len(data_summary)} 组)")
        for d in data_summary:
            report.append(f"  {d.get('symbol','?')} {d.get('timeframe','?')}: {d.get('count',0)} 根")

    # 5. Sync fresh data
    report.append("\n🔄 同步K线...")
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]
    for sym in symbols:
        for tf in ["1h", "15m"]:
            r = api("POST", "/api/candles/sync", {"symbol": sym, "timeframe": tf, "limit": 100})
            if "inserted" in r and r["inserted"] > 0:
                report.append(f"  ✓ {sym} {tf}: +{r['inserted']}")

    # 6. Quick re-backtest top strategies
    report.append("\n🧪 验证回测...")
    verify = [
        ("rsi_bollinger", {"rsi_period": 14, "oversold": 25, "overbought": 75, "bb_period": 20, "bb_std": 2.0}, "BTC/USDT"),
        ("rsi_bollinger", {"rsi_period": 14, "oversold": 25, "overbought": 75, "bb_period": 20, "bb_std": 2.0}, "SOL/USDT"),
        ("bollinger", {"period": 30, "std_dev": 2.5}, "BTC/USDT"),
    ]
    for strat, params, sym in verify:
        r = api("POST", "/api/backtests/run", {
            "strategy_key": strat, "strategy_params": params, "symbol": sym, "timeframe": "1h",
        })
        if "runs" in r and r["runs"]:
            run = r["runs"][0]
            ret = run.get("total_return_pct", 0)
            icon = "🟢" if ret > 0 else "🔴"
            report.append(f"  {icon} {strat} {sym}: {ret:+.3f}% dd={run.get('max_drawdown_pct',0):.2f}% trades={run.get('trades_count',0)}")
            if ret < -0.5:
                issues.append(f"⚠️ {strat} {sym} 回测亏损 {ret:+.3f}%，需关注")

    # 7. Summary
    if issues:
        report.append("\n⚠️ 需关注:")
        for issue in issues:
            report.append(f"  • {issue}")
    else:
        report.append("\n✅ 一切正常，无异常")

    print("\n".join(report))

if __name__ == "__main__":
    main()
