# Orcas 部署指南

> 三种部署方式，覆盖不同用户和不同 Agent 环境。
> 选择最适合你的一种。

---

## 方式一：一键脚本（推荐入门）

适用于任何环境（macOS / Linux），不依赖 AI Agent。

```bash
bash <(curl -s https://raw.githubusercontent.com/mr-tan4/Orcas/main/install.sh)
```

脚本会自动完成：
1. 检查 Python 3.10+、git
2. 克隆仓库到 `~/orcas`
3. 安装 Python 依赖
4. 创建默认配置文件
5. 初始化知识图谱

**自定义安装目录**：
```bash
INSTALL_DIR=/path/to/orcas bash <(curl -s ...)
```

---

## 方式二：AI Agent 自部署

适用于运行 Hermes Agent、Claude Code 等 AI Agent 的环境。

**支持的 Agent**：

| Agent | 状态 | 说明 |
|-------|------|------|
| **Hermes Agent** | ✅ 推荐 | 将 `docs/ARCHITECTURE.md` 发给 Agent，说"部署 Orcas" |
| **Claude Code** | ✅ 支持 | `claude -p "$(cat docs/ARCHITECTURE.md) Deploy Orcas"` |
| **DeepCode** | ⚠️ 部分支持 | 仅交互式 TTY 模式，参考下方手动步骤 |
| **Oh My Pi** | ⚠️ 待验证 | 支持交互式部署 |

### 手动步骤（所有 Agent 通用）

如果 Agent 不支持自动执行，或自部署失败，可以分步执行：

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置
cp config.example.yaml config.yaml
# 编辑 config.yaml 填入数据源和 API Key

# 3. 初始化 KG
python3 -m knowledge-graph.loader --seed-only

# 4. 全链路验证
python3 -m collector.collector --all
python3 -m knowledge-graph.loader --incremental
python3 -m analysis.trend_analysis snapshot
python3 -m analysis.trend_analysis trending
```

---

## 方式三：Docker（即将推出）

> 计划中，欢迎贡献。

---

## 环境要求

| 项目 | 最低 | 推荐 |
|------|------|------|
| Python | 3.10 | 3.11+ |
| 内存 | 512 MB | 1 GB+ |
| 磁盘 | 100 MB | 1 GB（知识图谱增长后） |
| 网络 | 出站可访问数据源 | — |
| GPU | 不需要 | — |

## 验证部署

```bash
cd ~/orcas
python3 -m scripts.health_check
```

期望输出：
```
✅ 数据库连接正常
✅ 配置文件可读
✅ 知识图谱已初始化
✅ 采集器可用
```

---

## 常见部署问题

### "ModuleNotFoundError: No module named 'knowledge-graph'"

当前目录不在 Python 路径中。使用 `python3 -m` 运行，或：
```bash
cd ~/orcas
export PYTHONPATH=$PWD:$PYTHONPATH
```

### pip install 失败

尝试使用虚拟环境：
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Agent 无法克隆仓库

如果 AI Agent 提示"git clone 需要授权"，请手动克隆后重试：
```bash
git clone https://github.com/mr-tan4/Orcas.git ~/orcas
```
然后告诉 Agent"代码已在 ~/orcas，继续部署"。

---

## 架构参考

完整系统设计请阅读 [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)。

快速概览：

```
数据采集（RSS/API）
    ↓
实体提取（两级 NER：快速级+精校级）
    ↓
知识图谱入库（增量/全量）
    ↓
趋势分析（快照对比）
    ↓
报告生成
```
