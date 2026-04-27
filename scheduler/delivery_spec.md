# 投递规范

## 概述

Orcas 的报告和分析结果通过投递适配器分发到各平台。投递层采用适配器模式，核心系统产出标准 Markdown 格式，由适配器按平台特性转换。

## 内置投递目标

| 目标 | 说明 | 配置 |
|------|------|------|
| `console` | 终端标准输出 | 无需额外配置 |
| `file` | 保存到本地文件 | 需指定 `path` |

## 自定义投递适配器

在 `scheduler/delivery/` 下创建文件，实现以下接口：

```python
class DeliveryAdapter:
    """投递适配器接口"""
    
    def deliver(self, content: str, config: dict) -> bool:
        """投递内容到目标平台
        
        Args:
            content: Markdown 格式的报告内容
            config: 平台配置
        
        Returns:
            是否投递成功
        """
        raise NotImplementedError
```

在 `scheduler/delivery/__init__.py` 中注册。

## 报告格式

所有报告输出标准 Markdown，包含：

```markdown
# 报告标题
生成时间: YYYY-MM-DD HH:mm

## 章节

- 条目 1
- 条目 2

---

元数据
```

## 文件投递标记

支持用 `MEDIA:` 前缀标记文件路径，由适配器处理：

```
MEDIA:/path/to/file
```

平台适配器应根据自身能力：
- 微信/Telegram → 作为文件发送
- Console → 打印文件路径
