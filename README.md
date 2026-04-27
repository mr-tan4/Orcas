
<h1 align="center">🐋 Orcas</h1>

<p align="center">
  <strong>AI 主动维护的个人知识基础设施</strong>
</p>

<p align="center">
  采集 → 实体提取 → 知识图谱 → 趋势分析 → 报告生成
</p>

<p align="center">
  <a href="#-quick-start">快速开始</a> ·
  <a href="docs/ARCHITECTURE.md">架构白皮书</a> ·
  <a href="#-components">组件</a> ·
  <a href="#-extend">扩展</a>
</p>

---

> **这个项目的所有代码、设计、文档均由 AI 独立完成。**
> 人类只提供想法方向、提出意见和做决策。没有任何一行代码是手写的。
>
> 运行框架推荐 [**Hermes Agent**](https://github.com/NousResearch/hermes-agent)，LLM 推荐 [**DeepSeek**](https://github.com/deepseek-ai/DeepSeek-V3)。

## 🤖 AI 原生部署

**把 `docs/ARCHITECTURE.md` 交给你的 Hermes Agent，它会自主完成整个系统的理解、配置和部署。**

具体操作：将 `docs/ARCHITECTURE.md` 发送给你的 Hermes Agent，告诉它"部署 Orcas"，Agent 会：
1. 读取架构白皮书，理解系统全貌
2. 检查目标环境
3. 克隆代码仓库
4. 配置数据源和 API Key
5. 初始化知识图谱数据库
6. 运行全链路测试
7. 设置定时任务
8. 汇报运行结果

**你不需要阅读任何文档**——Agent 自己读。

Orcas 是一套全链路自动运转的知识系统。它不依赖你手动输入——配置好数据源后，它自己采集、自己提取、自己关联、自己分析，然后主动告诉你发现了什么。

## ✨ 设计理念

| 原则 | 说明 |
|------|------|
| **增量优先** | 全量导入只在首次，之后全是增量。快照只记录变化量。 |
| **两级 NER** | 快速级（规则+词典）覆盖广度，精校级（LLM）保证准确度。 |
| **快照驱动分析** | 趋势基于每日快照对比，非实时计算，保证可回溯、可复现。 |
| **适配器模式** | 采集源、分析器、投递目标都支持插拔。 |
| **数据源外部化** | 代码不含任何硬编码数据源，全由 YAML 配置。 |
| **本地优先** | SQLite + JSON，所有数据存本地，不上传任何地方。 |

## 🚀 快速开始

### 前置条件

- Python 3.10+
- 一个 LLM API Key（DeepSeek / OpenAI 均可，可选，用于精校 NER）

### 1. 安装

```bash
git clone https://github.com/your-org/orcas.git
cd orcas
pip install -r requirements.txt
```

### 2. 配置数据源

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，填入你的数据源：

```yaml
orcas:
  collector:
    sources:
      - type: rss
        name: "my_feed"
        url: "https://example.com/feed.xml"
        category: "technology"
```

### 3. 初始化知识图谱

```bash
python3 -m knowledge-graph.loader --seed-only
```

### 4. 运行全链路

```bash
# 采集
python3 -m collector.collector --all

# 导入 KG
python3 -m knowledge-graph.loader --incremental

# 趋势快照
python3 -m analysis.trend_analysis snapshot

# 看看结果
python3 -m analysis.trend_analysis trending
```

### 5. 设置定时任务（可选）

```cron
0 */2 * * * cd ~/orcas && python3 -m collector.collector --all
30 */2 * * * cd ~/orcas && python3 -m knowledge-graph.loader --incremental
0 9 * * * cd ~/orcas && python3 -m analysis.trend_analysis trending
```

详见 [`scheduler/cron_patterns.md`](scheduler/cron_patterns.md)。

## 🧩 组件

```
orcas/
├── knowledge-graph/          # 知识图谱引擎
│   ├── loader.py             # 增量/全量数据导入
│   ├── ner_fast.py           # 快速实体提取
│   ├── confidence_engine.py  # 置信度评分
│   ├── trend_analysis.py     # 趋势分析+突发检测
│   └── query.py              # 知识图谱查询
├── analysis/                 # 分析引擎
│   ├── trend_analysis.py     # 趋势/新发现/突发
│   ├── counterfactual.py     # 反事实推理
│   ├── gap_detection.py      # 知识盲区检测
│   └── report_generator.py   # 报告生成
├── collector/                # 数据采集
│   ├── collector.py          # 通用采集器
│   ├── registry.py           # 适配器注册表
│   └── sources/              # 数据源适配器
├── scheduler/                # 调度与交付
│   ├── cron_patterns.md      # 定时任务模式
│   └── delivery_spec.md      # 投递规范
└── scripts/                  # 辅助脚本
    ├── health_check.py       # 健康检查
    └── data_validate.py      # 数据校验
```

## 🔧 扩展

- **添加数据源** — 在 `collector/sources/` 下继承 `BaseSourceAdapter`，注册后即可
- **添加分析器** — 在 `analysis/` 下新建 `.py`，实现 `analyze(db)` 接口
- **添加投递目标** — 在 `scheduler/delivery/` 下实现 `deliver(content, config)` 接口

详见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 扩展指南章节。

## 📊 运行成本

| 项目 | 预估 |
|------|------|
| 采集 | 免费（RSS/API 调用） |
| NER 快速级 | CPU 毫秒级，免费 |
| NER 精校级（可选） | 按 API 计费 |
| 趋势分析 | 本地计算，免费 |
| 报告生成 | ~$0.05-0.15/天（DeepSeek） |

典型场景（10 个 RSS 源 + 每日报告）每天 API 费用约 **$0.05-0.15**。

## 🏗️ 运行框架推荐

本项目由 AI Agent 驱动开发和运行。推荐使用：

| 项目 | 说明 |
|------|------|
| [**Hermes Agent**](https://github.com/NousResearch/hermes-agent) | 由 Nous Research 开源的通用 AI Agent 框架。支持多平台接入（微信、Telegram、Discord）、插件系统、技能系统、定时任务调度。是运行 Orcas 全链路的推荐载体。 |
| [**DeepSeek**](https://github.com/deepseek-ai/DeepSeek-V3) | 深度求索开源的高性价比 LLM。在代码生成、数据分析、摘要生成等任务上表现出色，API 成本仅为同类模型的 1/10。 |

## ❓ 常见问题

**需要 GPU 吗？** 不需要。整条管道跑在 2C4G 机器上绰绰有余。

**数据存哪里？** 默认 `~/.orcas/`，全部本地 SQLite + JSON。

**能换别的 LLM 吗？** 可以。config.yaml 改 `llm.provider` 和 `llm.model` 即可。

**怎么加我自己的分析逻辑？** `analysis/` 下新建文件，实现 `analyze(db)` 接口，框架自动发现。

## 🙏 致谢

- [**Hermes Agent**](https://github.com/NousResearch/hermes-agent) — 驱动本项目的 AI Agent 框架
- [**DeepSeek**](https://github.com/deepseek-ai/DeepSeek-V3) — 为本项目提供核心推理能力的 LLM

以及所有开源项目的维护者，你们的 work 是这一切的基础。

## 📄 许可

Apache 2.0

---

<p align="center">Built by AI, directed by human.<br>让 AI 替你读，而不是替你喂。</p>
