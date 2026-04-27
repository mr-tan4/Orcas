"""
kg_health_check.py — 知识盲区补全 (任务0.3)

Weekly scan of KG to identify sparse/isolated entities.
Generates a report appended to kg_blindspots_log.md.

Cron usage (weekly):
  python3 analysis/gap_detection.py
"""

import json
import os
import sqlite3
from datetime import datetime

import os
ORCAS_HOME = os.environ.get("ORCAS_HOME", os.path.expanduser("~/.orcas"))
DB_PATH = os.path.join(ORCAS_HOME, "kg.db")
LOG_PATH = os.path.join(ORCAS_HOME, "logs/gap_detection.md")

# 实体类型中文名
TYPE_CN = {
    "company": "组织/公司",
    "person": "人物",
    "product": "产品",
    "technology": "技术",
    "concept": "概念",
    "country": "国家/地区",
    "event": "事件",
    "policy": "政策",
}

# 缺失关系建议模板
RELATION_SUGGESTIONS = {
    "company": ["founded_by", "competes_with", "part_of", "based_in", "invested_in"],
    "person": ["founded_by", "part_of", "based_in"],
    "product": ["part_of", "competes_with", "related_to"],
    "technology": ["related_to", "part_of", "predecessor_of"],
    "country": ["based_in", "related_to"],
    "concept": ["related_to"],
    "event": ["related_to", "predecessor_of"],
}


def analyze_db(db):
    """分析KG健康状况"""
    print("  📊 计算平均关系数...")

    # 计算每个实体的关系数（作为source）
    avg_row = db.execute("""
        SELECT AVG(cnt) FROM (
            SELECT COUNT(*) as cnt
            FROM relations
            WHERE source_type = 'entity'
            GROUP BY source_id
        )
    """).fetchone()
    avg_relations = avg_row[0] or 0.0
    print(f"  📊 平均每个实体关系数: {avg_relations:.2f}")

    # 孤立节点：没有任何关系（作为source或target）
    print("  🔍 查找孤立节点...")
    isolated = db.execute("""
        SELECT e.id, e.name, e.type, e.source_count
        FROM entities e
        WHERE e.id NOT IN (
            SELECT source_id FROM relations WHERE source_type = 'entity'
            UNION
            SELECT target_id FROM relations WHERE target_type = 'entity'
        )
        ORDER BY e.source_count DESC
    """).fetchall()
    print(f"  🔍 孤立节点数: {len(isolated)}")

    # 对于孤立节点，检查它们是否出现在文档中（有 co-occurring 实体）
    isolated_details = []
    for ent_id, name, etype, src_count in isolated:
        # 对于孤立节点，通过 relations 表查它们关联的文档
        doc_count = db.execute("""
            SELECT COUNT(DISTINCT r.source_doc_id) FROM relations r
            WHERE r.source_doc_id IS NOT NULL
              AND ((r.source_type = 'entity' AND r.source_id = ?)
                OR (r.target_type = 'entity' AND r.target_id = ?))
        """, (ent_id, ent_id)).fetchone()[0]

        total_docs = doc_count
        isolated_details.append((ent_id, name, etype, src_count, total_docs))

    # 稀疏节点：关系数低于平均的30%，且排除source_count=1的新实体
    print("  🔍 查找稀疏节点...")
    threshold = avg_relations * 0.3
    sparse = db.execute("""
        SELECT e.id, e.name, e.type, COUNT(r.id) as rel_count, e.source_count
        FROM entities e
        LEFT JOIN relations r ON (r.source_type = 'entity' AND r.source_id = e.id)
        WHERE e.id IN (
            SELECT source_id FROM relations WHERE source_type = 'entity'
            UNION
            SELECT target_id FROM relations WHERE target_type = 'entity'
        )
        AND e.source_count > 1
        GROUP BY e.id
        HAVING rel_count < ?
        ORDER BY rel_count ASC
    """, (threshold,)).fetchall()
    print(f"  🔍 稀疏节点数: {len(sparse)}（阈值: {threshold:.1f}）")

    # 缺失关系类型统计
    print("  📈 分析关系分布...")
    rel_dist = db.execute("""
        SELECT relation_type, COUNT(*) as cnt
        FROM relations
        WHERE source_type = 'entity' AND target_type = 'entity'
        GROUP BY relation_type
        ORDER BY cnt DESC
    """).fetchall()

    return avg_relations, isolated_details, sparse, rel_dist


def generate_report(avg_relations, isolated_details, sparse, rel_dist):
    """生成盲区报告"""
    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [f"\n## 知识盲区报告 — {today}\n"]

    # === 孤立节点 ===
    lines.append("### 孤立节点（无任何关系）\n")
    if isolated_details:
        for ent_id, name, etype, src_count, doc_count in isolated_details[:20]:
            type_cn = TYPE_CN.get(etype, etype)
            if doc_count > 0:
                lines.append(f"- **{name}** ({type_cn}) — 出现在 {doc_count} 篇文档中，无关联实体")
            else:
                lines.append(f"- **{name}** ({type_cn}) — 无关联文档或实体")
        if len(isolated_details) > 20:
            lines.append(f"\n  ... 还有 {len(isolated_details) - 20} 个孤立节点未列出")
    else:
        lines.append("🎉 没有孤立节点！所有实体都有至少一个关系。\n")

    # === 稀疏节点 ===
    lines.append("\n### 稀疏节点（关系数低于平均的30%）\n")
    if sparse:
        for ent_id, name, etype, rel_count, src_count in sparse[:20]:
            type_cn = TYPE_CN.get(etype, etype)
            lines.append(f"- **{name}** ({type_cn}) — 当前关系数: {rel_count}, 平均: {avg_relations:.1f}")
        if len(sparse) > 20:
            lines.append(f"\n  ... 还有 {len(sparse) - 20} 个稀疏节点未列出")
    else:
        lines.append("🎉 没有特别稀疏的节点！\n")

    # === 建议补充方向 ===
    lines.append("\n### 建议补充方向\n")

    # 基于稀疏节点的类型给出建议
    sparse_types = {}
    for ent_id, name, etype, rel_count, src_count in sparse:
        sparse_types[etype] = sparse_types.get(etype, 0) + 1

    if sparse_types:
        lines.append("以下类型的实体关系较为稀疏，建议补充：\n")
        for etype, count in sorted(sparse_types.items(), key=lambda x: -x[1]):
            type_cn = TYPE_CN.get(etype, etype)
            suggestions = RELATION_SUGGESTIONS.get(etype, ["related_to"])
            lines.append(f"- **{type_cn}**（{count} 个实体）— 建议补充关系: {', '.join(suggestions)}")
    else:
        lines.append("当前图谱关系分布良好，无需特别补充。\n")

    # 关系分布概览
    lines.append("\n### 当前关系分布\n")
    if rel_dist:
        for rtype, cnt in rel_dist:
            lines.append(f"- `{rtype}`: {cnt} 条")
    lines.append("")

    lines.append(f"\n_报告生成时间: {timestamp}_\n")

    return "\n".join(lines)


def main():
    print(f"🏥 知识盲区检查 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   数据库: {DB_PATH}")

    db = sqlite3.connect(DB_PATH)

    try:
        avg_relations, isolated_details, sparse, rel_dist = analyze_db(db)

        report = generate_report(avg_relations, isolated_details, sparse, rel_dist)

        # 追加到日志
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(report)

        print(f"\n📄 报告已追加到 {LOG_PATH}")

        # 打印摘要
        print(f"\n{'='*50}")
        print(f"📊 健康检查摘要:")
        print(f"   平均关系数/实体: {avg_relations:.1f}")
        print(f"   孤立节点: {len(isolated_details)}")
        print(f"   稀疏节点: {len(sparse)}")
        if rel_dist:
            top_rel = rel_dist[0] if rel_dist else ("无", 0)
            print(f"   最常见关系: {top_rel[0]} ({top_rel[1]} 条)")

    finally:
        db.close()


if __name__ == "__main__":
    main()
