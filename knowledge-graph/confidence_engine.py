#!/usr/bin/env python3
"""
confidence_engine.py — 知识图谱置信度评分引擎

三加权评分模型:
  Confidence = α×SourceReliability + β×Freshness + γ×Coverage
  默认权重: α=0.5, β=0.3, γ=0.2

用法:
  python3 confidence_engine.py --incremental   # 增量评分（新文档）
  python3 confidence_engine.py --recalc        # 全库重算
  python3 confidence_engine.py --report        # 生成置信度概况报告
  python3 confidence_engine.py --entity-scores # 实体置信度列表
"""

import sqlite3
import json
import os
import sys
import argparse
from datetime import datetime, timedelta

ORCAS_HOME = os.environ.get("ORCAS_HOME", os.path.expanduser("~/.orcas"))
DB_PATH = os.path.join(ORCAS_HOME, "kg.db")

# ===================== 信源可靠性评级 =====================

# 来源 → (等级, 基础分, 说明)
SOURCE_RELIABILITY = {
    # A级 — 国际权威媒体
    "BBC":           (0.95, "A, international broadcast authority"),
    "BBC News":      (0.95, "A, international broadcast authority"),
    "TechCrunch":    (0.95, "A, tech startup authority"),
    "Bloomberg":     (0.95, "A, financial news authority"),
    "CNBC":          (0.95, "A, business news authority"),
    
    # B级 — 专业科技媒体
    "Ars Technica":  (0.85, "B, deep tech journalism"),
    "The Verge":     (0.85, "B, tech culture"),
    "Wired":         (0.85, "B, tech analysis"),
    
    # C级 — 中文原创新闻
    "chinanews_finance":  (0.75, "C, China News - finance original"),
    "chinanews_world":    (0.75, "C, China News - world original"),
    "chinanews_politics": (0.75, "C, China News - politics original"),
    "Hacker News":   (0.75, "C, tech community aggregation"),
    "HackerNews":    (0.75, "C, tech community aggregation"),
    
    # D级 — 聚合/转载类
    "ithome_tech":    (0.45, "D, Chinese tech aggregation"),
    "github_trending": (0.45, "D, auto-collected OSS metrics"),
    
    # E级 — 静态/低质量
    "wiki_knowledge_base": (0.25, "E, static wiki events"),
}

DEFAULT_RELIABILITY = 0.50  # 未列出的来源

# ===================== 时效新鲜度 =====================

def freshness_score(publish_time_str, now=None):
    """
    按时间衰减计算新鲜度。
    - 最近 7 天: 1.0 ~ 0.8
    - 7~30 天: 0.8 ~ 0.5
    - 30天以上: 0.3
    """
    if not publish_time_str or publish_time_str.strip() == "":
        return 0.3
    
    if now is None:
        now = datetime.now()
    
    # 尝试多种时间格式解析
    pt = _parse_time(publish_time_str)
    if pt is None:
        return 0.3  # 无法解析 = 低可信
    
    days_ago = (now - pt).total_seconds() / 86400.0
    
    if days_ago < 0:
        return 1.0  # 未来时间 = 假设最高
    elif days_ago <= 7:
        return 1.0 - 0.2 * (days_ago / 7.0)  # 1.0 ~ 0.8
    elif days_ago <= 30:
        return 0.8 - 0.3 * ((days_ago - 7) / 23.0)  # 0.8 ~ 0.5
    else:
        return max(0.3, 0.5 - 0.2 * ((days_ago - 30) / 100.0))  # 缓慢衰减到0.3


# GMT/时区格式：Wed, 8 Apr 2026 06:19:08 +0800
# ISO格式：2026-04-24T16:33:27
# 中文格式：2026年4月8日
def _parse_time(s):
    """尝试多种时间格式"""
    import re
    s = s.strip()
    
    # ISO: 2026-04-24T16:33:27
    try:
        from datetime import timezone
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]:
            try:
                return datetime.strptime(s[:19], fmt)
            except:
                pass
    except:
        pass
    
    # GMT: Wed, 8 Apr 2026 06:19:08 +0800
    try:
        # 去掉时区部分
        clean = re.sub(r'\s+\+?\d{4}$', '', s)
        clean = re.sub(r'^\w+,\s*', '', clean)  # 去掉 Weekday,
        return datetime.strptime(clean.strip(), "%d %b %Y %H:%M:%S")
    except:
        pass
    
    # 中文: 2026年4月8日
    try:
        clean = s.replace('年', '-').replace('月', '-').replace('日', '')
        return datetime.strptime(clean[:10], "%Y-%m-%d")
    except:
        pass
    
    return None


# ===================== 交叉覆盖评分 =====================

def coverage_score(db, title, source_name, entity_names=None):
    """
    交叉覆盖评分：同一件事被多少独立信源报道。
    - 用标题相似度 + 实体重叠 匹配
    - 3+ 独立源 = 满分 1.0
    """
    # 简单策略：标题关键词匹配（取前5个非停用词）
    import re
    stop_words = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', 
                  '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着',
                  '没有', '看', '好', '自己', '这', '他', '她', '它', '们'}
    
    words = re.findall(r'[\w]+', title.lower())
    keywords = [w for w in words if len(w) > 1 and w not in stop_words][:5]
    
    if not keywords:
        return 0.5
    
    # 找标题包含这些关键词的其他文档
    like_clauses = " OR ".join([f"title LIKE '%{kw}%'" for kw in keywords])
    
    try:
        matches = db.execute(f"""
            SELECT source, COUNT(*) as cnt
            FROM documents
            WHERE ({like_clauses})
              AND source != ?
              AND id != ''
            GROUP BY source
        """, (source_name,)).fetchall()
        
        # 统计独立信源数（去重）
        unique_sources = len(matches)
        
        if unique_sources >= 3:
            return 1.0
        elif unique_sources == 2:
            return 0.8
        elif unique_sources == 1:
            return 0.6
        else:
            return 0.3
    except:
        return 0.5


# ===================== 综合评分 =====================

def calculate_document_score(db, doc_id, title, source_name, publish_time, entity_names=None):
    """计算单篇文档的综合置信度"""
    
    # 1. 信源可靠性
    source_score = SOURCE_RELIABILITY.get(source_name, (DEFAULT_RELIABILITY, "unrated"))[0]
    
    # 2. 时效新鲜度
    freshness = freshness_score(publish_time)
    
    # 3. 交叉覆盖
    coverage = coverage_score(db, title, source_name, entity_names)
    
    # 加权
    alpha, beta, gamma = 0.5, 0.3, 0.2
    confidence = alpha * source_score + beta * freshness + gamma * coverage
    
    # 硬上限/下限
    confidence = min(1.0, max(0.1, confidence))
    
    return round(confidence, 4), {
        "source_score": source_score,
        "freshness": freshness,
        "coverage": coverage,
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
    }


# ===================== 实体置信度 =====================

def calculate_entity_confidence(db, entity_id, entity_name):
    """
    实体置信度 = 加权平均的信源覆盖 + 时效衰减
    
    逻辑：
    - 该实体出现在多少份高置信度文档中
    - 该实体的高置信度信源覆盖度
    - 最近一次出现时间衰减
    """
    ent = db.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if not ent:
        return 0.3
    
    # 找到所有包含该实体的文档及其置信度
    docs = db.execute("""
        SELECT d.confidence, d.source, d.publish_time
        FROM documents d
        JOIN relations r ON r.target_id = d.id
        WHERE r.source_type = 'entity' AND r.source_id = ?
          AND r.relation_type = 'mentions'
          AND d.confidence IS NOT NULL
    """, (entity_id,)).fetchall()
    
    if not docs:
        return 0.3
    
    # 1. 文档置信度加权平均
    avg_doc_conf = sum(d['confidence'] for d in docs) / len(docs)
    
    # 2. 独立信源覆盖
    sources = set(d['source'] for d in docs)
    source_coverage = min(1.0, len(sources) / 3.0)
    
    # 3. 时效衰减（基于 last_seen）
    last_seen = ent['last_seen']
    freshness = freshness_score(last_seen) if last_seen else 0.3
    
    # 综合
    confidence = 0.4 * avg_doc_conf + 0.3 * source_coverage + 0.3 * freshness
    return round(min(1.0, max(0.1, confidence)), 4)


# ===================== 引擎命令 =====================

def ensure_log_table(db):
    """确保置信度日志表存在"""
    db.execute("""
        CREATE TABLE IF NOT EXISTS confidence_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL,      -- 'document' | 'entity'
            target_id TEXT NOT NULL,
            score REAL NOT NULL,
            details TEXT,                    -- JSON 明细
            created_at TEXT NOT NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_conf_log_target ON confidence_log(target_type, target_id)")
    db.commit()


def cmd_incremental():
    """增量评分：只处理 confidence IS NULL 的文档"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    ensure_log_table(db)
    now = datetime.now()
    
    # 找所有未评分的文档
    pending = db.execute("""
        SELECT id, title, source, publish_time FROM documents 
        WHERE confidence IS NULL
    """).fetchall()
    
    if not pending:
        # 可能所有文档都有confidence了，找最近更新的重新评
        print("  所有文档已有评分，检查最近更新的文档...")
        pending = db.execute("""
            SELECT id, title, source, publish_time FROM documents 
            ORDER BY created_at DESC LIMIT 10
        """).fetchall()
    
    scored = 0
    errors = 0
    for doc in pending:
        try:
            # 找该文档的实体（用于覆盖评分）
            entities = db.execute("""
                SELECT e.name FROM entities e
                JOIN relations r ON r.source_type = 'entity' AND r.source_id = e.id
                WHERE r.target_id = ? AND r.relation_type = 'mentions'
            """, (doc['id'],)).fetchall()
            ent_names = [e['name'] for e in entities]
            
            score, details = calculate_document_score(
                db, doc['id'], doc['title'], doc['source'], 
                doc['publish_time'], ent_names
            )
            
            db.execute(
                "UPDATE documents SET confidence = ? WHERE id = ?",
                (score, doc['id'])
            )
            db.execute(
                "INSERT INTO confidence_log (target_type, target_id, score, details, created_at) VALUES (?, ?, ?, ?, ?)",
                ("document", doc['id'], score, json.dumps(details, ensure_ascii=False), now.isoformat())
            )
            scored += 1
        except Exception as e:
            print(f"  ⚠ 评分失败 [{doc['title'][:30]}]: {e}")
            errors += 1
    
    db.commit()
    
    # 实体评分（只重算最近活跃的）
    print(f"\n  计算实体置信度...")
    ents = db.execute("""
        SELECT id, name FROM entities WHERE source_count > 0
        ORDER BY source_count DESC LIMIT 200
    """).fetchall()
    
    ent_scored = 0
    for ent in ents:
        try:
            score = calculate_entity_confidence(db, ent['id'], ent['name'])
            db.execute(
                "INSERT INTO confidence_log (target_type, target_id, score, details, created_at) VALUES (?, ?, ?, ?, ?)",
                ("entity", str(ent['id']), score, json.dumps({"method": "weighted_avg"}, ensure_ascii=False), now.isoformat())
            )
            ent_scored += 1
        except:
            pass
    
    db.commit()
    
    print(f"\n✅ 增量评分完成")
    print(f"  文档评分: {scored} (失败 {errors})")
    print(f"  实体评分: {ent_scored}")
    
    # 输出概要
    avg_new = db.execute("SELECT AVG(confidence) FROM documents WHERE confidence IS NOT NULL").fetchone()[0]
    low_conf = db.execute("SELECT COUNT(*) FROM documents WHERE confidence < 0.4").fetchone()[0]
    high_conf = db.execute("SELECT COUNT(*) FROM documents WHERE confidence >= 0.7").fetchone()[0]
    print(f"  全库平均置信度: {avg_new:.3f}")
    print(f"  低置信度 (<0.4): {low_conf}")
    print(f"  高置信度 (>=0.7): {high_conf}")
    
    db.close()


def cmd_recalc():
    """全库重算所有文档和实体的置信度"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    ensure_log_table(db)
    now = datetime.now()
    
    print(f"\n🔄 全库置信度重算 (开始: {now.isoformat()[:19]})")
    print(f"{'='*60}")
    
    # 步骤1: 先算文档独立覆盖（需要所有文档的置信度都不依赖其他文档）
    print("\n📄 步骤1: 文档置信度评分...")
    docs = db.execute("""
        SELECT id, title, source, publish_time FROM documents
    """).fetchall()
    
    scored = 0
    for doc in docs:
        try:
            entities = db.execute("""
                SELECT e.name FROM entities e
                JOIN relations r ON r.source_type = 'entity' AND r.source_id = e.id
                WHERE r.target_id = ? AND r.relation_type = 'mentions'
            """, (doc['id'],)).fetchall()
            ent_names = [e['name'] for e in entities]
            
            score, details = calculate_document_score(
                db, doc['id'], doc['title'], doc['source'],
                doc['publish_time'], ent_names
            )
            
            db.execute("UPDATE documents SET confidence = ? WHERE id = ?", (score, doc['id']))
            scored += 1
        except Exception as e:
            pass
    
    db.commit()
    print(f"  已更新 {scored}/{len(docs)} 文档")
    
    # 步骤2: 实体置信度
    print("\n🔤 步骤2: 实体置信度评分...")
    ents = db.execute("""
        SELECT id, name FROM entities WHERE source_count > 0
    """).fetchall()
    
    ent_scored = 0
    for ent in ents:
        try:
            score = calculate_entity_confidence(db, ent['id'], ent['name'])
            # 记录日志（只保留最新）
            db.execute(
                "INSERT INTO confidence_log (target_type, target_id, score, details, created_at) VALUES (?, ?, ?, ?, ?)",
                ("entity", str(ent['id']), score, json.dumps({"method": "weighted_avg"}, ensure_ascii=False), now.isoformat())
            )
            ent_scored += 1
        except:
            pass
    
    db.commit()
    print(f"  已计算 {ent_scored}/{len(ents)} 实体")
    
    # 统计结果
    print(f"\n📊 重算结果")
    print(f"{'='*60}")
    
    stats = db.execute("""
        SELECT 
            COUNT(*) as total,
            ROUND(AVG(confidence), 4) as avg_conf,
            ROUND(MIN(confidence), 4) as min_conf,
            ROUND(MAX(confidence), 4) as max_conf
        FROM documents
    """).fetchone()
    print(f"  文档: {stats['total']} | 均值 {stats['avg_conf']} | 范围 [{stats['min_conf']}~{stats['max_conf']}]")
    
    # 按置信度分级
    levels = db.execute("""
        SELECT 
            CASE 
                WHEN confidence >= 0.8 THEN 'A (>=0.8)'
                WHEN confidence >= 0.6 THEN 'B (0.6~0.8)'
                WHEN confidence >= 0.4 THEN 'C (0.4~0.6)'
                ELSE 'D (<0.4)'
            END as level,
            COUNT(*) as cnt,
            ROUND(AVG(confidence), 4) as avg
        FROM documents
        GROUP BY level
        ORDER BY level
    """).fetchall()
    
    print(f"\n  置信度分布:")
    for l in levels:
        bar = "█" * (l['cnt'] // 10)
        print(f"    {l['level']:15s} {l['cnt']:4d} docs (avg {l['avg']}) {bar}")
    
    # 信源平均置信度
    print(f"\n  信源平均置信度:")
    src_stats = db.execute("""
        SELECT source, COUNT(*) as cnt, ROUND(AVG(confidence), 4) as avg_conf
        FROM documents
        GROUP BY source
        ORDER BY avg_conf DESC
    """).fetchall()
    for s in src_stats:
        print(f"    {s['source']:25s} {s['cnt']:4d} docs | avg {s['avg_conf']}")
    
    db.close()
    print(f"\n✅ 全库重算完成")


def cmd_report():
    """置信度概况报告"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    
    print(f"\n📊 置信度概况报告 ({datetime.now().isoformat()[:19]})\n")
    print(f"{'='*70}")
    
    # 文档置信度
    doc_stats = db.execute("""
        SELECT COUNT(*) as total,
               ROUND(AVG(confidence), 4) as avg,
               ROUND(MIN(confidence), 4) as min,
               ROUND(MAX(confidence), 4) as max,
               ROUND((SELECT confidence FROM documents ORDER BY confidence ASC LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM documents)), 4) as median
        FROM documents
    """).fetchone()
    
    print(f"📄 文档置信度")
    print(f"  总数: {doc_stats['total']}")
    print(f"  均值: {doc_stats['avg']} | 中位数: {doc_stats['median']}")
    print(f"  范围: [{doc_stats['min']} ~ {doc_stats['max']}]")
    print()
    
    # 分级
    levels = db.execute("""
        SELECT 
            CASE 
                WHEN confidence >= 0.8 THEN 'A'
                WHEN confidence >= 0.6 THEN 'B'
                WHEN confidence >= 0.4 THEN 'C'
                ELSE 'D'
            END as level,
            COUNT(*) as cnt
        FROM documents
        GROUP BY level
        ORDER BY level
    """).fetchall()
    
    print(f"  分级:")
    total = sum(l['cnt'] for l in levels)
    for l in levels:
        pct = l['cnt'] / total * 100
        bar = "█" * max(1, int(l['cnt'] / 20))
        print(f"    {l['level']}级  {l['cnt']:4d} ({pct:5.1f}%) {bar}")
    print()
    
    # 信源排名
    print(f"📡 信源评级（实际得分）:")
    srcs = db.execute("""
        SELECT source, COUNT(*) as cnt, ROUND(AVG(confidence), 3) as avg_conf,
               ROUND(AVG(CASE WHEN confidence < 0.4 THEN 1 ELSE 0 END), 3) as low_ratio
        FROM documents
        GROUP BY source
        ORDER BY avg_conf DESC
    """).fetchall()
    
    print(f"{'来源':25s} {'文档数':>6} {'平均置信度':>10} {'低信占比':>8}")
    print(f"{'─'*25} {'─'*6} {'─'*10} {'─'*8}")
    for s in srcs:
        print(f"{s['source']:25s} {s['cnt']:6d} {s['avg_conf']:10.3f} {s['low_ratio']:7.1%}")
    print()
    
    # 低置信度文档（Top 10 最差的）
    print(f"⚠ 低置信度文档 Top 10:")
    low = db.execute("""
        SELECT title, source, confidence, publish_time 
        FROM documents 
        ORDER BY confidence ASC 
        LIMIT 10
    """).fetchall()
    for i, d in enumerate(low, 1):
        print(f"  {i:2d}. [{d['confidence']:.2f}] {d['title'][:50]}")
        print(f"       {d['source']} | {d['publish_time'][:30] if d['publish_time'] else 'N/A'}")
    
    db.close()


def cmd_entity_scores(top_n=30):
    """实体置信度排名"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    
    print(f"\n🔤 实体置信度 Top {top_n}\n")
    
    # 从 confidence_log 获取最新实体评分
    ents = db.execute("""
        SELECT cl.score, e.name, e.type, e.source_count, e.last_seen
        FROM confidence_log cl
        JOIN entities e ON e.id = CAST(cl.target_id AS INTEGER)
        WHERE cl.target_type = 'entity'
          AND cl.id IN (SELECT MAX(id) FROM confidence_log WHERE target_type = 'entity' GROUP BY target_id)
        ORDER BY cl.score ASC
        LIMIT ?
    """, (top_n,)).fetchall()
    
    if not ents:
        print("  暂无实体置信度数据，请先运行 --incremental 或 --recalc")
        db.close()
        return
    
    print(f"{'排名':>4} {'实体':25s} {'置信度':>6} {'出现':>5} {'最近':24s}")
    print(f"{'─'*4} {'─'*25} {'─'*6} {'─'*5} {'─'*24}")
    for i, e in enumerate(ents, 1):
        last = (e['last_seen'] or "")[:24]
        print(f"{i:4d} {e['name']:25s} {e['score']:6.2f} {e['source_count']:5d} {last:24s}")
    
    # Top 10 高置信度
    print(f"\n🔝 高置信度实体 Top 10:")
    high = db.execute("""
        SELECT cl.score, e.name, e.type, e.source_count
        FROM confidence_log cl
        JOIN entities e ON e.id = CAST(cl.target_id AS INTEGER)
        WHERE cl.target_type = 'entity'
          AND cl.id IN (SELECT MAX(id) FROM confidence_log WHERE target_type = 'entity' GROUP BY target_id)
        ORDER BY cl.score DESC
        LIMIT 10
    """).fetchall()
    for i, e in enumerate(high, 1):
        print(f"  {i:2d}. {e['name']:25s} score={e['score']:.2f} ({e['source_count']}次)")
    
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="知识图谱置信度引擎")
    parser.add_argument("--incremental", action="store_true", help="增量评分")
    parser.add_argument("--recalc", action="store_true", help="全库重算")
    parser.add_argument("--report", action="store_true", help="置信度概况报告")
    parser.add_argument("--entity-scores", action="store_true", help="实体置信度列表")
    parser.add_argument("--top-n", type=int, default=30, help="实体列表数量")
    
    args = parser.parse_args()
    
    if args.recalc:
        cmd_recalc()
    elif args.report:
        cmd_report()
    elif args.entity_scores:
        cmd_entity_scores(args.top_n)
    else:
        # 默认增量模式
        cmd_incremental()
