#!/usr/bin/env python3
"""
thought_ingestion.py — 知识记忆摄入器

将用户的决策、判断、指令、探讨等 thoughts 摄入知识图谱，自动提取实体并建立关系。

消费场景:
  - CLI 手动输入:  python3 -m knowledge-graph.thought_ingestion --text "我觉得..."
  - 管道输入:      echo "决定了，用 DeepSeek v4-pro" | python3 -m knowledge-graph.thought_ingestion
  - Agent 调用:    python3 -m knowledge-graph.thought_ingestion --file /tmp/thought.json
  - 批量导入:      python3 -m knowledge-graph.thought_ingestion --batch thoughts.jsonl

用法:
  python3 -m knowledge-graph.thought_ingestion [--text "Message"] [--source "weixin|cli|api"]
                                              [--file path] [--batch path] [--dry-run]

分类规则:
  决策(0.95)  — "决定"、"就按"、"选"、"用这个"、"切到"、"确认"、"同意"、"就定"
  判断(0.90)  — "我觉得"、"我认为"、"关键在"、"问题在"、"短板"、"不如"、"更好"、"更优"
  指令(0.85)  — "需要"、"要做"、"安排"、"下一步"、"执行"、"搞"、"动手"
  探讨(0.70)  — "趋势"、"架构"、"设计"、"策略"、"对比"、"分析"、"评估"
  想法(0.50)  — 默认
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime


# ===================== 配置 =====================

ORCAS_HOME = os.environ.get("ORCAS_HOME", os.path.expanduser("~/.orcas"))
DB_PATH = os.path.join(ORCAS_HOME, "kg.db")

# 记忆分类关键词（与 HermesMemoryKG 保持一致）
CLASSIFICATION_RULES = [
    ("决策", 0.95, {"决定", "就按", "选", "用这个", "切到", "确认", "同意", "就定", "决定了"}),
    ("判断", 0.90, {"我觉得", "我认为", "关键在", "问题在", "短板", "不如", "更好", "更优"}),
    ("指令", 0.85, {"需要", "要做", "安排", "安排一下", "下一步", "执行", "搞", "动手", "做一下"}),
    ("探讨", 0.70, {"趋势", "架构", "方向", "设计", "策略", "对比", "分析", "评估"}),
]

# 个人实体（种子，可在 sources.yaml 外部化）
PERSONAL_ENTITIES = {
    "先生": ("person", ["robert", "Robert"], 0.95),
}

# 垃圾实体过滤
GARBAGE_NAMES = {
    'the', 'this', 'that', 'what', 'you', 'hermes', 'agent', 'yes', 'no',
    'ok', 'okay', 'got it', '好了', '好的', '明白', '知道',
    'weixin', 'wechat', 'session', 'memory', 'skill', 'cron',
    '看一下', '看看', '让我', '继续', '嗯', '哦',
}


def _ent_id(name: str) -> str:
    return f"ent_{hashlib.sha256(name.encode()).hexdigest()[:12]}"


def _doc_id(content: str) -> str:
    return f"doc_thought_{hashlib.sha256(content.encode()).hexdigest()[:12]}"


def _rel_id(*parts: str) -> str:
    raw = "_".join(parts)
    return f"rel_{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def get_db() -> sqlite3.Connection:
    """获取 KG 数据库连接。"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_tables(conn)
    return conn


def ensure_tables(conn: sqlite3.Connection):
    """确保核心表存在（与 loader.py 中使用的 schema 一致）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL DEFAULT 'news',
            title TEXT NOT NULL DEFAULT '',
            url TEXT DEFAULT '',
            source TEXT DEFAULT '',
            category TEXT DEFAULT 'uncategorized',
            language TEXT DEFAULT 'unknown',
            publish_time TEXT DEFAULT '',
            collect_time TEXT DEFAULT '',
            content TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            confidence REAL DEFAULT 0.5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL DEFAULT 'concept',
            aliases TEXT DEFAULT '[]',
            description TEXT DEFAULT '',
            importance REAL DEFAULT 0.5,
            first_seen TEXT DEFAULT '',
            last_seen TEXT DEFAULT '',
            source_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS relations (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL DEFAULT 'entity',
            source_id TEXT NOT NULL DEFAULT '',
            target_type TEXT NOT NULL DEFAULT 'document',
            target_id TEXT NOT NULL DEFAULT '',
            relation_type TEXT NOT NULL DEFAULT 'mentions',
            weight REAL DEFAULT 1.0,
            source_doc_id TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("  📋 已创建知识图谱表: documents, entities, relations")


# ===================== 分类器 =====================

def classify_message(text: str) -> tuple:
    """
    对消息进行类型分类。
    Returns (type_label, confidence) 或 ("想法", 0.50) 作为默认值。
    """
    for label, conf, keywords in CLASSIFICATION_RULES:
        for kw in keywords:
            if kw in text:
                return label, conf
    return ("想法", 0.50)


# ===================== 实体提取（复用 Orcas NER + 英文规则） =====================

# 尝试加载 ner_fast 模块
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
    from ner_fast import fast_ner, _is_low_quality
    HAVE_NER = True
except ImportError:
    HAVE_NER = False


def extract_entities(text: str) -> list:
    """
    从文本中提取核心实体。

    策略:
      1. 个人实体精确匹配（先生、弹簧等）
      2. 大写英文技术名词（DeepSeek, Transformer, GPT-4 等）
      3. 中英文混合版本号（DeepSeek-v4, GPT-4o 等）
      4. 含空格的组合技术名（Hermes Agent 等）— 从种子表匹配
      5. 如果 ner_fast 可用，用 jieba+正则智能提取中文实体
    """
    entities = set()

    # 1. 个人实体
    for name in PERSONAL_ENTITIES:
        if name in text:
            entities.add(name)

    # 2. 大写英文技术名词
    tech_matches = re.findall(r'\b[A-Z][A-Za-z0-9_-]{2,}\b', text)
    for t in tech_matches:
        if t.lower() not in GARBAGE_NAMES and len(t) >= 3:
            entities.add(t)

    # 3. 中英文混合（如 "DeepSeek-v4", "GPT-4o"）
    mixed = re.findall(r'[A-Za-z][A-Za-z0-9_-]*[vV]\d[\w.-]*', text)
    for m in mixed:
        if m not in GARBAGE_NAMES:
            entities.add(m)

    # 4. 含空格的组合技术名（从 SYSTEM_ENTITIES + SEED 匹配）
    # 匹配 "Hermes Agent"、"Claude Sonnet 4" 等
    spaced_tech = re.findall(r'\b([A-Za-z][a-z]*\s[A-Za-z][A-Za-z0-9]*(\s\d)?)\b', text)
    for match in spaced_tech:
        term = match[0].strip()
        if term and len(term) >= 5 and not any(c in GARBAGE_NAMES for c in term.lower().split()):
            entities.add(term)
    # 也匹配 "GPT-4o" 级别（修正版润饰）
    versioned = re.findall(r'\b[A-Za-z]+-\d+[A-Za-z]?(?:-\d+)?\b', text)
    for v in versioned:
        if v not in GARBAGE_NAMES:
            entities.add(v)

    # 5. ner_fast 智能中文实体提取
    if HAVE_NER:
        try:
            ner_results = fast_ner("", text, max_candidates=15)
            for ent in ner_results:
                name = ent.get("name", "") if isinstance(ent, dict) else str(ent)
                if not name or len(name) < 2:
                    continue
                if name.lower() in GARBAGE_NAMES:
                    continue
                entities.add(name)
        except Exception:
            pass  # NER 失败时静默降级

    # 去重 + 去除包含关系
    return _deduplicate(entities)


def _deduplicate(entities: set) -> list:
    """
    去重 + 去除包含关系。
    如果 'GPT-4o' 已在列表中，排除 'GPT' 这样的短名子串。
    """
    ents = list(dict.fromkeys(entities))  # 去重保序
    long_ents = {e.lower() for e in ents if len(e) >= 5}
    filtered = []
    for e in ents:
        el = e.lower()
        if any(el in le and el != le for le in long_ents):
            continue
        if re.match(r'^[A-Z][A-Za-z0-9]{1,3}$', e):
            if any(el in le and len(le) > len(e) + 2 for le in long_ents):
                continue
        filtered.append(e)
    return filtered


# ===================== 核心摄入逻辑 =====================

SYSTEM_ENTITIES = {
    # 预置几个常用系统实体（可扩展）
    "Hermes Agent": ("product", ["Hermes"], 0.9),
    "DeepSeek": ("product", ["深度求索"], 0.9),
    "OpenAI": ("company", [], 0.85),
    "GitHub": ("company", [], 0.85),
    "Orcas": ("product", [], 0.95),
}


def get_entity_type(name: str) -> str:
    """获取实体类型，从已知列表查找。"""
    if name in PERSONAL_ENTITIES:
        return PERSONAL_ENTITIES[name][0]
    if name in SYSTEM_ENTITIES:
        return SYSTEM_ENTITIES[name][0]
    return "concept"


def get_entity_aliases(name: str) -> list:
    """获取实体别名。"""
    if name in PERSONAL_ENTITIES:
        return PERSONAL_ENTITIES[name][1]
    if name in SYSTEM_ENTITIES:
        return SYSTEM_ENTITIES[name][1]
    return []


def ingest_thought(text: str, source: str = "cli", dry_run: bool = False) -> dict:
    """
    摄入一条 thought 到知识图谱。

    参数:
        text: 用户输入的原始消息
        source: 来源 ("cli", "weixin", "api", "file")
        dry_run: True 时不写入数据库

    返回:
        包含分类、实体、文档ID的 dict
    """
    text = text.strip()
    if not text:
        return {"error": "empty text"}

    # 分类
    label, confidence = classify_message(text)

    # 提取实体
    entities = extract_entities(text)

    # 构建元数据
    now = datetime.now().isoformat()
    today = datetime.now().strftime("%Y-%m-%d")
    doc_id = _doc_id(text)
    title = f"[{label}] {text[:80].rstrip()}"
    if len(title) > 100:
        title = title[:97] + "..."

    result = {
        "doc_id": doc_id,
        "title": title,
        "label": label,
        "confidence": confidence,
        "entities": entities,
        "source": source,
        "timestamp": now,
    }

    if dry_run:
        return result

    # === 写入 KG ===
    db = get_db()

    try:
        # 1. 写入文档（type='thought'）
        db.execute("""
            INSERT OR REPLACE INTO documents
            (id, type, title, url, source, category, language, publish_time, collect_time,
             content, tags, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            doc_id,
            "thought",
            title,
            "",
            source,
            f"thought/{label}",
            "zh-CN",
            today,
            now,
            text[:2000],
            json.dumps([label], ensure_ascii=False),
            confidence,
        ))

        # 2. 写入实体 + 建立关系
        for ent_name in entities:
            eid = _ent_id(ent_name)
            ent_type = get_entity_type(ent_name)
            aliases = get_entity_aliases(ent_name)

            db.execute("""
                INSERT OR REPLACE INTO entities
                (id, name, type, aliases, description, importance, first_seen, last_seen, source_count)
                VALUES (?, ?, ?, ?, ?, ?,
                        COALESCE((SELECT MIN(first_seen) FROM entities WHERE id = ?), ?),
                        COALESCE((SELECT MAX(last_seen) FROM entities WHERE id = ?), ?),
                        COALESCE((SELECT source_count + 1 FROM entities WHERE id = ?), 1))
            """, (
                eid, ent_name, ent_type,
                json.dumps(aliases, ensure_ascii=False),
                f"来自 thought: {title[:60]}",
                0.5,
                eid, today,
                eid, today,
                eid,
            ))

            # 实体 → 文档关系
            rid = _rel_id("entity", eid, "mentions", doc_id)
            db.execute("""
                INSERT OR IGNORE INTO relations
                (id, source_type, source_id, target_type, target_id, relation_type, weight, source_doc_id)
                VALUES (?, 'entity', ?, 'document', ?, 'mentions', 1.0, ?)
            """, (rid, eid, doc_id, doc_id))

        # 3. 实体间共现关系
        if len(entities) >= 2:
            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    e1_id = _ent_id(entities[i])
                    e2_id = _ent_id(entities[j])
                    rid = _rel_id(e1_id, "co", e2_id, "in", doc_id)
                    db.execute("""
                        INSERT OR IGNORE INTO relations
                        (id, source_type, source_id, target_type, target_id, relation_type, weight, source_doc_id)
                        VALUES (?, 'entity', ?, 'entity', ?, 'co_occurrence', 0.3, ?)
                    """, (rid, e1_id, e2_id, doc_id))

        db.commit()
        result["written"] = True

    except Exception as e:
        db.rollback()
        result["written"] = False
        result["error"] = str(e)
    finally:
        db.close()

    return result


def ingest_batch(filepath: str, source: str = "cli", dry_run: bool = False) -> list:
    """
    批量摄入 thoughts。

    支持格式:
      - JSONL（每行一个 JSON 对象，必须有 "text" 字段）
      - 纯文本（每行一条 thought）
    """
    results = []

    with open(filepath) as f:
        first_line = f.readline()
        f.seek(0)

        # 判断格式
        if first_line.strip().startswith("{"):
            # JSONL 格式
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    text = record.get("text", "")
                    src = record.get("source", source)
                except json.JSONDecodeError:
                    continue
                if text:
                    results.append(ingest_thought(text, src, dry_run))
        else:
            # 纯文本格式
            for line in f:
                line = line.strip()
                if line:
                    results.append(ingest_thought(line, source, dry_run))

    return results


# ===================== CLI =====================

def format_result(result: dict) -> str:
    """格式化一条摄入结果为可读文本。"""
    if "error" in result:
        return f"  ❌ {result.get('error', 'unknown error')}"

    label = result["label"]
    confidence = result["confidence"]
    entities = result["entities"]
    doc_id = result["doc_id"]

    lines = [f"  📝 [{label}] (置信度: {confidence:.2f})"]
    if entities:
        lines.append(f"    实体: {', '.join(entities)}")
    lines.append(f"    ID: {doc_id}")
    lines.append(f"    状态: {'✅ 已写入' if result.get('written') else '⚡ 预览'}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="知识记忆摄入器 — 将决策、判断、指令等写入知识图谱",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 单条摄入
  python3 -m knowledge-graph.thought_ingestion --text "我觉得关键在推理成本"

  # 管道输入
  echo "决定切换 DeepSeek v4-pro" | python3 -m knowledge-graph.thought_ingestion

  # 预览（不写入）
  python3 -m knowledge-graph.thought_ingestion --text "评估几个框架" --dry-run

  # 从 JSONL 文件批量导入
  python3 -m knowledge-graph.thought_ingestion --batch thoughts.jsonl

  # 从纯文本文件导入
  python3 -m knowledge-graph.thought_ingestion --batch notes.txt
        """,
    )
    parser.add_argument("--text", "-t", help="单条 thought 文本")
    parser.add_argument("--file", "-f", help="从 JSON 文件读取单条 thought")
    parser.add_argument("--batch", "-b", help="批量导入 JSONL 或纯文本文件")
    parser.add_argument("--source", "-s", default="cli",
                        choices=["cli", "weixin", "api", "file", "cron"],
                        help="来源（默认: cli）")
    parser.add_argument("--dry-run", "-n", action="store_true", help="只预览，不写入")

    # 如果没有参数，从 stdin 读取
    args = parser.parse_args()

    # 参数优先级: --text > --file > --batch > stdin
    if args.batch:
        print(f"📦 批量导入: {args.batch}")
        results = ingest_batch(args.batch, args.source, args.dry_run)
        total = len(results)
        written = sum(1 for r in results if r.get("written"))
        errors = sum(1 for r in results if "error" in r)
        print(f"   共 {total} 条 | ✅ {written} 条写入 | ❌ {errors} 条失败" if not args.dry_run
              else f"   共 {total} 条预览")
        for r in results:
            print()
            print(format_result(r))
        return

    if args.file:
        with open(args.file) as f:
            data = json.load(f)
        text = data.get("text", "")
        source = data.get("source", args.source)
    elif args.text:
        text = args.text
        source = args.source
    else:
        # 从 stdin 读取（管道模式）
        text = sys.stdin.read().strip()
        source = args.source

    if not text:
        print("⚠ 没有输入内容。使用 --text, --file, --batch, 或管道输入。")
        parser.print_help()
        sys.exit(1)

    result = ingest_thought(text, source, args.dry_run)

    if args.dry_run:
        print("⚡ DRY RUN — 未写入数据库")
    print()
    print(format_result(result))
    print()

    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
