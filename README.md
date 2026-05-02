<h1 align="center">🐋 Orcas</h1>

<p align="center">
  <strong>一个人+AI 的认知协作框架</strong>
</p>

<p align="center">
  知识不应该被热度绑架。认知需要多视角制衡。
</p>

<p align="center">
  <a href="docs/MANIFESTO.md">📜 认知方法论宣言</a> ·
  <a href="docs/DEPLOY.md">🚀 部署指南</a> ·
  <a href="docs/ARCHITECTURE.md">🏗️ 架构白皮书（AI Agent 版）</a> ·
  <a href="#-quick-start">⚡ 快速开始</a> ·
  <a href="#-components">🧩 组件</a> ·
  <a href="#-participate">🤝 参与</a>
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

---

## 📜 核心理念

Orcas 不是一个"装好就能用"的知识图谱工具。它是一个**认知方法论框架**。

### 五个核心原则

| 原则 | 一句话 |
|------|--------|
| **星群模型** | 个人知识与公共知识物理隔离，不被热度绑架 |
| **三元制衡** | 决策者、框架、助手三个视角独立运作，互相纠偏 |
| **实验生命周期** | 假设→实验→验证→提炼→收录，证伪也是知识 |
| **AI 审慎** | 多视角制衡是防止 AI 放大错误的安全阀 |
| **认知主权** | 决策者有推翻一切的最终权限，认知不可外包 |

详见 [`docs/MANIFESTO.md`](docs/MANIFESTO.md) — 认知方法论宣言。

---

## ⚡ 部署方式

Orcas 提供三种部署方式，选择最适合你的：

| 方式 | 适合用户 | 操作 |
|------|---------|------|
| **一键脚本** | 所有用户 | `bash <(curl -s https://raw.githubusercontent.com/mr-tan4/Orcas/main/install.sh)` |
| **AI Agent 自部署** | Hermes / Claude Code 用户 | 把 `docs/ARCHITECTURE.md` 发给 Agent |
| **手动部署** | 需要定制化的用户 | 见下方快速开始 |

详见 [`docs/DEPLOY.md`](docs/DEPLOY.md) 获取完整部署指南。

---

## 快速开始

### 前置条件
- Python 3.10+
- 一个 LLM API Key（DeepSeek / OpenAI 均可，可选，用于精校 NER）

### 1. 安装

```bash
git clone https://github.com/mr-tan4/Orcas.git
cd Orcas
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

---

## 🧩 组件

```
orcas/
├── knowledge-graph/          # 知识图谱引擎
│   ├── loader.py             # 增量/全量数据导入
│   ├── ner_fast.py           # 快速实体提取
│   ├── confidence_engine.py  # 置信度评分
│   ├── trend_analysis.py     # 趋势分析+突发检测
│   ├── query.py              # 知识图谱查询
│   └── thought_ingestion.py  # 记忆摄入（决策/判断/指令→KG）
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
├── docs/
│   ├── MANIFESTO.md          # 📜 认知方法论宣言
│   └── ARCHITECTURE.md       # 架构白皮书（AI Agent 版）
└── scripts/                  # 辅助脚本
    ├── health_check.py       # 健康检查
    └── data_validate.py      # 数据校验
```

---

## 🏗️ 运行框架推荐

| 项目 | 说明 |
|------|------|
| [**Hermes Agent**](https://github.com/NousResearch/hermes-agent) | 由 Nous Research 开源的通用 AI Agent 框架。支持多平台接入（微信、Telegram、Discord）、插件系统、技能系统、定时任务调度。是运行 Orcas 全链路的推荐载体。 |
| [**DeepSeek**](https://github.com/deepseek-ai/DeepSeek-V3) | 深度求索开源的高性价比 LLM。在代码生成、数据分析、摘要生成等任务上表现出色，API 成本仅为同类模型的 1/10。 |

---

## 🤝 参与

本项目需要的不是"加功能"，而是**"加视角"**。

| 贡献类型 | 说明 |
|---------|------|
| **使用反馈** | 部署后遇到的问题、你觉得缺失的功能 |
| **理念碰撞** | 三元认知模型有缺陷？开 Issue 辩论 |
| **跨领域经验** | 这个方法论在你的领域是否成立？ |
| **语言/文化适配** | 英文文档的翻译和本地化 |
| **工具扩展** | 新的数据源适配器、分析器、投递目标 |

我们不做功能竞标赛。这个项目的价值在于它的**理念和结构**，不在于它有多少个数据源。

### 社区原则

- 三元认知共同体的精神同样适用于社区——**不同视角的价值高于共识**
- 反对同态——不要为了和谐而回避分歧
- 所有讨论必须是**可追溯的**（公开 Issue/PR，不接受私聊决策）

---

## 📊 运行成本

| 项目 | 预估 |
|------|------|
| 采集 | 免费（RSS/API 调用） |
| NER 快速级 | CPU 毫秒级，免费 |
| NER 精校级（可选） | 按 API 计费 |
| 趋势分析 | 本地计算，免费 |
| 报告生成 | ~$0.05-0.15/天（DeepSeek） |

典型场景（10 个 RSS 源 + 每日报告）每天 API 费用约 **$0.05-0.15**。

---

## ❓ 常见问题

**需要 GPU 吗？** 不需要。整条管道跑在 2C4G 机器上绰绰有余。

**数据存哪里？** 默认 `~/.orcas/`，全部本地 SQLite + JSON。

**能换别的 LLM 吗？** 可以。config.yaml 改 `llm.provider` 和 `llm.model` 即可。

**怎么加我自己的分析逻辑？** `analysis/` 下新建文件，实现 `analyze(db)` 接口，框架自动发现。

**我不同意三元制衡的理念怎么办？** 欢迎开 Issue 辩论。这个项目的价值就在于不同的视角。

---

## 🙏 致谢

- [**Hermes Agent**](https://github.com/NousResearch/hermes-agent) — 驱动本项目的 AI Agent 框架
- [**DeepSeek**](https://github.com/deepseek-ai/DeepSeek-V3) — 为本项目提供核心推理能力的 LLM
- [**OpenViking**](https://github.com/volcengine/OpenViking) — Thought Ingestion 模块的 L0/L1/L2 三级记忆管理与检索思路源于此项目
- 所有开源项目的维护者，你们的 work 是这一切的基础

## 📄 许可

MIT License — 代码随意使用，理念欢迎碰撞。
