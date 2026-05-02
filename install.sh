#!/usr/bin/env bash
#
# Orcas 一键部署脚本
# 用法: bash <(curl -s https://raw.githubusercontent.com/mr-tan4/Orcas/main/install.sh)
#
# 支持: macOS / Linux
# 依赖: Python 3.10+, git, pip
#
set -euo pipefail

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }
info() { echo -e "${CYAN}[i]${NC} $1"; }

# ── 检查依赖 ──
info "检查系统依赖..."

OS="$(uname -s)"
PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    PYTHON="$cmd"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  err "未找到 Python 3.10+。请先安装:"
  err "  macOS: brew install python"
  err "  Linux: apt install python3 python3-pip"
  exit 1
fi

PYVER=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
if [ "$(echo "$PYVER" | cut -d. -f1)" -lt 3 ] || { [ "$(echo "$PYVER" | cut -d. -f1)" -eq 3 ] && [ "$(echo "$PYVER" | cut -d. -f2)" -lt 10 ]; }; then
  err "需要 Python 3.10+，当前: $PYTHON $PYVER"
  exit 1
fi
log "Python: $($PYTHON --version)"

if ! command -v git &>/dev/null; then
  err "未找到 git。请先安装。"
  exit 1
fi
log "Git: $(git --version)"

# ── 设置安装目录 ──
INSTALL_DIR="${INSTALL_DIR:-$HOME/orcas}"
info "安装目录: $INSTALL_DIR"

# ── 克隆仓库 ──
if [ -d "$INSTALL_DIR" ]; then
  warn "目录已存在: $INSTALL_DIR"
  info "更新中..."
  cd "$INSTALL_DIR"
  git pull --rebase 2>/dev/null || warn "git pull 失败，使用已有代码"
else
  info "克隆仓库..."
  git clone --depth 1 https://github.com/mr-tan4/Orcas.git "$INSTALL_DIR"
  cd "$INSTALL_DIR"
  log "仓库已克隆"
fi

# ── 安装 Python 依赖 ──
info "安装 Python 依赖..."
if [ -f "requirements.txt" ]; then
  $PYTHON -m pip install --quiet -r requirements.txt 2>/dev/null || {
    warn "pip install 失败，尝试使用虚拟环境..."
    $PYTHON -m venv .venv
    source .venv/bin/activate
    $PYTHON -m pip install --quiet -r requirements.txt
    log "虚拟环境已创建在 .venv/"
    echo ""
    info "下次使用 Orcas 前请先: source $INSTALL_DIR/.venv/bin/activate"
  }
  log "Python 依赖安装完成"
else
  warn "未找到 requirements.txt，跳过依赖安装"
fi

# ── 配置 ──
CONFIG_FILE="$INSTALL_DIR/config.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
  info "创建默认配置文件..."
  cp config.example.yaml config.yaml 2>/dev/null || warn "config.example.yaml 不存在"
  log "配置文件: $CONFIG_FILE"
  info "请编辑 config.yaml 填入你的数据源和 API Key"
else
  info "配置文件已存在，跳过"
fi

# ── 初始化知识图谱 ──
info "初始化知识图谱..."
if $PYTHON -m knowledge-graph.loader --seed-only 2>/dev/null; then
  log "知识图谱初始化完成"
else
  warn "知识图谱初始化跳过（脚本可能在 knowledge-graph/ 目录下需要调整路径）"
  warn "稍后可手动执行: cd $INSTALL_DIR && $PYTHON -m knowledge-graph.loader --seed-only"
fi

# ── 验证 ──
echo ""
log "═══════════════════════════════════════════"
log " Orcas 部署完成！"
log "═══════════════════════════════════════════"
echo ""
info "  安装目录: $INSTALL_DIR"
info "  配置文件: $CONFIG_FILE"
info "  快速验证: cd $INSTALL_DIR && $PYTHON -m scripts.health_check"
echo ""
info "  全链路运行一次:"
info "    cd $INSTALL_DIR"
info "    $PYTHON -m collector.collector --all"
info "    $PYTHON -m knowledge-graph.loader --incremental"
info "    $PYTHON -m analysis.trend_analysis snapshot"
echo ""
info "  AI Agent 自部署:"
info "    将 docs/ARCHITECTURE.md 交给你的 Hermes Agent"
info "    说: 部署 Orcas"
echo ""
info "  文档:"
info "    📜 理念: docs/MANIFESTO.md"
info "    🏗️  架构: docs/ARCHITECTURE.md"
info "    📖 Wiki: https://github.com/mr-tan4/Orcas/wiki"
echo ""
