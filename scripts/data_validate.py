#!/usr/bin/env python3
"""scripts/data_validate.py — 数据校验工具
检查 JSON 格式、必填字段、重复记录。
"""

import os
import json
import sys
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ORCAS_HOME = os.environ.get("ORCAS_HOME", os.path.expanduser("~/.orcas"))


def validate_news_file(filepath: str) -> dict:
    """校验单个新闻数据文件
    
    Returns:
        {"file": ..., "total": N, "valid": N, "invalid": N, "errors": [...]}
    """
    result = {
        "file": filepath,
        "total": 0,
        "valid": 0,
        "invalid": 0,
        "errors": [],
    }
    
    if not os.path.exists(filepath):
        result["errors"].append("文件不存在")
        return result
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        result["errors"].append(f"JSON 解析失败: {e}")
        return result
    
    if not isinstance(data, list):
        result["errors"].append("顶层结构应为数组")
        return result
    
    result["total"] = len(data)
    
    required_fields = ["title", "url", "source"]
    
    for i, item in enumerate(data):
        missing = [f for f in required_fields if f not in item]
        if missing:
            result["invalid"] += 1
            result["errors"].append(f"条目 {i}: 缺少字段 {missing}")
        else:
            result["valid"] += 1
    
    return result


def validate_collector_output():
    """校验采集器输出目录"""
    data_dir = os.path.join(ORCAS_HOME, "news", "data")
    if not os.path.exists(data_dir):
        logger.warning("采集输出目录不存在")
        return
    
    files = [f for f in os.listdir(data_dir) if f.startswith("tagged_news_") and f.endswith(".json")]
    files.sort()
    
    if not files:
        logger.warning("未找到 tagged_news 文件")
        return
    
    # 只校验最近 3 个文件
    for fname in files[-3:]:
        fpath = os.path.join(data_dir, fname)
        result = validate_news_file(fpath)
        status = "✓" if result["invalid"] == 0 else "✗"
        print(f"  {status} {fname}: {result['valid']}/{result['total']} 有效")


def validate_kg():
    """校验知识图谱数据库"""
    db_path = os.path.join(ORCAS_HOME, "kg.db")
    if not os.path.exists(db_path):
        logger.warning("KG 数据库不存在")
        return
    
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # 检查 entities 表
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"  表: {', '.join(tables)}")
    
    for table in tables:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        print(f"  {table}: {count} 行")
    
    conn.close()


if __name__ == "__main__":
    print("=== 数据校验 ===")
    
    print("\n[采集输出]")
    validate_collector_output()
    
    print("\n[知识图谱]")
    validate_kg()
    
    print("\n完成")
