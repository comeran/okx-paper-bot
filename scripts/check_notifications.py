#!/usr/bin/env python3
"""读取通知队列，输出未发送的消息（供 Hermes cron 转发到微信）。

- 读取 data/notify_queue.jsonl
- 输出所有待发消息到 stdout
- 清空队列文件
- 无消息时输出空（cron 静默不发）
"""
import json
import sys
from pathlib import Path

QUEUE = Path("/opt/data/okx-paper-bot/data/notify_queue.jsonl")

if not QUEUE.exists() or QUEUE.stat().st_size == 0:
    sys.exit(0)

try:
    lines = QUEUE.read_text(encoding="utf-8").strip().split("\n")
except Exception:
    sys.exit(0)

messages = []
for line in lines:
    line = line.strip()
    if not line:
        continue
    try:
        entry = json.loads(line)
        messages.append(entry.get("msg", line))
    except json.JSONDecodeError:
        messages.append(line)

if not messages:
    sys.exit(0)

# 输出所有待发消息
for msg in messages:
    print(msg)
    print()

# 清空队列
QUEUE.write_text("", encoding="utf-8")
