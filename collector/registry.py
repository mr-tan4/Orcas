"""collector registry — 数据源适配器注册表
所有 Source Adapter 在此注册后，主循环自动发现并调用。
"""

import logging
logger = logging.getLogger(__name__)

# 内置适配器注册表
_BUILTIN_ADAPTERS = {}

def register(name: str, adapter_class):
    """注册一个数据源适配器"""
    _BUILTIN_ADAPTERS[name] = adapter_class
    logger.debug(f"注册采集适配器: {name}")

def get_adapter(source_type: str):
    """获取指定类型的采集适配器
    
    Args:
        source_type: 数据源类型 (rss, api 等)
    
    Returns:
        适配器类，未注册返回 None
    """
    return _BUILTIN_ADAPTERS.get(source_type)

def list_adapters():
    """列出所有已注册的适配器"""
    return dict(_BUILTIN_ADAPTERS)
