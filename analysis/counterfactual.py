"""
counterfactual_generator.py — 反事实推理 (任务0.4)

Daily counterfactual reasoning based on today's most important news.
Uses template-based approach to generate "what if" scenarios.

Cron usage:
  python3 analysis/counterfactual.py
"""

import json
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta

import os
ORCAS_HOME = os.environ.get("ORCAS_HOME", os.path.expanduser("~/.orcas"))
DB_PATH = os.path.join(ORCAS_HOME, "kg.db")
LOG_PATH = os.path.join(ORCAS_HOME, "logs/counterfactual.md")

# —————— 反事实模板库 ——————

# 按分类的反事实推理模板
COUNTERFACTUAL_TEMPLATES = {
    "technology": {
        "decision_points": [
            ("某公司没有选择当前技术路线", "选择另一条技术路线"),
            ("没有发布该产品", "竞争对手率先抢占市场"),
            ("开源方案未被采纳", "闭源生态成为主流"),
        ],
        "formats": [
            lambda title, ents: f"如果{ents[0] if ents else '相关方'}在{title}中没有采取这一策略，而是选择保守观望，那么竞争对手很可能已经填补了市场空白，先生的工具链选择范围将更加有限。",
            lambda title, ents: f"如果当时该项技术决策被推迟了6个月，那么整个生态格局可能完全不同，先生今天使用的很可能是一套替代方案。",
        ],
    },
    "military": {
        "decision_points": [
            ("冲突未升级", "外交谈判提前达成"),
            ("未采取军事威慑", "局势和平降温"),
            ("第三方介入调停", "冲突规模被限制"),
        ],
        "formats": [
            lambda title, ents: f"如果{ents[0] if ents else '相关方'}在事态初期选择了不同的应对策略，地缘风险的传导路径可能完全改写，先生的资产配置逻辑也需要相应调整。",
            lambda title, ents: f"假设当时没有发生{title}中的关键事件，周边地区的安全态势将显著不同，先生的信息筛选权重也应重新分配。",
        ],
    },
    "economy": {
        "decision_points": [
            ("政策未收紧", "经济过热引发通胀"),
            ("贸易限制未实施", "供应链保持畅通"),
            ("未采取刺激措施", "经济增速进一步放缓"),
        ],
        "formats": [
            lambda title, ents: f"如果当时决策者选择了相反的经济政策，市场走势将与今天截然不同，先生可能需要重新评估投资组合的风险敞口。",
            lambda title, ents: f"如果{title}中的经济信号被推迟了3个月才显现，那么市场参与者的预期和反应都会完全不同，先生的财务规划节点也应随之调整。",
        ],
    },
    "finance": {
        "decision_points": [
            ("监管未放松", "市场流动性持续紧缩"),
            ("利率未调整", "资本成本维持高位"),
            ("未引入外资", "市场估值体系保持封闭"),
        ],
        "formats": [
            lambda title, ents: f"如果当时的金融监管政策走向了另一个方向，资本流动格局将彻底改变，先生的现金流管理和融资策略也需要对应调整。",
            lambda title, ents: f"如果{title}中的金融信号被市场提前消化，那么当前的估值水平将完全不同，先生的资产配置需要重新校准。",
        ],
    },
    "politics": {
        "decision_points": [
            ("政策未被通过", "行业保持原有监管状态"),
            ("选举结果不同", "政策方向完全反转"),
            ("国际合作未破裂", "多边框架持续运作"),
        ],
        "formats": [
            lambda title, ents: f"如果当时的政治决策走向了另一条路径，{ents[0] if ents else '相关领域'}的规则将完全不同，先生的合规成本和机会窗口也会随之改变。",
            lambda title, ents: f"假设{title}中的博弈出现了相反的结果，那么接下来的政策预期将全面逆转，先生应提前思考备用方案。",
        ],
    },
    "international": {
        "decision_points": [
            ("外交破裂未发生", "双边关系维持正常"),
            ("国际制裁未实施", "经济合作继续推进"),
            ("未形成军事同盟", "地区力量维持平衡"),
        ],
        "formats": [
            lambda title, ents: f"如果当时外交谈判取得了突破而非破裂，地缘政治格局将完全不同，先生的信息来源渠道和可信度权重也需要重新评估。",
            lambda title, ents: f"如果{title}中的国际事件走向了缓和而非升级，那么全球供应链和资本流向都将改写，先生的决策坐标系也应相应调整。",
        ],
    },
}

# 默认模板
DEFAULT_TEMPLATES = {
    "decision_points": [
        ("选择不同", "结果完全不同"),
        ("决策延迟", "时机错失"),
    ],
    "formats": [
        lambda title, ents: f"如果当时在{title}中的关键节点上做出了不同的选择，后续的发展路径可能完全改写，先生对这一议题的认知框架也值得重新审视。",
        lambda title, ents: f"假设{title}中的核心变量发生了变化，整个叙事逻辑将截然不同，这一反事实视角可为先生的多元化决策提供参考。",
    ],
}


def extract_key_entities(title, content):
    """从标题和内容中提取关键实体名"""
    text = f"{title} {content[:300]}"

    # 提取国家/地区名
    countries = re.findall(r'(?:美国|中国|日本|韩国|俄罗斯|欧洲|英国|法国|德国|印度|伊朗|以色列|沙特|阿联酋|新加坡|台湾|香港|朝鲜|越南|澳大利亚)', text)

    # 提取公司名（中文2-6字+公司/科技/集团）
    companies = re.findall(r'[\u4e00-\u9fff]{2,6}(?:公司|集团|科技|技术|研究院)', text)

    # 提取人物名（中文2-4字）
    persons = re.findall(r'(?:特朗普|拜登|普京|习近平|泽连斯基|内塔尼亚胡|哈梅内伊|石破茂|尹锡悦|莫迪)', text)

    return (countries + companies + persons)[:3]


def get_top_news(db):
    """获取今天最重要的新闻"""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 先试今天
    print(f"  📰 查询今日新闻 ({today})...")
    docs = db.execute("""
        SELECT id, title, content, category, confidence
        FROM documents
        WHERE type='news'
          AND (date(publish_time) = ? OR date(collect_time) = ?)
        ORDER BY confidence DESC
        LIMIT 5
    """, (today, today)).fetchall()

    if docs:
        print(f"  → 找到 {len(docs)} 条今日新闻")
        return docs

    # 回退到昨天
    print(f"  📰 今日无新闻，回退到昨日 ({yesterday})...")
    docs = db.execute("""
        SELECT id, title, content, category, confidence
        FROM documents
        WHERE type='news'
          AND (date(publish_time) = ? OR date(collect_time) = ?)
        ORDER BY confidence DESC
        LIMIT 5
    """, (yesterday, yesterday)).fetchall()

    if docs:
        print(f"  → 找到 {len(docs)} 条昨日新闻")
        return docs

    # 最后回退：最近一周
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    print(f"  📰 回退到最近一周 ({week_ago} ~ {today})...")
    docs = db.execute("""
        SELECT id, title, content, category, confidence
        FROM documents
        WHERE type='news'
          AND (date(publish_time) >= ? OR date(collect_time) >= ?)
        ORDER BY confidence DESC
        LIMIT 5
    """, (week_ago, week_ago)).fetchall()

    return docs


def get_category_templates(category):
    """获取分类对应的模板，回退到默认"""
    for key in COUNTERFACTUAL_TEMPLATES:
        if key in (category or "").lower():
            return COUNTERFACTUAL_TEMPLATES[key]
    return DEFAULT_TEMPLATES


def generate_counterfactual(title, content, category):
    """生成反事实推理文本"""
    if not content:
        content = ""

    ents = extract_key_entities(title, content)
    templates = get_category_templates(category)

    # 选择决策点
    decision_point, alternative = random.choice(templates["decision_points"])

    # 选择格式
    format_fn = random.choice(templates["formats"])

    # 生成背景说明
    context = format_fn(title, ents)

    # 构建反事实句子
    counterfactual_options = [
        f"**如果当时选择了「{alternative}」，那么现在很可能发生的是「{decision_point}所对应的完全不同的结果」。**",
        f"**如果当时的{ents[0] if ents else '关键决策者'}做出了相反的选择，那么今天的格局将彻底改写。**",
        f"**如果当时{title}中的事件未曾发生，世界的走向将与我们现在看到的截然不同。**",
    ]
    counterfactual_sentence = random.choice(counterfactual_options)

    full_text = f"{context}\n\n{counterfactual_sentence}"

    return full_text


def main():
    print(f"🔄 反事实推理引擎 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   数据库: {DB_PATH}")

    db = sqlite3.connect(DB_PATH)

    try:
        docs = get_top_news(db)

        if not docs:
            print("⚠ 未找到任何新闻文档，无法生成反事实推理")
            # 写一个空条目
            today = datetime.now().strftime("%Y-%m-%d")
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"\n## 反事实推演 — {today}\n\n今日无新闻数据，跳过反事实生成。\n\n_生成时间: {timestamp}_\n"
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(entry)
            print(f"  📝 已记录空条目到 {LOG_PATH}")
            return

        # 取置信度最高的
        top_doc = docs[0]
        doc_id, title, content, category, confidence = top_doc

        print(f"\n🏆 选中新闻:")
        print(f"   标题: {title}")
        print(f"   分类: {category}")
        print(f"   置信度: {confidence}")

        counterfactual = generate_counterfactual(title, content or "", category)

        # 构建日志条目
        today = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## 反事实推演 — {today}\n\n"
        entry += f"基于今日新闻：{title}\n\n"
        entry += f"{counterfactual}\n\n"
        entry += f"_生成时间: {timestamp}_\n"

        # 追加到日志
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(entry)

        print(f"\n📄 反事实记录已追加到 {LOG_PATH}")
        print(f"\n{'='*50}")
        print(f"📝 生成的反事实:")
        print(f"{counterfactual}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
