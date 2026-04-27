#!/usr/bin/env python3
"""scripts/health_check.py — 系统健康检查
验证 KG 完整性、快照时效性、组件可运行性。
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ORCAS_HOME = os.environ.get("ORCAS_HOME", os.path.expanduser("~/.orcas"))


def check_kg():
    """检查知识图谱数据库"""
    db_path = os.path.join(ORCAS_HOME, "kg.db")
    if not os.path.exists(db_path):
        return ("KG 数据库", "MISSING", f"{db_path} 不存在")
    
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # 检查表是否存在
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        
        if "entities" not in tables:
            conn.close()
            return ("KG 数据库", "ERROR", "缺少 entities 表")
        
        cur.execute("SELECT COUNT(*) FROM entities")
        count = cur.fetchone()[0]
        conn.close()
        
        return ("KG 数据库", "OK", f"{count} 实体")
    except Exception as e:
        return ("KG 数据库", "ERROR", str(e))


def check_snapshot():
    """检查快照状态"""
    db_path = os.path.join(ORCAS_HOME, "kg.db")
    if not os.path.exists(db_path):
        return ("趋势快照", "SKIP", "KG 不存在")
    
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # 检查 trend_snapshots 表
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trend_snapshots'")
        if not cur.fetchone():
            conn.close()
            return ("趋势快照", "WARN", "快照表未创建，请运行 trend_analysis snapshot")
        
        cur.execute("SELECT snapshot_date FROM trend_snapshots ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return ("趋势快照", "WARN", "无快照数据")
        
        last_date = row[0]
        today = datetime.now().strftime("%Y-%m-%d")
        
        if last_date == today:
            return ("趋势快照", "OK", f"今日已更新")
        elif (datetime.now() - datetime.strptime(last_date, "%Y-%m-%d")).days <= 2:
            return ("趋势快照", "WARN", f"最后快照: {last_date}")
        else:
            return ("趋势快照", "STALE", f"最后快照: {last_date}")
    except Exception as e:
        return ("趋势快照", "ERROR", str(e))


def check_collector():
    """检查采集器输出目录"""
    news_dir = os.path.join(ORCAS_HOME, "news", "data")
    if not os.path.exists(news_dir):
        return ("采集输出", "WARN", "采集目录不存在，请先运行采集器")
    
    today = datetime.now().strftime("%Y-%m-%d")
    today_file = os.path.join(news_dir, f"tagged_news_{today}.json")
    
    if os.path.exists(today_file):
        try:
            with open(today_file) as f:
                data = json.load(f)
            return ("采集输出", "OK", f"今日 {len(data)} 条")
        except:
            return ("采集输出", "WARN", "今日文件格式异常")
    else:
        return ("采集输出", "WARN", "今日未采集")


def run_all():
    """运行全部检查"""
    checks = [
        check_kg(),
        check_snapshot(),
        check_collector(),
    ]
    
    all_ok = True
    print("\n=== Orcas 健康检查 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"ORCAS_HOME: {ORCAS_HOME}")
    print()
    
    for name, status, detail in checks:
        icon = {"OK": "✓", "WARN": "⚠", "ERROR": "✗", "MISSING": "✗", "SKIP": "→", "STALE": "⚠"}.get(status, "?")
        print(f"  {icon} {name}: {status} — {detail}")
        if status in ("ERROR", "MISSING"):
            all_ok = False
    
    print()
    if all_ok:
        print("结果: 一切正常 ✓")
    else:
        print("结果: 存在问题需要处理 ⚠")
    
    return all_ok


if __name__ == "__main__":
    full = "--full" in sys.argv
    
    if full:
        # 全链路检查会导入并测试各模块
        logger.info("执行全链路检查...")
        try:
            import analysis.trend_analysis
            logger.info("  trend_analysis: 可加载 ✓")
        except Exception as e:
            logger.warning(f"  trend_analysis: {e}")
        
        try:
            import collector.collector
            logger.info("  collector: 可加载 ✓")
        except Exception as e:
            logger.warning(f"  collector: {e}")
    
    ok = run_all()
    sys.exit(0 if ok else 1)
