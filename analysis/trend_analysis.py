#!/usr/bin/env python3
"""
trend_analysis.py — 知识图谱趋势分析系统

基于每日快照对比，实现：
1. 热度时序 — 实体 source_count 在时间轴上的变化
2. 新发现预警 — 最近导入周期中首次出现的实体
3. 突发检测 — 实体频次在短时间内的异常上升

依赖：query.py 的同款 DB_PATH，以及 loader.py --incremental 写入的快照。

用法:
  python3 trend_analysis.py snapshot    — 创建当日快照（loader 增量后自动调用）
  python3 trend_analysis.py rising      — 上升最快实体（对比上次快照）
  python3 trend_analysis.py new         — 新发现实体（最近快照周期内首次出现）
  python3 trend_analysis.py burst       — 突发检测（source_count 增速异常）
  python3 trend_analysis.py trending    — 综合趋势报告
  python3 trend_analysis.py status      — 快照状态检查
"""

import sqlite3
import json
import os
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import os
ORCAS_HOME = os.environ.get("ORCAS_HOME", os.path.expanduser("~/.orcas"))
DB_PATH = os.path.join(ORCAS_HOME, "kg.db")

# ===================== 快照管理 =====================

def ensure_snapshot_table(db):
    """确保 trend_snapshots 表存在"""
    db.execute("""
        CREATE TABLE IF NOT EXISTS trend_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            entity_snapshots TEXT NOT NULL  -- JSON: {entity_id: source_count, ...}
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_date ON trend_snapshots(snapshot_date)")
    db.commit()


def cmd_snapshot():
    """创建当前时刻的快照"""
    db = sqlite3.connect(DB_PATH)
    ensure_snapshot_table(db)
    
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().isoformat()
    
    # 检查今天是否已有快照
    existing = db.execute(
        "SELECT id, created_at FROM trend_snapshots WHERE snapshot_date = ? ORDER BY id DESC LIMIT 1",
        (today,)
    ).fetchone()
    
    if existing:
        print(f"⚠ 今日快照已存在 (ID: {existing[0]}, 创建于 {existing[1]})")
        print(f"   如需更新，请先删除旧快照再运行")
        db.close()
        return
    
    # 采集所有实体的 source_count
    entities = db.execute(
        "SELECT id, name, source_count, last_seen FROM entities WHERE source_count > 0"
    ).fetchall()
    
    snapshot_data = {}
    for e in entities:
        snapshot_data[e[0]] = {
            "name": e[1],
            "count": e[2],
            "last_seen": e[3] or ""
        }
    
    json_str = json.dumps(snapshot_data, ensure_ascii=False)
    
    db.execute(
        "INSERT INTO trend_snapshots (snapshot_date, created_at, entity_snapshots) VALUES (?, ?, ?)",
        (today, now, json_str)
    )
    db.commit()
    
    print(f"✅ 快照已创建: {today} ({now})")
    print(f"   记录实体数: {len(snapshot_data)}")
    db.close()


def get_latest_snapshots(db, n=3):
    """获取最近 n 个快照"""
    rows = db.execute(
        "SELECT id, snapshot_date, created_at, entity_snapshots FROM trend_snapshots ORDER BY id DESC LIMIT ?",
        (n,)
    ).fetchall()
    
    results = []
    for r in rows:
        results.append({
            "id": r[0],
            "date": r[1],
            "created_at": r[2],
            "data": json.loads(r[3]) if r[3] else {}
        })
    return results


# ===================== 趋势分析命令 =====================

def cmd_status():
    """查看快照状态"""
    db = sqlite3.connect(DB_PATH)
    ensure_snapshot_table(db)
    
    rows = db.execute(
        "SELECT id, snapshot_date, created_at, LENGTH(entity_snapshots) as size FROM trend_snapshots ORDER BY id DESC LIMIT 10"
    ).fetchall()
    
    if not rows:
        print("📊 快照状态: 暂无快照")
        print("   运行 `trend_analysis.py snapshot` 创建第一个快照")
        db.close()
        return
    
    print("📊 快照历史:\n")
    print(f"{'ID':>4} {'日期':12s} {'创建时间':25s} {'大小':>8}")
    print(f"{'─'*4} {'─'*12} {'─'*25} {'─'*8}")
    for r in rows:
        print(f"{r[0]:4d} {r[1]:12s} {r[2]:25s} {r[3]:8d}")
    
    # 最新快照概要
    latest = rows[0]
    latest_data = json.loads(db.execute(
        "SELECT entity_snapshots FROM trend_snapshots WHERE id = ?", (latest[0],)
    ).fetchone()[0])
    
    total = len(latest_data)
    total_count = sum(e["count"] for e in latest_data.values())
    print(f"\n   最新快照 (#{latest[0]}): {total} 实体, {total_count} 总出现次数")
    
    db.close()


def cmd_rising(limit=20):
    """上升最快实体（对比最新两个快照）"""
    db = sqlite3.connect(DB_PATH)
    ensure_snapshot_table(db)
    
    snapshots = get_latest_snapshots(db, 2)
    if len(snapshots) < 2:
        print("⚠ 需要至少2个快照才能计算趋势")
        print(f"   当前: {len(snapshots)} 个快照")
        db.close()
        return
    
    old, new = snapshots[1], snapshots[0]
    old_data, new_data = old["data"], new["data"]
    
    print(f"📈 上升最快实体 (对比 {old['date']} → {new['date']})\n")
    print(f"{'排名':>4} {'实体名':25s} {'增长':>6} {'旧值':>6} {'新值':>6} {'类型':12s}")
    print(f"{'─'*4} {'─'*25} {'─'*6} {'─'*6} {'─'*6} {'─'*12}")
    
    # 计算每个实体的增量
    deltas = []
    for eid, info in new_data.items():
        old_count = old_data.get(eid, {}).get("count", 0)
        new_count = info["count"]
        delta = new_count - old_count
        if delta > 0:
            deltas.append((delta, info["name"], old_count, new_count))
    
    deltas.sort(key=lambda x: -x[0])
    
    for i, (delta, name, old_c, new_c) in enumerate(deltas[:limit], 1):
        # 获取类型
        ent = db.execute("SELECT type FROM entities WHERE name = ?", (name,)).fetchone()
        etype = ent[0] if ent else "?"
        print(f"{i:4d} {name:25s} +{delta:4d} {old_c:6d} {new_c:6d} {etype:12s}")
    
    print(f"\n   共 {len(deltas)} 个实体的计数有增长")
    db.close()


def cmd_new(limit=30):
    """新发现实体（在当前最新快照中，但不在历史快照中）"""
    db = sqlite3.connect(DB_PATH)
    ensure_snapshot_table(db)
    
    snapshots = get_latest_snapshots(db, 3)
    if not snapshots:
        print("⚠ 需要至少1个快照")
        db.close()
        return
    
    if len(snapshots) == 1:
        # 只有1个快照 — 所有实体都是"新发现"
        latest = snapshots[0]
        entities_in_first = set()
    else:
        # 收集历史快照中所有见过实体ID
        entities_in_first = set()
        for s in snapshots[1:]:
            entities_in_first.update(s["data"].keys())
    
    latest = snapshots[0]
    new_entities = []
    
    for eid, info in latest["data"].items():
        if eid not in entities_in_first:
            new_entities.append((info["name"], info["count"], info["last_seen"]))
    
    # 按出现次数排序
    new_entities.sort(key=lambda x: -x[1])
    
    print(f"🆕 新发现实体 (相对之前的快照)\n")
    print(f"{'排名':>4} {'实体名':30s} {'出现次数':>8} {'最近':20s}")
    print(f"{'─'*4} {'─'*30} {'─'*8} {'─'*20}")
    
    for i, (name, count, last_seen) in enumerate(new_entities[:limit], 1):
        print(f"{i:4d} {name:30s} {count:8d} {last_seen[:20]:20s}")
    
    print(f"\n   共 {len(new_entities)} 个新发现实体")
    db.close()


def cmd_burst(threshold=5, limit=20):
    """突发检测 — source_count 增速异常（新值 / 旧值 > threshold）
    过滤条件是旧值 > 0（避免除零）且新值 - 旧值 >= 3
    """
    db = sqlite3.connect(DB_PATH)
    ensure_snapshot_table(db)
    
    snapshots = get_latest_snapshots(db, 2)
    if len(snapshots) < 2:
        print("⚠ 需要至少2个快照才能进行突发检测")
        db.close()
        return
    
    old, new = snapshots[1], snapshots[0]
    old_data, new_data = old["data"], new["data"]
    
    print(f"⚡ 突发检测 (增长率 > {threshold}x, 对比 {old['date']} → {new['date']})\n")
    print(f"{'排名':>4} {'实体名':30s} {'增长率':>8} {'旧值':>5} {'新值':>5} {'类型':12s}")
    print(f"{'─'*4} {'─'*30} {'─'*8} {'─'*5} {'─'*5} {'─'*12}")
    
    bursts = []
    for eid, info in new_data.items():
        old_count = old_data.get(eid, {}).get("count", 0)
        new_count = info["count"]
        delta = new_count - old_count
        if old_count > 0 and delta >= 3:
            ratio = new_count / old_count
            if ratio >= threshold:
                bursts.append((ratio, info["name"], old_count, new_count))
    
    bursts.sort(key=lambda x: -x[0])
    
    for i, (ratio, name, old_c, new_c) in enumerate(bursts[:limit], 1):
        ent = db.execute("SELECT type FROM entities WHERE name = ?", (name,)).fetchone()
        etype = ent[0] if ent else "?"
        print(f"{i:4d} {name:30s} {ratio:6.1f}x {old_c:5d} {new_c:5d} {etype:12s}")
    
    print(f"\n   共 {len(bursts)} 个实体触发突发检测")
    db.close()


def cmd_trending():
    """综合趋势报告"""
    db = sqlite3.connect(DB_PATH)
    ensure_snapshot_table(db)
    
    snapshots = get_latest_snapshots(db, 2)
    if len(snapshots) < 2:
        print("⚠ 综合趋势报告需要至少2个快照")
        print(f"   当前: {len(snapshots)} 个快照")
        db.close()
        return
    
    old, new = snapshots[1], snapshots[0]
    old_data, new_data = old["data"], new["data"]
    
    print(f"📊 综合趋势报告: {old['date']} → {new['date']}\n")
    print(f"{'='*70}")
    
    # 1. 总体统计
    old_total = sum(e["count"] for e in old_data.values())
    new_total = sum(e["count"] for e in new_data.values())
    total_delta = new_total - old_total
    pct = (total_delta / max(old_total, 1)) * 100
    direction = "↑" if total_delta > 0 else "↓"
    
    print(f"📈 总体变动: {old_total} → {new_total} ({direction} {abs(pct):.1f}%)")
    print(f"   活跃实体: {len(old_data)} → {len(new_data)}")
    print()
    
    # 2. 上升最快 Top 10
    print(f"{'='*70}")
    print(f"🏆 上升最快 Top 10\n")
    deltas = []
    for eid, info in new_data.items():
        old_c = old_data.get(eid, {}).get("count", 0)
        new_c = info["count"]
        delta = new_c - old_c
        if delta > 0:
            deltas.append((delta, info["name"], old_c, new_c))
    deltas.sort(key=lambda x: -x[0])
    
    print(f"{'排名':>4} {'实体':25s} {'增长':>6} {'旧值':>6} {'新值':>6}")
    print(f"{'─'*4} {'─'*25} {'─'*6} {'─'*6} {'─'*6}")
    for i, (d, name, oc, nc) in enumerate(deltas[:10], 1):
        print(f"{i:4d} {name:25s} +{d:4d} {oc:6d} {nc:6d}")
    print()
    
    # 3. 新发现 Top 10
    known_entities = set()
    for s in snapshots[1:]:
        known_entities.update(s["data"].keys())
    
    new_list = [(info["name"], info["count"]) for eid, info in new_data.items() 
                 if eid not in known_entities]
    new_list.sort(key=lambda x: -x[1])
    
    if new_list:
        print(f"{'='*70}")
        print(f"🆕 新发现实体 Top 10\n")
        for i, (name, count) in enumerate(new_list[:10], 1):
            print(f"  {i:2d}. {name:30s} (出现 {count} 次)")
        print()
    
    # 4. 突发 Top 10
    bursts = []
    for eid, info in new_data.items():
        old_c = old_data.get(eid, {}).get("count", 0)
        new_c = info["count"]
        delta = new_c - old_c
        if old_c > 0 and delta >= 3:
            ratio = new_c / old_c
            if ratio >= 3:
                bursts.append((ratio, info["name"], old_c, new_c))
    bursts.sort(key=lambda x: -x[0])
    
    if bursts:
        print(f"{'='*70}")
        print(f"⚡ 突发信号 Top 10 (增长率 > 3x)\n")
        print(f"{'排名':>4} {'实体':25s} {'增长率':>8} {'旧值':>5} {'新值':>5}")
        print(f"{'─'*4} {'─'*25} {'─'*8} {'─'*5} {'─'*5}")
        for i, (r, name, oc, nc) in enumerate(bursts[:10], 1):
            print(f"{i:4d} {name:25s} {r:6.1f}x {oc:5d} {nc:5d}")
    
    print(f"\n{'='*70}")
    print(f"报告生成: {datetime.now().isoformat()[:19]}")
    
    db.close()


# ===================== 入口 =====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="知识图谱趋势分析系统")
    parser.add_argument("command", nargs="?", default="status",
                       choices=["snapshot", "rising", "new", "burst", "trending", "status"])
    parser.add_argument("--limit", type=int, default=20, help="结果数量限制")
    parser.add_argument("--threshold", type=float, default=5.0, help="突发检测触发阈值(默认5x)")
    args = parser.parse_args()
    
    commands = {
        "snapshot": lambda: cmd_snapshot(),
        "rising": lambda: cmd_rising(args.limit),
        "new": lambda: cmd_new(args.limit),
        "burst": lambda: cmd_burst(args.threshold, args.limit),
        "trending": lambda: cmd_trending(),
        "status": lambda: cmd_status(),
    }
    
    commands[args.command]()
