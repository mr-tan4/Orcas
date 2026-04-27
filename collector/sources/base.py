"""sources/base.py — Source Adapter 基类
所有自定义数据源适配器应继承此类。
"""

from typing import List, Dict, Any


class BaseSourceAdapter:
    """数据源适配器基类"""
    
    name = "base"
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    def fetch(self) -> List[Dict[str, Any]]:
        """获取数据，返回结构化条目列表
        
        每个条目应包含：
            - title: 标题
            - description: 描述/内容
            - url: 原文链接
            - published: 发布时间
            - source: 来源名称
        
        Returns:
            条目列表
        """
        raise NotImplementedError
