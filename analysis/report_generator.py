"""analysis/report_generator.py — 综合报告生成器
汇总各分析结果，调用 LLM 生成可读的综合报告。
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

ORCAS_HOME = os.environ.get("ORCAS_HOME", os.path.expanduser("~/.orcas"))


class ReportGenerator:
    """综合报告生成器"""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(ORCAS_HOME, "kg.db")
    
    def collect_data(self) -> Dict[str, Any]:
        """收集所有分析数据"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "trending": self._get_trending(),
            "new_entities": self._get_new_entities(),
            "bursts": self._get_bursts(),
            "stats": self._get_stats(),
        }
        return data
    
    def _get_trending(self) -> list:
        """获取趋势数据"""
        try:
            from analysis.trend_analysis import cmd_trending
            # 这里预期趋势分析模块提供一个可调用接口
            return []
        except ImportError:
            logger.warning("趋势分析模块未加载")
            return []
    
    def _get_new_entities(self) -> list:
        """获取新发现实体"""
        return []
    
    def _get_bursts(self) -> list:
        """获取突发检测结果"""
        return []
    
    def _get_stats(self) -> Dict[str, int]:
        """获取 KG 基础统计"""
        return {"entities": 0, "relations": 0}
    
    def generate(self, llm_config: Optional[Dict] = None) -> str:
        """生成综合报告
        
        Args:
            llm_config: LLM 配置（provider, api_key, model 等）
        
        Returns:
            报告文本
        """
        data = self.collect_data()
        
        # 构造报告内容
        lines = [
            f"# Orcas 知识报告",
            f"生成时间: {data['timestamp']}",
            "",
            "## 趋势概览",
            *([f"- {e}" for e in data['trending'][:10]] or ["- 暂无趋势数据"]),
            "",
            "## 新发现",
            *([f"- {e}" for e in data['new_entities'][:10]] or ["- 无"]),
            "",
            "## 突发信号",
            *([f"- {b}" for b in data['bursts'][:5]] or ["- 无"]),
            "",
            "---",
            f"KG 统计: {data['stats']['entities']} 实体, {data['stats']['relations']} 关系",
        ]
        
        report = "\n".join(lines)
        
        # 保存到文件
        report_dir = os.path.join(ORCAS_HOME, "reports")
        os.makedirs(report_dir, exist_ok=True)
        report_path = os.path.join(report_dir, f"report_{datetime.now().strftime('%Y%m%d')}.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        
        logger.info(f"报告已生成: {report_path}")
        return report


def main():
    """CLI 入口"""
    generator = ReportGenerator()
    report = generator.generate()
    print(report)


if __name__ == "__main__":
    main()
