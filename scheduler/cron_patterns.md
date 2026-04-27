# 定时任务配置模式

## 推荐方案

系统依赖系统 cron（`crontab -e`）或 Hermes Agent 内置调度器。

## 典型定时模式

| 任务 | 推荐频率 | 说明 |
|------|---------|------|
| 数据采集 | 每 2 小时 | RSS/API 数据源轮询 |
| KG 增量导入 | 采集后（+30min） | 将新数据导入知识图谱 |
| 趋势快照 | 每天 1 次（02:00） | 记录当日实体热度基准 |
| 趋势报告 | 每天 1 次（09:00） | 生成上升/新发现/突发报告 |
| 知识盲区扫描 | 每周 1 次（周日 04:00） | 检查稀疏节点 |
| 健康检查 | 每天 1 次（06:00） | 验证全链路状态 |

## crontab 示例

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

## 注意事项

- 所有路径使用绝对路径，避免 cron 环境变量问题
- Python 脚本需有可执行权限或使用 `python3` 前缀
- 日志默认输出到 `~/.orcas/logs/`
- 首次部署先手动跑一遍全链路，确认无误再开 cron
