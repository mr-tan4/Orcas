# Orcas Governance Tools

治理工具套件，用于决策追踪、风险评估和 Schema 合规审计。

---

## 工具列表

### audit.py — Schema 合规审计

审计知识图谱数据库（SQLite）的治理 Schema 合规性。

```bash
python3 audit.py                              # 审计默认数据库 (~/.orcas/knowledge_graph.db)
python3 audit.py --db /path/to/db             # 审计自定义数据库
python3 audit.py --fix                        # 自动修复可修复的违规项
```

审计项：
1. 零 co_occurrence — 个人聚落内禁止共现关系
2. judgment.author 分布 — 判断实体的作者字段
3. settlement 标记一致性 — 没有空值或非法值
4. 影子实体连接 — 确保影子实体有 corresponds_to 边
5. challenges 指向合规 — 不能指向助手自身的判断

### escalation.py — 越级上报检测器

检测助手视角报告中的越级上报信号。

```bash
python3 escalation.py --report report.md      # 扫描单个报告文件
```

四条检测规则：
1. frontmatter `status: challenged`
2. 表格行 `挑战原则前提 = 是`
3. 勾选框 `[x] 本视角挑战了框架原则体系中的前提假设`
4. 关键词启发式：前提不成立 near 框架原则

exit 0 = 未触发信号，exit 1 = 越级信号待处理。

### risk_rating.py — 决策风险评级

三维度评分工具，用于评估决策风险等级。

```bash
python3 risk_rating.py --decision "替换数据库"          # 快评模式
python3 risk_rating.py --interactive                    # 交互式评估
python3 risk_rating.py --examples                       # 示例对照表
python3 risk_rating.py --decision "..." --override A=3  # 覆写某维度分
```

三维度：
| 维度 | 权重 | 1分 | 2分 | 3分 |
|------|------|-----|-----|-----|
| A 可逆性 | 0.4 | 完全可逆 | 代价回滚 | 不可逆 |
| B 影响面 | 0.35 | 局部 | 系统内 | 架构级 |
| C 新颖度 | 0.25 | 已知路径 | 类比路径 | 全新路径 |

评级结果：
- **低风险** (1.0-1.6)：仅原则检查
- **中风险** (1.7-2.3)：标准三元审查
- **高风险** (2.4-3.0)：完整审查 + 前提破坏测试 + 越级上报

### experiment.py — 实验生命周期

假设→实验→验证→提炼→收录 的全周期管理工具。

```bash
python3 experiment.py new --title "..." --hypothesis "..."  # 创建新实验
python3 experiment.py list                                    # 列出所有实验
python3 experiment.py show EXP-YYYYMMDD-NNN                  # 查看实验详情
python3 experiment.py status EXP-YYYYMMDD-NNN                 # 查看流程进度
python3 experiment.py update EXP-YYYYMMDD-NNN --status ...    # 更新状态
```

实验文件存储在 `--dir` 指定的目录（默认 `./experiments/`）。

---

## 使用方式

### 独立使用

```bash
# 评估一个决策风险
python3 risk_rating.py --decision "把 DB 从 SQLite 切到 PostgreSQL"

# 审计你的知识图谱
python3 audit.py --db ~/my_knowledge_graph.db

# 检测视角报告中的越级信号
python3 escalation.py --report perspective_report.md
```

### 作为三元治理管道

```bash
# 完整流程
python3 risk_rating.py --decision "..."           # 1. 评级
python3 escalation.py --report report.md          # 2. 检测越级
python3 audit.py --db knowledge_graph.db          # 3. 审计合规性
```

---

## 设计原则

1. **纯 Python 标准库** — 零外部依赖
2. **单文件自包含** — 每个工具都是独立的 `.py` 文件
3. **stdin/stdout 友好** — 输出格式适合管道和脚本集成
4. **脱敏** — 不包含任何个人身份信息，使用角色名

---

## 与 Orcas 的关系

这些工具是 Orcas 认知方法论框架的「治理层」组件。
它们不依赖 Orcas 的其他模块（采集、NER、KG），可以独立使用。

详见 [`docs/MANIFESTO.md`](../docs/MANIFESTO.md) 获取完整的理念说明。
