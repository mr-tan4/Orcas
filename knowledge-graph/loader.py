#!/usr/bin/env python3
"""
knowledge_graph_loader.py — 知识图谱数据导入器

将现有知识资产（新闻、Wiki事件、GitHub趋势）批量导入到知识图谱数据库，
并自动提取实体、建立关系。

用法:
  python3 knowledge_graph_loader.py [--reset] [--dry-run]

模式:
  --reset    清空数据库重新导入（慎用）
  --dry-run  只打印计划，不实际写入
"""

import json
import os
import sys
import hashlib
import re
import sqlite3
import argparse
import glob
from datetime import datetime
from pathlib import Path

# NER 快速级实体提取（loader.py 在 scripts/ 下，兄弟目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
try:
    from ner_fast import fast_ner
    HAVE_NER = True
except ImportError:
    HAVE_NER = False

# ===================== 配置 =====================
ORCAS_HOME = os.environ.get("ORCAS_HOME", os.path.expanduser("~/.orcas"))
BASE_DIR = ORCAS_HOME
DB_PATH = os.path.join(BASE_DIR, "kg.db")
# WIKI_DIR = os.path.join(BASE_DIR, "wiki", "events")  # 可选 Wiki 源
NEWS_DIR = os.path.join(BASE_DIR, "news")
RAW_DIR = os.path.join(BASE_DIR, "raw")
DATA_DIR = os.path.join(BASE_DIR, "data")
TAGGED_DIR = os.path.join(BASE_DIR, "data")  # tagged_news_*.json 在 data/ 子目录

# ===================== 实体提取器 =====================

# 已知的高价值实体（预置种子列表，后续自动扩充）
SEED_ENTITIES = {
    # AI/科技公司
    "DeepSeek": {"type": "company", "aliases": ["深度求索", "DeepSeek AI"]},
    "OpenAI": {"type": "company", "aliases": ["Open AI"]},
    "Anthropic": {"type": "company"},
    "Google": {"type": "company", "aliases": ["谷歌"]},
    "Microsoft": {"type": "company", "aliases": ["微软"]},
    "Meta": {"type": "company", "aliases": ["Facebook"]},
    "Apple": {"type": "company", "aliases": ["苹果"]},
    "NVIDIA": {"type": "company", "aliases": ["英伟达"]},
    "Tesla": {"type": "company"},
    "ByteDance": {"type": "company", "aliases": ["字节跳动", "抖音"]},
    "Alibaba": {"type": "company", "aliases": ["阿里巴巴", "阿里"]},
    "Tencent": {"type": "company", "aliases": ["腾讯"]},
    "Baidu": {"type": "company", "aliases": ["百度"]},
    "Huawei": {"type": "company", "aliases": ["华为"]},
    "NousResearch": {"type": "company", "aliases": ["Nous Research"]},
    # 人物
    "Sam Altman": {"type": "person"},
    "Elon Musk": {"type": "person"},
    "梁文锋": {"type": "person", "aliases": ["Liang Wenfeng"]},
    "Jensen Huang": {"type": "person", "aliases": ["黄仁勋"]},
    "Mark Zuckerberg": {"type": "person"},
    "Donald Trump": {"type": "person", "aliases": ["特朗普", "川普"]},
    "雷军": {"type": "person"},
    "马云": {"type": "person"},
    # 技术/产品
    "GPT-4": {"type": "product", "aliases": ["GPT4"]},
    "GPT-4o": {"type": "product"},
    "Claude": {"type": "product"},
    "Claude Sonnet 4": {"type": "product"},
    "Gemini": {"type": "product"},
    "LLaMA": {"type": "product", "aliases": ["Llama"]},
    "Hermes Agent": {"type": "product"},
    "AutoGPT": {"type": "product"},
    "Cursor": {"type": "product"},
    "Copilot": {"type": "product", "aliases": ["GitHub Copilot"]},
    "Devin": {"type": "product"},
    "Android": {"type": "product"},
    "iOS": {"type": "product"},
    "PyTorch": {"type": "technology"},
    "TensorFlow": {"type": "technology"},
    "Transformer": {"type": "technology", "aliases": ["Transformers"]},
    "Diffusion Model": {"type": "technology", "aliases": ["扩散模型"]},
    "RAG": {"type": "technology"},
    "Agent": {"type": "technology", "aliases": ["AI Agent", "AI代理"]},
    "LLM": {"type": "technology", "aliases": ["大语言模型", "Large Language Model"]},
    # 概念
    "AI": {"type": "concept", "aliases": ["人工智能", "Artificial Intelligence"]},
    "Machine Learning": {"type": "concept", "aliases": ["机器学习", "ML"]},
    "关税": {"type": "concept"},
    "芯片": {"type": "concept"},
    "开源": {"type": "concept", "aliases": ["open source", "OSS"]},
    "具身智能": {"type": "concept", "aliases": ["embodied intelligence"]},
    "人形机器人": {"type": "concept"},
    "自动驾驶": {"type": "concept", "aliases": ["FSD", "autonomous driving"]},
    "量子计算": {"type": "concept"},
    "卫星互联网": {"type": "concept"},
    "5G": {"type": "technology"},
    "6G": {"type": "technology"},
    "区块链": {"type": "concept", "aliases": ["blockchain"]},
    # 国家/地区
    "中国": {"type": "country", "aliases": ["China", "中国大陆"]},
    "美国": {"type": "country", "aliases": ["美国", "USA", "US"]},
    "欧盟": {"type": "country", "aliases": ["EU", "欧洲"]},
    "日本": {"type": "country"},
    "韩国": {"type": "country"},
    "伊朗": {"type": "country"},
    "以色列": {"type": "country"},
    "俄罗斯": {"type": "country", "aliases": ["Russia"]},
    "印度": {"type": "country"},
    "越南": {"type": "country"},
    "澳大利亚": {"type": "country"},
    # 产品/公司补充
    "特斯拉": {"type": "company", "aliases": ["Tesla"]},
    "SpaceX": {"type": "company"},
    "AMD": {"type": "company"},
    "Intel": {"type": "company", "aliases": ["英特尔"]},
    "高通": {"type": "company", "aliases": ["Qualcomm"]},
    "台积电": {"type": "company", "aliases": ["TSMC"]},
    "三星": {"type": "company", "aliases": ["Samsung"]},
    "小米": {"type": "company", "aliases": ["Xiaomi"]},
    "华为": {"type": "company", "aliases": ["Huawei"]},
    "鸿蒙": {"type": "product", "aliases": ["HarmonyOS"]},
    # 关键人物补充
    "普京": {"type": "person", "aliases": ["Putin"]},
    "拜登": {"type": "person", "aliases": ["Biden"]},
    "习近平": {"type": "person"},
    # GitHub生态
    "GitHub": {"type": "company"},
    "Rust": {"type": "technology"},
    "Python": {"type": "technology"},
    "JavaScript": {"type": "technology"},
    "TypeScript": {"type": "technology"},
    "Go": {"type": "technology"},
    "Kubernetes": {"type": "technology", "aliases": ["k8s"]},
    "Docker": {"type": "technology"},
    "PostgreSQL": {"type": "technology"},
    "Redis": {"type": "technology"},
}

# 实体匹配规则（title/content中出现的模式）
ENTITY_PATTERNS = [
    (r'[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\s(?:AI|Inc\.|Corp\.|LLC|Ltd)', 'company'),
    (r'(?:发布|推出|开源|收购|投资)\s*[：:]?\s*([^\s，。！？]{2,20})', 'product'),
]


def extract_entities(text, title=""):
    """从文本中提取已知实体，返回匹配到的实体名列表"""
    found = []
    combined = f"{title} {text}" if text else title

    # 种子列表精确匹配
    for name, info in SEED_ENTITIES.items():
        if name.lower() in combined.lower():
            found.append(name)
            continue
        # 别名匹配
        for alias in info.get("aliases", []):
            if alias.lower() in combined.lower():
                found.append(name)
                break

    # 去重
    return list(set(found))


# 低质量片段过滤（HTML/CSS残留、技术误匹配等）
LOW_QUALITY_FRAGMENTS = {
    'text-align', 'center', 'list-paddingleft', 'nbsp', 'src', 'href',
    'jpg', 'png', 'gif', 'img', 'div', 'span', 'class', 'style',
    'None', 'null', 'undefined', 'True', 'False',
}


def filter_low_quality_entities(entities):
    """过滤低质量实体匹配结果"""
    filtered = []
    for e in entities:
        e_lower = e.lower()
        # 排除过短
        if len(e) < 2:
            continue
        # 排除HTML/CSS片段（精确匹配 + 前缀匹配）
        if e_lower in LOW_QUALITY_FRAGMENTS:
            continue
        if any(e_lower.startswith(frag) for frag in {'text-align', 'list-paddingleft', 'nbsp', 'lt;'}):
            continue
        # 排除包含CSS选择器的
        if re.search(r'[{}:;]', e):
            continue
        # 排除纯数字/符号
        if re.match(r'^[\d\s\-_.,;:!@#$%^&*()+=/\\\[\]{}|`~<>]+$', e):
            continue
        filtered.append(e)
    return filtered


def extract_core_entities(text, title=""):
    """增强版实体提取：NER快速级 + 种子列表兜底 + 别名匹配"""
    combined = f"{title} {text}" if text else title
    found = []
    seen = set()

    # 1. 种子列表精确匹配（确保已知关键实体不丢失）
    for name, info in SEED_ENTITIES.items():
        if name.lower() in combined.lower():
            key = name.lower()
            if key not in seen:
                seen.add(key)
                found.append(name)
            continue
        for alias in info.get("aliases", []):
            if alias.lower() in combined.lower():
                key = f"alias_{alias.lower()}"
                if key not in seen:
                    seen.add(key)
                    found.append(name)
                break

    # 2. NER快速级（新发现实体，类型默认concept）
    if HAVE_NER:
        ner_results = fast_ner(title, text, max_candidates=15)
        for ent in ner_results:
            name = ent.get("name", "") if isinstance(ent, dict) else ent
            if not name or len(name) < 2:
                continue
            key = name.lower()
            if key not in seen:
                seen.add(key)
                found.append(name)

    # 3. 引号内专名（补充模式，非NER重叠）
    quoted = re.findall(r'[""]([^""]{2,30})[""]', combined)
    for q in quoted:
        q_key = q.lower()
        if q_key not in seen and len(q) > 2:
            seen.add(q_key)
            found.append(q)

    # 4. 过滤低质量
    found = filter_low_quality_entities(found)

    return list(dict.fromkeys(found))  # 保留顺序去重


# ===================== 数据加载器 =====================

def generate_id(prefix, key):
    """生成确定性ID"""
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    return f"{prefix}_{h}"


def load_tagged_news(db, dry_run=False, incremental=False):
    """导入最新打标新闻（tagged_news_*.json）
    
    incremental=True 时跳过已导入的文档（按doc_id去重）
    """
    tagged_files = sorted(glob.glob(os.path.join(TAGGED_DIR, "tagged_news_*.json")))
    print(f"  找到 {len(tagged_files)} 个 tagged_news 文件")

    if incremental:
        # 获取已导入的doc_id集合
        existing = set(row[0] for row in db.execute("SELECT id FROM documents WHERE type='news'").fetchall())
        print(f"  数据库已有 {len(existing)} 篇新闻文档")

    total_docs = 0
    total_ents = 0
    total_rels = 0

    for fpath in tagged_files:
        with open(fpath) as f:
            try:
                items = json.load(f)
            except:
                print(f"  ⚠ 跳过无法解析的文件: {fpath}")
                continue
        if not isinstance(items, list):
            continue

        for item in items:
            title = item.get("title", "")
            if not title:
                continue

            doc_id = generate_id("doc_news", item.get("url", title))
            
            # 增量模式下跳过已导入文档
            if incremental and doc_id in existing:
                continue

            content = item.get("summary", "") or item.get("content", "") or item.get("description", "") or ""
            tags = item.get("tags", []) or []
            publish_time = item.get("published", "") or item.get("publish_time", "")

            # 提取实体
            entities = extract_core_entities(content, title)

            if dry_run:
                total_docs += 1
                total_ents += len(entities)
                print(f"    [{total_docs}] {title[:50]}... 实体: {entities[:5]}")
                continue

            # 写入文档
            try:
                db.execute("""
                    INSERT OR REPLACE INTO documents 
                    (id, type, title, url, source, category, language, publish_time, collect_time, 
                     content, tags, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    doc_id, "news", title, item.get("url", ""),
                    item.get("source_name", "") or item.get("source", ""),
                    item.get("category", "uncategorized"),
                    item.get("language", "unknown"),
                    publish_time,
                    item.get("collect_time", ""),
                    content[:2000],  # 只存前2000字
                    json.dumps(tags, ensure_ascii=False),
                    item.get("confidence", 0.5)
                ))
                total_docs += 1
            except Exception as e:
                print(f"    ⚠ 写入文档失败 [{title[:30]}]: {e}")
                continue

            # 写入实体并建立关系
            for ent_name in entities:
                info = SEED_ENTITIES.get(ent_name, {})
                ent_type = info.get("type", "concept") if info else "concept"
                aliases = info.get("aliases", []) if info else []
                ent_id = generate_id("ent", ent_name)

                db.execute("""
                    INSERT OR REPLACE INTO entities 
                    (id, name, type, aliases, description, importance, first_seen, last_seen, source_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 
                            COALESCE((SELECT source_count + 1 FROM entities WHERE id = ?), 1))
                """, (
                    ent_id, ent_name, ent_type,
                    json.dumps(aliases, ensure_ascii=False),
                    f"自动从新闻中提取", 0.5,
                    publish_time or item.get("collect_time", "") or "unknown",
                    publish_time or item.get("collect_time", "") or "unknown",
                    ent_id
                ))

                # 实体-文档关系
                try:
                    db.execute("""
                        INSERT OR IGNORE INTO relations (id, source_type, source_id, target_type, target_id, relation_type, weight, source_doc_id)
                        VALUES (?, 'entity', ?, 'document', ?, 'mentions', 1.0, ?)
                    """, (generate_id("rel", f"entity_{ent_id}_mentions_{doc_id}"), ent_id, doc_id, doc_id))
                    total_rels += 1
                except:
                    pass

                total_ents += 1

            # 实体间共现关系（同一篇文档出现的实体之间）
            if len(entities) >= 2:
                for i in range(len(entities)):
                    for j in range(i+1, len(entities)):
                        e1_id = generate_id("ent", entities[i])
                        e2_id = generate_id("ent", entities[j])
                        try:
                            db.execute("""
                                INSERT OR IGNORE INTO relations (id, source_type, source_id, target_type, target_id, relation_type, weight, source_doc_id)
                                VALUES (?, 'entity', ?, 'entity', ?, 'co_occurrence', 0.3, ?)
                            """, (
                                generate_id("rel", f"{e1_id}_co_{e2_id}_in_{doc_id}"),
                                e1_id, e2_id, doc_id
                            ))
                        except:
                            pass

        print(f"  文件 {os.path.basename(fpath)}: {len(items)} 条")

    return total_docs, total_ents, total_rels


def load_wiki_events(db, dry_run=False):
    """导入Wiki事件页"""
    if not os.path.isdir(WIKI_DIR):
        print(f"  ⚠ Wiki events 目录不存在: {WIKI_DIR}")
        return 0, 0, 0

    files = os.listdir(WIKI_DIR)
    md_files = [f for f in files if f.endswith(".md")]
    print(f"  找到 {len(md_files)} 个 Wiki event 文件")

    total_docs = 0
    total_ents = 0
    total_rels = 0

    for fname in md_files:
        fpath = os.path.join(WIKI_DIR, fname)
        with open(fpath) as f:
            content = f.read()

        # 解析YAML frontmatter
        meta = {}
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_text = parts[1]
                body = parts[2]
                for line in yaml_text.strip().split("\n"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip().strip('"').strip("'")

        title = meta.get("title", fname.replace(".md", "").replace("Event_", "").replace("_", " "))
        created = meta.get("created", "")
        updated = meta.get("updated", "")
        tags_str = meta.get("tags", "")
        tags = []
        if tags_str:
            tags = [t.strip() for t in tags_str.strip("[]").split(",") if t.strip()]

        doc_id = generate_id("doc_wiki", fname)

        # 跳过空内容的Wiki页面（没有有价值的实体可提取）
        body_clean = body.strip().strip("#").strip("-\n ")
        if not body_clean or len(body_clean) < 50:
            # 仍然导入文档，但不提取实体
            try:
                db.execute("""
                    INSERT OR REPLACE INTO documents 
                    (id, type, title, url, source, category, language, publish_time, collect_time, 
                     content, tags, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    doc_id, "wiki_event", title, "",
                    "wiki_knowledge_base", "event", "zh-CN",
                    created or "",
                    updated or "",
                    f"[空内容页面] {fname}",
                    json.dumps(tags, ensure_ascii=False),
                    0.3  # 低置信度
                ))
                total_docs += 1
            except Exception as e:
                print(f"    ⚠ 写入wiki文档失败 [{title[:30]}]: {e}")
            continue

        # 提取实体
        entities = extract_core_entities(body, title)

        if dry_run:
            total_docs += 1
            print(f"    [{total_docs}] {title[:50]}... 实体: {entities[:5]}")
            continue

        try:
            db.execute("""
                INSERT OR REPLACE INTO documents 
                (id, type, title, url, source, category, language, publish_time, collect_time, 
                 content, tags, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                doc_id, "wiki_event", title, "",
                "wiki_knowledge_base", "event", "zh-CN",
                created or "",
                updated or "",
                body[:2000],
                json.dumps(tags, ensure_ascii=False),
                0.7
            ))
            total_docs += 1
        except Exception as e:
            print(f"    ⚠ 写入wiki文档失败 [{title[:30]}]: {e}")
            continue

        for ent_name in entities:
            info = SEED_ENTITIES.get(ent_name, {})
            ent_type = info.get("type", "concept") if info else "concept"
            aliases = info.get("aliases", []) if info else []
            ent_id = generate_id("ent", ent_name)

            db.execute("""
                INSERT OR REPLACE INTO entities 
                (id, name, type, aliases, description, importance, first_seen, last_seen, source_count)
                VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT MIN(first_seen) FROM entities WHERE id = ?), ?),
                        COALESCE((SELECT MAX(last_seen) FROM entities WHERE id = ?), ?),
                        COALESCE((SELECT source_count + 1 FROM entities WHERE id = ?), 1))
            """, (
                ent_id, ent_name, ent_type,
                json.dumps(aliases, ensure_ascii=False),
                f"从Wiki知识库提取", 0.5,
                ent_id, created or "unknown",
                ent_id, updated or created or "unknown",
                ent_id
            ))

            try:
                db.execute("""
                    INSERT OR IGNORE INTO relations (id, source_type, source_id, target_type, target_id, relation_type, weight, source_doc_id)
                    VALUES (?, 'entity', ?, 'document', ?, 'mentions', 1.0, ?)
                """, (generate_id("rel", f"wiki_{ent_id}_mentions_{doc_id}"), ent_id, doc_id, doc_id))
                total_rels += 1
            except:
                pass
            total_ents += 1

        # 实体间共现
        if len(entities) >= 2:
            for i in range(len(entities)):
                for j in range(i+1, len(entities)):
                    e1_id = generate_id("ent", entities[i])
                    e2_id = generate_id("ent", entities[j])
                    try:
                        db.execute("""
                            INSERT OR IGNORE INTO relations (id, source_type, source_id, target_type, target_id, relation_type, weight, source_doc_id)
                            VALUES (?, 'entity', ?, 'entity', ?, 'co_occurrence', 0.3, ?)
                        """, (
                            generate_id("rel", f"wiki_{e1_id}_co_{e2_id}_in_{doc_id}"),
                            e1_id, e2_id, doc_id
                        ))
                    except:
                        pass

    return total_docs, total_ents, total_rels


def update_entity_stats(db):
    """更新实体的统计信息（source_count, last_seen等）"""
    # 更新source_count
    db.execute("""
        UPDATE entities SET source_count = (
            SELECT COUNT(*) FROM relations 
            WHERE relations.source_type = 'entity' 
              AND relations.source_id = entities.id 
              AND relations.relation_type = 'mentions'
        )
    """)
    # 更新last_seen（从关联文档的最新时间）
    db.execute("""
        UPDATE entities SET last_seen = (
            SELECT MAX(documents.publish_time) FROM relations
            JOIN documents ON relations.target_id = documents.id
            WHERE relations.source_type = 'entity'
              AND relations.source_id = entities.id
              AND documents.publish_time != ''
              AND documents.publish_time IS NOT NULL
        )
    """)


def main():
    parser = argparse.ArgumentParser(description="知识图谱数据导入器")
    parser.add_argument("--reset", action="store_true", help="清空数据库重新导入")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写入")
    parser.add_argument("--incremental", action="store_true", help="增量模式，只导入新文档")
    args = parser.parse_args()

    print("=" * 60)
    print("📊 知识图谱数据导入器")
    print(f"   数据库: {DB_PATH}")
    print(f"   Dry-run: {args.dry_run}")
    print(f"   Reset: {args.reset}")
    print("=" * 60)

    if args.dry_run:
        print("\n🔍 DRY RUN 模式 — 不会实际写入数据\n")

    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=OFF")

    if args.reset and not args.dry_run:
        print("\n⚠ 清空数据库...")
        for table in ["relations", "documents", "entities"]:
            db.execute(f"DELETE FROM {table}")
        db.commit()
        print("   已清空\n")

    print("\n📰 步骤1: 导入打标新闻...")
    news_docs, news_ents, news_rels = load_tagged_news(db, args.dry_run, incremental=args.incremental)
    print(f"   新闻: {news_docs} 文档, {news_ents} 实体引用, {news_rels} 关系")

    if not args.incremental:
        print("\n📝 步骤2: 导入Wiki事件...")
        wiki_docs, wiki_ents, wiki_rels = load_wiki_events(db, args.dry_run)
        print(f"   Wiki: {wiki_docs} 文档, {wiki_ents} 实体引用, {wiki_rels} 关系")
    else:
        wiki_docs = wiki_ents = wiki_rels = 0
        print("\n📝 步骤2: 增量模式跳过Wiki导入")

    if not args.dry_run:
        print("\n📈 步骤3: 更新实体统计...")
        update_entity_stats(db)
        db.commit()

        # 步骤4: 趋势快照（增量模式才记录快照）
        if args.incremental:
            print("\n📸 步骤4: 记录趋势快照...")
            try:
                from trend_analysis import ensure_snapshot_table, cmd_snapshot
                ensure_snapshot_table(db)
                # 先检查今天是否已有快照
                today = datetime.now().strftime("%Y-%m-%d")
                existing = db.execute(
                    "SELECT id FROM trend_snapshots WHERE snapshot_date = ? ORDER BY id DESC LIMIT 1",
                    (today,)
                ).fetchone()
                if not existing:
                    entities = db.execute(
                        "SELECT id, name, source_count, last_seen FROM entities WHERE source_count > 0"
                    ).fetchall()
                    snapshot_data = {str(e[0]): {"name": e[1], "count": e[2], "last_seen": e[3] or ""} for e in entities}
                    db.execute(
                        "INSERT INTO trend_snapshots (snapshot_date, created_at, entity_snapshots) VALUES (?, ?, ?)",
                        (today, datetime.now().isoformat(), json.dumps(snapshot_data, ensure_ascii=False))
                    )
                    db.commit()
                    print(f"   已记录快照: {len(snapshot_data)} 实体")
                else:
                    # 已存在今日快照，追加一个新快照（同一天允许多个）
                    entities = db.execute(
                        "SELECT id, name, source_count, last_seen FROM entities WHERE source_count > 0"
                    ).fetchall()
                    snapshot_data = {str(e[0]): {"name": e[1], "count": e[2], "last_seen": e[3] or ""} for e in entities}
                    db.execute(
                        "INSERT INTO trend_snapshots (snapshot_date, created_at, entity_snapshots) VALUES (?, ?, ?)",
                        (today, datetime.now().isoformat(), json.dumps(snapshot_data, ensure_ascii=False))
                    )
                    db.commit()
                    print(f"   已追加快照: {len(snapshot_data)} 实体 (#{existing[0] + 1})")
            except ImportError as e:
                print(f"   ⚠ 趋势分析模块未就绪: {e}")
            except Exception as e:
                print(f"   ⚠ 快照记录失败: {e}")

        # 步骤5: 置信度评分（增量模式新文档评分）
        if args.incremental:
            print("\n📊 步骤5: 置信度评分...")
            try:
                import confidence_engine
                confidence_engine.DB_PATH = DB_PATH
                confidence_engine.cmd_incremental()
            except ImportError as e:
                print(f"   ⚠ 置信度引擎未就绪: {e}")
            except Exception as e:
                print(f"   ⚠ 置信度评分失败: {e}")

        # 统计结果
        counts = {}
        for table in ["entities", "documents", "relations"]:
            counts[table] = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        ent_types = db.execute("SELECT type, COUNT(*) FROM entities GROUP BY type ORDER BY COUNT(*) DESC").fetchall()
        doc_types = db.execute("SELECT type, COUNT(*) FROM documents GROUP BY type ORDER BY COUNT(*) DESC").fetchall()
        rel_types = db.execute("SELECT relation_type, COUNT(*) FROM relations GROUP BY relation_type ORDER BY COUNT(*) DESC").fetchall()

        print(f"\n{'='*60}")
        print(f"📊 导入完成统计")
        print(f"   实体: {counts['entities']} (类型: {dict(ent_types)})")
        print(f"   文档: {counts['documents']} (类型: {dict(doc_types)})")
        print(f"   关系: {counts['relations']} (类型: {dict(rel_types)})")
        print(f"\n   Top 10 实体:")
        top_ents = db.execute("""
            SELECT name, type, source_count, last_seen 
            FROM entities 
            WHERE source_count > 0 
            ORDER BY source_count DESC 
            LIMIT 10
        """).fetchall()
        for row in top_ents:
            print(f"     {row[0]:25s} | {row[1]:12s} | 出现 {row[2]:3d} 次 | 最近 {row[3] or 'N/A'}")

        print(f"\n{'='*60}")
        print("✅ 导入完成")

    db.close()


if __name__ == "__main__":
    main()
