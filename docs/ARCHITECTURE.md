# Orcas — 个人智库系统部署白皮书（AI Agent 版）

> 本文档供 AI Agent（如 Claude Code、Codex、Cursor 等）阅读。
> 你的任务是：**理解这套系统的架构，然后在目标机器上自主完成部署和运行。**
>
> 你的主人会给你方向和预算约束，其余由你判断和执行。

---

## 一、系统概述

Orcas 是一套 **AI 主动维护的个人知识基础设施**。它自动完成：

```
采集（RSS/API） → 实体提取 → 知识图谱入库 → 趋势分析 → 报告生成
```

全链路无人值守，由 cron 调度。主人只消费输出（趋势快报、分析报告），不参与日常运维。

### 核心理念

| 设计原则 | 说明 |
|---------|------|
| **增量优先** | 全量导入只在首次，之后都是增量。快照只记录变化量。 |
| **两级 NER** | 快速级（规则+词典）覆盖广度 + 精校级（LLM）保证准确度，平衡成本与质量 |
| **快照驱动分析** | 趋势基于每日快照对比，非实时计算，保证可回溯、可复现 |
| **适配器模式** | 采集源、分析器、投递目标都支持插拔，不改核心代码即可扩展 |
| **数据源外部化** | 所有采集渠道通过 YAML 配置，代码不含任何硬编码数据源 |

### 架构图

```
  数据采集层
  ┌─────────────────────────────────────────┐
  │  collector/collector.py                 │
  │  ┌──────────┐  ┌──────────┐             │
  │  │ RSS 采集  │  │ API 采集  │             │
  │  └────┬─────┘  └────┬─────┘             │
  │       │             │                    │
  │  ┌────▼─────────────▼────┐               │
  │  │   清洗 · 去重 · 标签    │               │
  │  └───────────────────────┘               │
  └─────────────────┬───────────────────────┘
                    │
  知识图谱引擎       ▼
  ┌─────────────────────────────────────────┐
  │  knowledge-graph/                       │
  │  ┌──────────────┐ ┌──────────────────┐  │
  │  │ NER 实体提取  │ │ 置信度评分        │  │
  │  │ (ner_fast.py) │ │ (confidence_...  │  │
  │  └──────┬───────┘ └────────┬─────────┘  │
  │         │                  │             │
  │  ┌──────▼──────────────────▼──────┐     │
  │  │ 增量加载 + 快照机制 (SQLite)    │     │
  │  │ (loader.py + trend_analysis)   │     │
  │  └────────────────┬───────────────┘     │
  └───────────────────┼────────────────────┘
                      │
  分析层               ▼
  ┌─────────────────────────────────────────┐
  │  analysis/                              │
  │  ┌──────────┐ ┌──────────┐ ┌─────────┐  │
  │  │ 趋势分析  │ │ 突发检测  │ │ 反事实   │  │
  │  │          │ │          │ │ 推理     │  │
  │  └────┬─────┘ └───┬──────┘ └───┬─────┘  │
  │       │           │             │        │
  │  ┌────▼───────────▼─────────────▼────┐  │
  │  │  报告生成 (report_generator.py)    │  │
  │  └────────────────┬──────────────────┘  │
  └───────────────────┼────────────────────┘
                      │
  交付层               ▼
  ┌─────────────────────────────────────────┐
  │  scripts/ + scheduler/                  │
  │  ┌──────────┐ ┌──────────┐ ┌─────────┐  │
  │  │ 终端输出  │ │ 文件保存  │ │ 健康检查 │  │
  │  └──────────┘ └──────────┘ └─────────┘  │
  └─────────────────────────────────────────┘
```

---

## 二、组件清单

### 2.1 知识图谱引擎 (`knowledge-graph/`)

| 文件 | 职责 |
|------|------|
| `loader.py` | 增量/全量数据导入器。读取新闻等数据源，提取实体，写入 SQLite。支持 `--reset`（清空重导）和 `--dry-run`（模拟运行）。 |
| `ner_fast.py` | 快速实体提取器。基于 jieba 分词 + 正则 + 黑名单/白名单词典。毫秒级。 |
| `confidence_engine.py` | 置信度评分。综合来源可信度、匹配频次、NER 级别给实体置信度打分。 |
| `trend_analysis.py` | 趋势分析系统（也位于 `analysis/`）。通过每日快照对比实现热度时序、新实体发现、突发检测。 |
| `query.py` | 知识图谱查询接口。支持按时间线、实体关联、热度排行等查询。 |
| `ner_blacklist.yaml` | NER 噪声过滤规则（HTML 残留、通用名词等）。 |
| `ner_user_dict.txt` | jieba 用户词典，用于正确切分专有名词。 |

### 2.2 分析引擎 (`analysis/`)

| 文件 | 职责 |
|------|------|
| `trend_analysis.py` | 趋势分析 — 快照对比实现热度时序、新发现、突发检测。子命令：`snapshot`/`rising`/`new`/`burst`/`trending`/`status` |
| `counterfactual.py` | 反事实推理 — 基于重要事件生成"如果…会怎样"的假设推演。 |
| `gap_detection.py` | 知识盲区检测 — 扫描 KG 中关系稀疏的节点，标记建议补充方向。 |
| `report_generator.py` | 报告生成器 — 汇总各分析结果，生成综合报告。 |

### 2.3 数据采集 (`collector/`)

| 文件 | 职责 |
|------|------|
| `collector.py` | 通用采集器。从 YAML 配置读取数据源列表，按类型分发到对应采集方法，执行清洗去重、标签生成、持久化。 |
| `registry.py` | 采集源注册表。自定义 Source Adapter 在此注册后主循环可自动发现。 |
| `sources/__init__.py` | sources 子模块包标记。 |
| `sources/base.py` | `BaseSourceAdapter` 基类。自定义数据源适配器应继承此类。 |

**数据源配置**：所有采集渠道通过 `sources.yaml` 定义，代码不含任何硬编码数据源 URL。详见 `config.example.yaml`。

**内置采集方法**：
- `fetch_rss()` — 通用 RSS/Atom Feed 采集，支持 feedparser 自动解析和 XML 回退解析
- `fetch_api()` — 通用 API 采集，支持 JSONPath 表达式提取字段

### 2.4 调度与交付 (`scheduler/`)

| 文件 | 职责 |
|------|------|
| `cron_patterns.md` | 推荐定时任务配置模式：采集每 2h、KG 导入每 2h、报告每天 9:00、健康检查每天 6:00。 |
| `delivery_spec.md` | 投递规范。定义适配器接口、报告格式标准、`MEDIA:` 文件标记协议。 |

### 2.5 辅助脚本 (`scripts/`)

| 文件 | 职责 |
|------|------|
| `health_check.py` | 系统健康检查。验证 KG 完整性、快照时效性、采集输出状态。支持 `--full` 模式验证模块可加载性。 |
| `data_validate.py` | 数据校验。检查采集输出 JSON 格式、必填字段、重复记录；统计 KG 表行数。 |

---

## 三、部署步骤（由 AI Agent 执行）

### Step 1: 环境准备

```bash
# Python 3.10+
python3 --version

# 安装依赖
pip install -r requirements.txt
```

`requirements.txt` 清单：feedparser、requests、beautifulsoup4、jieba、pyyaml。

### Step 2: 获取代码

```bash
git clone https://github.com/mr-tan4/Orcas.git orcas
cd orcas
```

### Step 3: 配置

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`：

```yaml
orcas:
  home: "~/.orcas"
  collector:
    sources:
      - type: rss
        name: "my_source"
        url: "https://your-feed-url/rss"
        category: "technology"
  delivery:
    targets:
      - platform: "console"
```

**数据源配置**有两种方式：
- **方式 A（推荐）**：单独创建 `sources.yaml` 文件，`load_config()` 优先加载
- **方式 B**：使用 `config.yaml` 内联配置

首次部署建议先用示例 RSS 源测试全链路。

### Step 4: 初始化 KG 数据库

```bash
# 首次运行：创建数据库结构和种子实体
python3 -m knowledge-graph.loader --seed-only

# 验证
python3 -m knowledge-graph.query stats
```

### Step 5: 运行采集 + 导入

```bash
# 单次采集（数据源来自 sources.yaml 或 config.yaml）
python3 -m collector.collector --all

# 导入 KG
python3 -m knowledge-graph.loader --incremental

# 创建趋势快照
python3 -m analysis.trend_analysis snapshot

# 查看趋势
python3 -m analysis.trend_analysis trending

# 生成报告
python3 -m analysis.report_generator
```

### Step 6: 设置定时任务

推荐 cron 配置（`crontab -e`）：

```cron
# Orcas 定时任务

# 每 2 小时采集
0 */2 * * * cd ~/orcas && python3 -m collector.collector --all

# 采集后延迟 30 分钟导入 KG
30 */2 * * * cd ~/orcas && python3 -m knowledge-graph.loader --incremental

# 每天 02:00 创建趋势快照
0 2 * * * cd ~/orcas && python3 -m analysis.trend_analysis snapshot

# 每天 09:00 生成趋势报告
0 9 * * * cd ~/orcas && python3 -m analysis.trend_analysis trending

# 每天 06:00 健康检查
0 6 * * * cd ~/orcas && python3 -m scripts.health_check

# 每周日 04:00 知识盲区扫描
0 4 * * 0 cd ~/orcas && python3 -m analysis.gap_detection
```

详见 `scheduler/cron_patterns.md`。

### Step 7: 验证全链路

```bash
# 健康检查
python3 -m scripts.health_check --full

# 输出应该包含：
# - KG 数据库: OK (N 实体)
# - 趋势快照: OK (今日已更新)
# - 采集输出: OK (今日 N 条)
# - trend_analysis: 可加载 ✓
# - collector: 可加载 ✓
```

---

## 四、配置参考

### 4.1 种子实体配置（NER 用）

种子实体内置于 `loader.py` 的 `SEED_ENTITIES` 字典中，用户应替换为自身关注领域的实体：

```python
SEED_ENTITIES = {
    "OpenAI": {"type": "company", "aliases": ["Open AI"]},
    "DeepSeek": {"type": "company", "aliases": ["深度求索"]},
    # 使用者替换为自己的关注实体
}
```

### 4.2 数据源配置 (`sources.yaml`)

```yaml
sources:
  - name: my_rss_source       # 唯一标识
    type: rss                  # rss | api
    url: "https://..."         # RSS Feed URL 或 API 端点
    category: technology       # 分类标签
    language: en               # zh-CN | en

  - name: my_api_source
    type: api
    endpoint: "https://api..."
    category: technology
    json_path: "$.items[*]"    # JSONPath 提取列表
    extract_fields:
      title: "$.title"
      description: "$.desc"
      url: "$.url"

http:
  timeout: 30
  headers:
    User-Agent: "Orcas-Collector/1.0"
```

### 4.3 LLM 配置

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| `provider` | API 提供商 | `deepseek` / `openai` / `openrouter` |
| `model` | 模型名 | `deepseek-chat` / `gpt-4o-mini` |
| `temperature` | 生成温度 | `0.3`（分析类任务用低温） |
| `max_tokens` | 最大输出 | `4096` |

---

## 五、记忆摄入 — Thought Ingestion

除了自动采集新闻，Orcas 还支持**手动/API 写入知识碎片**（决策、判断、指令、探讨等），将用户的观察直接摄入知识图谱。

### 5.1 使用场景

- **Agent 静默投喂**：Hermes Agent 等 AI 助手在对话结束后，将用户的决策/判断自动写入 Orcas KG
- **人肉输入**：直接通过 CLI 或管道输入 notes、想法、会议纪要
- **批量导入**：从 JSONL 或纯文本文件批量导入历史记录

### 5.2 CLI 用法

```bash
# 单条输入
python3 -m knowledge-graph.thought_ingestion --text "我觉得关键在推理成本"

# 管道输入
echo "决定用 DeepSeek v4-pro" | python3 -m knowledge-graph.thought_ingestion

# 预览（不写入）
python3 -m knowledge-graph.thought_ingestion --text "评估几个框架的架构差异" --dry-run

# 批量导入
python3 -m knowledge-graph.thought_ingestion --batch thoughts.jsonl
```

### 5.3 分类规则

| 分类 | 置信度 | 触发关键词 |
|------|--------|-----------|
| 决策 | 0.95 | 决定、就按、选、确认、同意 |
| 判断 | 0.90 | 我觉得、关键在、短板、更好 |
| 指令 | 0.85 | 需要、安排、下一步、执行 |
| 探讨 | 0.70 | 趋势、架构、设计、对比 |
| 想法 | 0.50 | 默认分类 |

### 5.4 与 Hermes Agent 集成

如果部署了 [Hermes Agent](https://github.com/NousResearch/hermes-agent)，可以在 Hermes 的 Memory 插件中直接调用：

```python
# HermesMemoryKG on_session_end() 中自动调用
import subprocess
subprocess.run([
    "python3", "-m", "knowledge-graph.thought_ingestion",
    "--text", extracted_thought,
    "--source", "hermes"
])
```

更推荐的集成方式：Hermes Agent 配置 `memory.provider: hermes-memory-kg` 后，会自动使用其自身的 KG 数据库。如果需要将 Hermes 的记忆与 Orcas 共享，可将两者指向同一个 `kg.db` 或通过 `thought_ingestion` CLI 桥接。

### 5.5 文件结构

| 文件 | 职责 |
|------|------|
| `knowledge-graph/thought_ingestion.py` | 记忆摄入核心（CLI + API） |
| — 分类器 | 规则关键词匹配 → 决策/判断/指令/探讨/想法 |
| — 实体提取 | ner_fast 智能中文提取 + 英文技术名词正则 |
| — 数据库写入 | 统一写入 Orcas KG（documents/entities/relations） |

---

## 六、扩展指南

### 6.1 添加新的数据源

1. 在 `collector/sources/` 下创建文件，继承 `BaseSourceAdapter`
2. 在 `collector/registry.py` 中注册
3. 在 `sources.yaml` 的 `sources` 中添加配置

### 6.2 添加新的分析器

1. 在 `analysis/` 下创建 `.py` 文件
2. 实现 `analyze(db) -> dict` 接口
3. `report_generator.py` 会收集并汇总分析结果

### 6.3 添加新的投递目标

1. 在 `scheduler/delivery/` 下创建平台适配器
2. 实现 `deliver(content, config) -> bool` 接口
3. 在 `delivery_spec.md` 中登记

---

## 七、故障排查

| 症状 | 可能原因 | 检查 |
|------|---------|------|
| 采集 0 条 | 数据源配置错误 / 网络不可达 | `curl <feed_url>` 是否正常返回 |
| NER 无输出 | 词典未加载 / 格式异常 | `python3 -m knowledge-graph.ner_fast --test` |
| 趋势分析报错 | 快照不存在 / DB 损坏 | `python3 -m analysis.trend_analysis status` |
| 报告为空 | 当日无新数据 / KG 为空 | 先运行采集和导入再生成报告 |
| 定时任务不触发 | cron 未启动 / 路径错误 | `crontab -l` 验证 + 检查 `$HOME` 路径 |
| loader 无新增 | 增量模式未检测到新文件 | 检查 `~/.orcas/news/data/` 下是否有新 JSON |

---

## 八、AI Agent 执行清单

当你（AI Agent）被主人要求部署 Orcas 时，按此清单执行：

1. □ 读取本文档，理解全貌
2. □ 检查环境（Python 版本、网络连通性、磁盘空间）
3. □ 向主人确认：API Key 来源？数据目录位置？需要接入哪些数据源？
4. □ `git clone` 代码
5. □ 创建 `config.yaml`，填入配置（API Key 优先用环境变量）
6. □ 创建 `sources.yaml`，配置数据源
7. □ 安装依赖 `pip install -r requirements.txt`
8. □ 初始化种子实体 + KG 数据库
9. □ 运行一次全链路测试：采集 → 导入 → 快照 → 报告
10. □ 确认输出符合预期，向主人汇报结果
11. □ 设置 cron 定时任务
12. □ 将部署概况写入本地 README 备忘，方便下次维护

---

*本文档专为 AI Agent 阅读编写。如有歧义，优先从系统设计意图推断，拿不准时向主人确认。*
