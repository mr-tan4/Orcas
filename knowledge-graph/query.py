#!/usr/bin/env python3
"""
knowledge_graph_query.py — 知识图谱查询工具

用法:
  python3 knowledge_graph_query.py <query-type> [参数]

查询类型:
  timeline <entity-name>    — 某实体的时间线
  related <entity-name>     — 某实体的关联实体
  hot                      — 热度上升最快的实体
  search <keyword>          — 关键词搜索文档
  stats                    — 知识图谱统计
  doc <doc-id>             — 查看文档详情
  entity <entity-name>     — 查看实体详情
  graph <entity-name>       — 实体关系图谱（2跳）
"""

import sqlite3
import json
import sys
import os
from datetime import datetime

import os
ORCAS_HOME = os.environ.get("ORCAS_HOME", os.path.expanduser("~/.orcas"))
DB_PATH = os.path.join(ORCAS_HOME, "kg.db")


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def cmd_timeline(entity_name):
    """查询某个实体的时间线"""
    db = get_db()
    
    # 先找实体
    ent = db.execute(
        "SELECT * FROM entities WHERE name = ? OR ? IN (SELECT value FROM json_each(aliases))",
        (entity_name, entity_name)
    ).fetchone()
    
    if not ent:
        # 模糊搜索
        ents = db.execute(
            "SELECT * FROM entities WHERE name LIKE ? LIMIT 5",
            (f"%{entity_name}%",)
        ).fetchall()
        if ents:
            print(f"未精确匹配 '{entity_name}'，候选实体:")
            for e in ents:
                print(f"  {e['name']} ({e['type']}) — 出现 {e['source_count']} 次")
        else:
            print(f"知识库中未找到 '{entity_name}' 相关实体")
        db.close()
        return
    
    print(f"\n{'='*60}")
    print(f"📌 实体: {ent['name']} ({ent['type']})")
    print(f"   别名: {ent['aliases']}")
    print(f"   影响力: {ent['importance']} | 出现: {ent['source_count']} 次")
    print(f"   首次出现: {ent['first_seen']} | 最近: {ent['last_seen']}")
    print(f"   描述: {ent['description']}")
    print(f"{'='*60}")
    
    # 获取所有相关文档（按时间排序）
    docs = db.execute("""
        SELECT d.*, r.relation_type
        FROM documents d
        JOIN relations r ON r.target_id = d.id
        WHERE r.source_type = 'entity' 
          AND r.source_id = ?
          AND r.relation_type = 'mentions'
          AND d.publish_time != ''
          AND d.publish_time IS NOT NULL
        ORDER BY d.publish_time DESC
        LIMIT 30
    """, (ent['id'],)).fetchall()
    
    if not docs:
        # 也查一下没有 publish_time 的
        docs = db.execute("""
            SELECT d.*, r.relation_type
            FROM documents d
            JOIN relations r ON r.target_id = d.id
            WHERE r.source_type = 'entity' 
              AND r.source_id = ?
              AND r.relation_type = 'mentions'
            ORDER BY d.created_at DESC
            LIMIT 20
        """, (ent['id'],)).fetchall()
    
    if docs:
        print(f"\n📅 相关事件时间线 ({len(docs)} 条):\n")
        for i, doc in enumerate(docs, 1):
            time_str = doc['publish_time'] or doc['collect_time'] or doc['created_at']
            print(f"  [{i}] {time_str}")
            print(f"      {doc['title'][:60]}")
            print(f"      来源: {doc['source']} | 类型: {doc['type']}")
            print()
    else:
        print("  (暂无相关文档)")
    
    # 关联实体
    rel_ents = db.execute("""
        SELECT e.name, e.type, e.source_count, r2.relation_type
        FROM relations r1
        JOIN relations r2 ON (
            (r2.source_type = 'entity' AND r2.source_id = r1.target_id)
            OR (r2.target_type = 'entity' AND r2.target_id = r1.source_id)
        )
        JOIN entities e ON e.id = (
            CASE WHEN r2.source_type = 'entity' THEN r2.source_id ELSE r2.target_id END
        )
        WHERE r1.source_type = 'entity' AND r1.source_id = ?
          AND r1.relation_type = 'co_occurrence'
          AND e.id != ?
        GROUP BY e.id
        ORDER BY e.source_count DESC
        LIMIT 15
    """, (ent['id'], ent['id'])).fetchall()
    
    if rel_ents:
        print(f"\n🔗 共现实体 (Top 15):")
        for e in rel_ents:
            print(f"  {e['name']:20s} ({e['type']:10s}) 共现 {e['source_count']} 次")
    
    db.close()


def cmd_related(entity_name):
    """查询实体的关联关系图谱"""
    db = get_db()
    
    ent = db.execute(
        "SELECT * FROM entities WHERE name = ?",
        (entity_name,)
    ).fetchone()
    
    if not ent:
        print(f"实体 '{entity_name}' 未找到")
        db.close()
        return
    
    print(f"\n🔗 '{ent['name']}' 的关联图谱 (2跳):\n")
    
    # 第1跳：共现实体
    print(f"── 直接关联 ──")
    co_occur = db.execute("""
        SELECT e.name, e.type, e.source_count, COUNT(*) as strength
        FROM relations r
        JOIN entities e ON (
            (r.source_type = 'entity' AND r.source_id = e.id AND r.target_id = ?)
            OR (r.target_type = 'entity' AND r.target_id = e.id AND r.source_id = ?)
        )
        WHERE r.relation_type = 'co_occurrence'
          AND e.id != ?
        GROUP BY e.id
        ORDER BY strength DESC
        LIMIT 20
    """, (ent['id'], ent['id'], ent['id'])).fetchall()
    
    if co_occur:
        for e in co_occur:
            print(f"  ── {e['name']} ({e['type']}, 关联强度: {e['strength']})")
    else:
        print("  (暂无共现实体)")
    
    # 第2跳：共现的共现
    print(f"\n── 间接关联 (2跳) ──")
    indirect = db.execute("""
        SELECT e.name, e.type, e.source_count, COUNT(*) as strength
        FROM relations r1
        JOIN relations r2 ON r1.target_id = r2.source_id 
                           OR r1.source_id = r2.target_id
        JOIN entities e ON e.id = (
            CASE WHEN r2.source_type = 'entity' AND r2.source_id != ? THEN r2.source_id
                 WHEN r2.target_type = 'entity' AND r2.target_id != ? THEN r2.target_id
            END
        )
        WHERE r1.source_type = 'entity' AND r1.source_id = ?
          AND r1.relation_type = 'co_occurrence'
          AND r2.relation_type = 'co_occurrence'
          AND e.id != ?
          AND e.id NOT IN (
              SELECT CASE WHEN r3.source_type = 'entity' THEN r3.source_id ELSE r3.target_id END
              FROM relations r3
              WHERE (r3.source_type = 'entity' AND r3.source_id = ?)
                 OR (r3.target_type = 'entity' AND r3.target_id = ?)
          )
        GROUP BY e.id
        ORDER BY strength DESC
        LIMIT 15
    """, (ent['id'], ent['id'], ent['id'], ent['id'], ent['id'], ent['id'])).fetchall()
    
    if indirect:
        for e in indirect:
            print(f"  ~~ {e['name']} ({e['type']}, 关联强度: {e['strength']})")
    else:
        print("  (暂无间接关联)")
    
    db.close()


def cmd_hot():
    """热实体排行榜"""
    db = get_db()
    
    # 按 source_count 降序
    print(f"\n🔥 热度实体排行榜 (按出现次数):\n")
    print(f"{'排名':>4} {'实体名':25s} {'类型':12s} {'出现次数':>8} {'最近出现':20s}")
    print(f"{'─'*4} {'─'*25} {'─'*12} {'─'*8} {'─'*20}")
    
    ents = db.execute("""
        SELECT * FROM entities 
        WHERE source_count > 0
        ORDER BY source_count DESC 
        LIMIT 30
    """).fetchall()
    
    for i, e in enumerate(ents, 1):
        last = (e['last_seen'] or "")[:20]
        print(f"{i:4d} {e['name']:25s} {e['type']:12s} {e['source_count']:8d} {last:20s}")
    
    db.close()


def cmd_search(keyword):
    """关键词搜索文档"""
    db = get_db()
    
    docs = db.execute("""
        SELECT id, title, type, source, publish_time, tags
        FROM documents
        WHERE title LIKE ? OR content LIKE ?
        ORDER BY publish_time DESC
        LIMIT 20
    """, (f"%{keyword}%", f"%{keyword}%")).fetchall()
    
    if docs:
        print(f"\n🔍 搜索 '{keyword}': 找到 {len(docs)} 条结果\n")
        for d in docs:
            tags_str = ""
            try:
                tags_list = json.loads(d['tags'])
                tags_str = f" [{', '.join(tags_list[:3])}]"
            except:
                pass
            print(f"  [{d['type']:11s}] {d['title'][:60]}")
            print(f"           {d['source']} | {d['publish_time'] or 'N/A'}{tags_str}")
            print()
    else:
        print(f"未找到包含 '{keyword}' 的文档")
    
    db.close()


def cmd_stats():
    """知识图谱统计"""
    db = get_db()
    
    print(f"\n📊 知识图谱统计\n")
    
    # 基础计数
    counts = {}
    for table in ["entities", "documents", "relations"]:
        counts[table] = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    
    print(f"  实体总数: {counts['entities']}")
    print(f"  文档总数: {counts['documents']}")
    print(f"  关系总数: {counts['relations']}")
    print()
    
    # 按类型
    ent_types = db.execute(
        "SELECT type, COUNT(*) FROM entities GROUP BY type ORDER BY COUNT(*) DESC"
    ).fetchall()
    print(f"  实体类型分布:")
    for t, c in ent_types:
        bar = "█" * (c // 5)
        print(f"    {t:12s} {c:4d} {bar}")
    
    doc_types = db.execute(
        "SELECT type, COUNT(*) FROM documents GROUP BY type ORDER BY COUNT(*) DESC"
    ).fetchall()
    print(f"\n  文档类型分布:")
    for t, c in doc_types:
        bar = "█" * (c // 10)
        print(f"    {t:12s} {c:4d} {bar}")
    
    rel_types = db.execute(
        "SELECT relation_type, COUNT(*) FROM relations GROUP BY relation_type ORDER BY COUNT(*) DESC"
    ).fetchall()
    print(f"\n  关系类型分布:")
    for t, c in rel_types:
        print(f"    {t:15s} {c}")
    
    # 时间覆盖
    dates = db.execute(
        "SELECT MIN(publish_time) as earliest, MAX(publish_time) as latest FROM documents WHERE publish_time != '' AND publish_time IS NOT NULL"
    ).fetchone()
    if dates and dates['earliest']:
        print(f"\n  时间覆盖: {dates['earliest'][:10]} ~ {dates['latest'][:10]}")
    
    # 有实体的文档比例
    has_entities = db.execute("""
        SELECT COUNT(DISTINCT target_id) FROM relations WHERE relation_type = 'mentions'
    """).fetchone()[0]
    print(f"  标记实体的文档: {has_entities}/{counts['documents']} ({has_entities/max(counts['documents'],1)*100:.0f}%)")
    
    db.close()


def cmd_entity_detail(entity_name):
    """查看实体详情"""
    db = get_db()
    
    ent = db.execute(
        "SELECT * FROM entities WHERE name = ?", (entity_name,)
    ).fetchone()
    
    if not ent:
        print(f"实体 '{entity_name}' 未找到")
        db.close()
        return
    
    print(f"\n📌 实体详情\n")
    print(f"  ID:       {ent['id']}")
    print(f"  名称:     {ent['name']}")
    print(f"  类型:     {ent['type']}")
    print(f"  别名:     {ent['aliases']}")
    print(f"  描述:     {ent['description']}")
    print(f"  重要性:   {ent['importance']}")
    print(f"  首次:     {ent['first_seen']}")
    print(f"  最近:     {ent['last_seen']}")
    print(f"  出现次数: {ent['source_count']}")
    print(f"  元数据:   {ent['metadata']}")
    
    db.close()


def cmd_graph(entity_name):
    """实体关系图（ASCII版）"""
    db = get_db()
    
    ent = db.execute(
        "SELECT * FROM entities WHERE name = ?", (entity_name,)
    ).fetchone()
    
    if not ent:
        print(f"实体 '{entity_name}' 未找到")
        db.close()
        return
    
    print(f"\n🌐 '{ent['name']}' 的关系图\n")
    
    # 找到共现实体及其强度
    rels = db.execute("""
        SELECT e.name, e.type, COUNT(*) as strength
        FROM relations r
        JOIN entities e ON (
            WHEN r.source_type = 'entity' AND r.source_id = e.id THEN r.source_id
            WHEN r.target_type = 'entity' AND r.target_id = e.id THEN r.target_id
        )
    """).fetchall()
    
    # 获取共现关系
    co_occur = db.execute("""
        SELECT 
            CASE WHEN r.source_type = 'entity' AND r.source_id != ? THEN r.source_id
                 WHEN r.target_type = 'entity' AND r.target_id != ? THEN r.target_id
            END as related_entity_id,
            e.name, e.type, e.source_count,
            COUNT(*) as strength
        FROM relations r
        JOIN entities e ON e.id = (
            CASE WHEN r.source_type = 'entity' AND r.source_id != ? THEN r.source_id
                 WHEN r.target_type = 'entity' AND r.target_id != ? THEN r.target_id
            END
        )
        WHERE (r.source_type = 'entity' AND (r.source_id = ? OR r.target_id = ?))
          AND r.relation_type = 'co_occurrence'
          AND e.id != ?
        GROUP BY e.id
        ORDER BY strength DESC
        LIMIT 10
    """, (ent['id'], ent['id'], ent['id'], ent['id'], ent['id'], ent['id'])).fetchall()
    
    # 输出ASCII关系图
    print(f"              ┌──────────────────┐")
    print(f"              │ {ent['name']:16s} │")
    print(f"              │ ({ent['type']})          │")
    print(f"              └──────┬───────────┘")
    print(f"                     │")
    
    if not co_occur:
        print("           (暂无关联实体)")
    else:
        for i, e in enumerate(co_occur):
            is_last = (i == len(co_occur) - 1)
            conn = "└──" if is_last else "├──"
            print(f"           {conn}─── {e['name']:18s} ({e['type']:8s}) 强度:{e['strength']}")
    
    db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    
    cmd = sys.argv[1]
    
    commands = {
        "timeline": cmd_timeline,
        "related": cmd_related,
        "hot": cmd_hot,
        "search": cmd_search,
        "stats": cmd_stats,
        "entity": cmd_entity_detail,
        "graph": cmd_graph,
    }
    
    if cmd in commands:
        if cmd in ("hot", "stats"):
            commands[cmd]()
        elif len(sys.argv) >= 3:
            commands[cmd](" ".join(sys.argv[2:]))
        else:
            print(f"用法: python3 {sys.argv[0]} {cmd} <参数>")
    else:
        print(f"未知命令: {cmd}")
        print(f"可用命令: {', '.join(commands.keys())}")
