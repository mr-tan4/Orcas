#!/usr/bin/env python3
"""
新闻收集器 — 通用采集框架
从配置文件定义的数据源获取内容，清洗去重后输出结构化 JSON。
数据源通过 YAML 配置文件配置，具体源由使用者定义。
"""

import os
import sys
import time
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import feedparser
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NewsCollector:
    """新闻收集器"""
    
    def __init__(self, config_path: str = None, target_date: str = None):
        """初始化收集器"""
        # 设置目标日期（默认为今天）
        if target_date:
            self.target_date = target_date
        else:
            from datetime import datetime
            self.target_date = datetime.now().strftime('%Y-%m-%d')
        
        self.config = self.load_config(config_path)
        self.session = self.create_session()
        self.processed_items = []
        
    def load_config(self, config_path: str = None) -> Dict[str, Any]:
        """加载配置文件
        
        优先级: 1) 传入路径  2) 脚本同级目录 sources.yaml  3) 默认配置
        """
        # 确定 YAML 文件路径
        search_paths = []
        if config_path:
            search_paths.append(config_path)
        search_paths.append(os.path.join(os.path.dirname(__file__), '..', 'sources.yaml'))
        search_paths.append(os.path.join(os.path.dirname(__file__), 'sources.yaml'))

        for sp in search_paths:
            if os.path.exists(sp):
                import yaml
                with open(sp, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f)

        # 降级：硬编码默认配置（仅用于未找到 YAML 的极端情况）
        import yaml
        default_yaml = """
# ==================== 示例配置 ====================
# 将此文件保存为 sources.yaml 并修改成你的数据源
# 支持的数据源类型: rss, api
#
# RSS:
#   - name: 唯一标识
#     type: rss
#     url: RSS Feed URL
#     category: 分类标签
#     language: zh-CN / en
#
# API:
#   - name: 唯一标识
#     type: api
#     endpoint: API 地址
#     category: 分类标签
#     json_path: JSONPath 表达式
#     extract_fields:
#       title: "$.title"
#       description: "$.description"
#       url: "$.url"
sources:
  - name: example_rss
    type: rss
    url: "https://example.com/feed.xml"
    category: technology
    language: en
http:
  timeout: 30
  headers:
    User-Agent: "Orcas-Collector/1.0"
    Accept: "application/rss+xml,application/xml;q=0.9,*/*;q=0.8"
  retry_on_status: [429, 502, 503, 504]
fallback:
  on_parse_error: skip_and_log
  on_http_error: retry_then_skip
  min_success_rate: 0.6
"""
        logger.warning("未找到 sources.yaml，使用内联示例配置（请配置你的数据源）")
        return yaml.safe_load(default_yaml)
    
    def create_session(self) -> requests.Session:
        """创建 HTTP 会话"""
        session = requests.Session()
        
        # 设置重试策略
        retry_strategy = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # 设置默认头
        session.headers.update(self.config['http']['headers'])
        
        return session
    
    
    def fetch_rss(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取 RSS 源数据"""
        try:
            logger.info(f"获取 RSS 源: {source['name']}")
            
            max_items = source.get('max_items', 10)
            
            # 使用requests获取XML内容
            response = self.session.get(
                source['url'],
                timeout=self.config['http']['timeout']
            )
            response.raise_for_status()
            
            # 尝试使用feedparser解析
            feed = feedparser.parse(response.content)
            
            # 如果feedparser没有解析出条目，尝试直接解析XML
            if not feed.entries:
                logger.warning(f"feedparser未解析出条目，尝试直接解析XML: {source['name']}")
                import xml.etree.ElementTree as ET
                
                # 解析XML
                root = ET.fromstring(response.content)
                
                # 查找所有item元素（RSS 2.0标准）
                namespace = {'atom': 'http://www.w3.org/2005/Atom'}
                items_elem = root.findall('.//item')
                
                items = []
                for item_elem in items_elem[:max_items]:  # 限制数量
                    title_elem = item_elem.find('title')
                    description_elem = item_elem.find('description')
                    link_elem = item_elem.find('link')
                    pubdate_elem = item_elem.find('pubDate')
                    
                    item = {
                        'title': title_elem.text if title_elem is not None else '',
                        'description': description_elem.text if description_elem is not None else '',
                        'url': link_elem.text if link_elem is not None else '',
                        'published': pubdate_elem.text if pubdate_elem is not None else '',
                        'source': source['name'],
                        'source_name': source['name'],
                        'category': source['category'],
                        'language': source.get('language', 'zh-CN')
                    }
                    
                    # 关键词过滤（针对军事/时政源）
                    if 'filter_keywords' in source:
                        content = f"{item['title']} {item['description']}"
                        if not any(keyword in content for keyword in source['filter_keywords']):
                            continue
                    
                    items.append(item)
                
                logger.info(f"从 {source['name']} 获取到 {len(items)} 条新闻（XML解析）")
                return items
            
            # 使用feedparser解析的结果
            items = []
            for entry in feed.entries[:max_items]:  # 限制数量
                item = {
                    'title': entry.get('title', ''),
                    'description': entry.get('description', '') or entry.get('summary', ''),
                    'url': entry.get('link', ''),
                    'published': entry.get('published', '') or entry.get('updated', ''),
                    'source': source['name'],
                    'source_name': source['name'],
                    'category': source['category'],
                    'language': source.get('language', 'zh-CN')
                }
                
                # 关键词过滤（针对军事/时政源）
                if 'filter_keywords' in source:
                    content = f"{item['title']} {item['description']}"
                    if not any(keyword in content for keyword in source['filter_keywords']):
                        continue
                
                items.append(item)
            
            logger.info(f"从 {source['name']} 获取到 {len(items)} 条新闻")
            return items
            
        except Exception as e:
            logger.error(f"获取 RSS 源 {source['name']} 失败: {e}")
            return []
    
    def fetch_api(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取 API 源数据"""
        try:
            logger.info(f"获取 API 源: {source['name']}")
            
            headers = source.get('headers', {})
            params = source.get('params', {})
            
            response = self.session.get(
                source['endpoint'],
                headers=headers,
                params=params,
                timeout=self.config['http']['timeout']
            )
            response.raise_for_status()
            
            data = response.json()
            
            # 解析 JSON 路径
            import jsonpath_ng
            jsonpath_expr = jsonpath_ng.parse(source['json_path'])
            matches = [match.value for match in jsonpath_expr.find(data)]
            
            items = []
            for match in matches:
                item = {
                    'source': source['name'],
                    'category': source['category']
                }
                
                # 提取字段
                for field, path in source['extract_fields'].items():
                    try:
                        expr = jsonpath_ng.parse(path)
                        value = [m.value for m in expr.find(match)]
                        item[field] = value[0] if value else ''
                    except:
                        item[field] = ''
                
                items.append(item)
            
            logger.info(f"从 {source['name']} 获取到 {len(items)} 条数据")
            return items
            
        except Exception as e:
            logger.error(f"获取 API 源 {source['name']} 失败: {e}")
            return []
    
    def deduplicate(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """去重处理 (支持 RSS 新闻和 GitHub Trending)"""
        deduped = []
        seen_urls = set()  # 用于追踪 URL 去重
        
        for item in items:
            # 统一去重策略：基于 title+description+url 的 hash
            content = f"{item.get('title', '')}{item.get('description', '')}{item.get('url', '')}"
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            
            if content_hash not in seen_urls:
                seen_urls.add(content_hash)
                item['content_hash'] = content_hash
                deduped.append(item)
        
        logger.info(f"去重后剩余 {len(deduped)} 条数据")
        return deduped
    
    def filter_today_news(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """过滤今日新闻"""
        from datetime import datetime
        
        today_items = []
        today_str = self.target_date
        
        for item in items:
            publish_time = item.get('published', '')
            
            # 尝试解析发布时间
            try:
                # RSS 时间格式：Mon, 07 Apr 2026 06:30:00 GMT
                if publish_time:
                    # 简化处理：检查是否包含今天的日期
                    if today_str in publish_time:
                        today_items.append(item)
                    else:
                        # 尝试解析时间戳
                        try:
                            dt = datetime.strptime(publish_time, '%a, %d %b %Y %H:%M:%S %Z')
                            if dt.strftime('%Y-%m-%d') == today_str:
                                today_items.append(item)
                        except:
                            # 如果无法解析，跳过
                            pass
                else:
                    # 没有发布时间，默认保留（如 GitHub 数据）
                    today_items.append(item)
            except Exception as e:
                logger.warning(f"解析发布时间失败: {publish_time}, 错误: {e}")
        
        logger.info(f"今日新闻过滤: {len(items)} -> {len(today_items)} 条")
        return today_items
    
    def enrich_with_llm(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """使用 LLM 生成标签和摘要"""
        logger.info(f"准备为 {len(items)} 条数据生成标签和摘要")
        
        # 如果没有数据，直接返回
        if not items:
            return items
        
        # 预定义的标签类别（根据配置文件要求）
        tag_categories = [
            "国际", "财经", "时政", "科技", "军事", "社会", "文化", "体育", "娱乐", "健康",
            "教育", "环境", "能源", "交通", "房地产", "金融", "互联网", "人工智能", "区块链", "5G"
        ]
        
        enriched_items = []
        
        for i, item in enumerate(items):
            try:
                # 准备内容
                title = item.get('title', '')
                description = item.get('description', '')
                content = f"{title} {description}"
                
                # 如果内容太短，跳过LLM处理
                if len(content.strip()) < 10:
                    item['tags'] = ['未分类']
                    item['summary'] = description[:100] if description else title[:50]
                    item['confidence'] = 0.0
                    enriched_items.append(item)
                    continue
                
                # 使用简单的规则匹配生成标签（在没有LLM API的情况下）
                tags = []
                
                # 根据源类别添加基础标签
                category = item.get('category', '')
                if category:
                    tags.append(category)
                
                # 根据关键词匹配标签（中英文混合）
                content_lower = content.lower()
                
                # 军事相关内容必须标注"军事"标签
                military_keywords = ['军事', '军队', '国防', '战争', '冲突', '演习', '武器', '导弹', '海军', '空军', '陆军',
                                     'military', 'army', 'navy', 'air force', 'missile', 'warfare', 'defense', 'weapon']
                if any(keyword in content_lower for keyword in military_keywords):
                        tags.append('军事')
                
                # 其他关键词匹配（中英双语）
                keyword_to_tag = {
                    '国际': ['国际', '外交', '联合国', '大使', '领事', 
                            'foreign', 'diplomacy', 'united nations', 'ambassador', 'global', 'sanction'],
                    '财经': ['经济', '金融', '股市', '投资', '银行', '货币', '汇率',
                            'economy', 'stock', 'market', 'investment', 'bank', 'finance', 'trade', 'tariff', 'interest rate'],
                    '时政': ['政治', '政府', '政策', '领导人', '选举', '议会',
                            'government', 'policy', 'president', 'congress', 'parliament', 'election', 'regulation'],
                    '科技': ['科技', '技术', '创新', '研发', '科学', '实验室',
                            'technology', 'tech', 'innovation', 'scientific', 'research', 'engineering'],
                    '人工智能': ['AI', '人工智能', '机器学习', '深度学习', '神经网络', 'machine learning', 'deep learning',
                              'neural network', 'transformer', 'LLM', 'model', 'agent'],
                    '互联网': ['互联网', '网络', '在线', '电商', '平台', 'APP',
                            'internet', 'web', 'online', 'platform', 'app', 'software'],
                    '5G': ['5G', '通信', '网络技术', '移动通信'],
                    '区块链': ['区块链', '比特币', '加密货币', '数字货币', 'blockchain', 'bitcoin', 'crypto', 'ethereum'],
                    '环境': ['环境', '气候', '污染', '环保', '生态', '可持续发展',
                            'climate', 'environment', 'pollution', 'sustainability', 'green'],
                    '能源': ['能源', '石油', '天然气', '电力', '新能源', '太阳能', '风能',
                            'energy', 'oil', 'gas', 'power', 'solar', 'renewable'],
                    '健康': ['健康', '医疗', '医院', '医生', '疫苗', '疾病', '疫情',
                            'health', 'medical', 'hospital', 'vaccine', 'disease', 'pandemic', 'covid'],
                    '体育': ['体育', '比赛', '运动员', '奥运', '足球', '篮球', '网球',
                            'sports', 'game', 'olympic', 'championship', 'tournament'],
                    '娱乐': ['娱乐', '电影', '音乐', '明星', '艺人', '综艺', '电视剧',
                            'entertainment', 'movie', 'music', 'film', 'celebrity', 'game']
                }
                
                for tag, keywords in keyword_to_tag.items():
                    if any(keyword in content for keyword in keywords):
                        if tag not in tags:
                            tags.append(tag)
                
                # 如果没有匹配到标签，使用源类别或默认标签
                if not tags:
                    category = item.get('category', '')
                    if category and category != 'uncategorized':
                        tags = [category]
                    else:
                        tags = ['未分类']
                
                # 限制标签数量
                tags = tags[:5]
                
                # 生成摘要
                summary = description[:150] if description else title[:100]
                if not summary:
                    summary = content[:100]
                
                # 添加标签和摘要
                item['tags'] = tags
                item['summary'] = summary
                item['confidence'] = 0.8 if len(tags) > 1 else 0.5
                
                enriched_items.append(item)
                
                logger.debug(f"已处理 {i+1}/{len(items)}: {title[:30]}... -> 标签: {tags}")
                
            except Exception as e:
                logger.error(f"处理第 {i+1} 条数据时出错: {e}")
                # 出错时添加默认值
                item['tags'] = ['处理错误']
                item['summary'] = item.get('description', '')[:50] + '...'
                item['confidence'] = 0.0
                enriched_items.append(item)
        
        logger.info(f"已为 {len(enriched_items)} 条数据生成标签和摘要")
        return enriched_items
    
    def persist_to_vectorstore(self, items: List[Dict[str, Any]]) -> bool:
        """持久化到知识库目录（raw/ + kb/ 双写）"""
        logger.info(f"准备持久化 {len(items)} 条数据到知识库")
        
        # 知识库基础路径
        ORCAS_HOME = os.environ.get("ORCAS_HOME", os.path.expanduser("~/.orcas"))
        kb_base = os.path.join(ORCAS_HOME, "news")
        raw_dir = os.path.join(kb_base, 'raw')
        data_dir = os.path.join(kb_base, 'data')
        os.makedirs(raw_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        date_str = datetime.now().strftime('%Y-%m-%d')
        
        # === 保存原始数据到 raw/（供分析系统读取）===
        raw_file = os.path.join(raw_dir, f'raw_news_{timestamp}.json')
        with open(raw_file, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        logger.info(f"原始数据已保存到: {raw_file}")
        
        # 同时写 daily 文件方便按日查看
        raw_daily = os.path.join(raw_dir, f'raw_news_{date_str}.json')
        with open(raw_daily, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        logger.info(f"每日原始数据已保存到: {raw_daily}")
        
        # === 保存标准格式到 data/（兼容 tagged_news 格式）===
        standard_items = []
        for item in items:
            standard_item = {
                'title': item.get('title', ''),
                'url': item.get('url', '') or item.get('link', ''),
                'source': item.get('source', 'unknown'),
                'source_name': item.get('source_name', item.get('source', 'unknown')),
                'published': item.get('published', ''),
                'summary': item.get('summary', ''),
                'content': item.get('description', ''),
                'tags': item.get('tags', []),
                'category': item.get('category', '未分类'),
                'language': item.get('language', 'zh-CN'),
                'confidence': item.get('confidence', 0.5),
                'content_hash': item.get('content_hash', ''),
                'collect_time': timestamp
            }
            standard_items.append(standard_item)
        
        # 按标签分文件保存
        date_tagged_file = os.path.join(data_dir, f'tagged_news_{date_str}.json')
        with open(date_tagged_file, 'w', encoding='utf-8') as f:
            json.dump(standard_items, f, ensure_ascii=False, indent=2)
        logger.info(f"标记数据已保存到: {date_tagged_file}")
        
        # 更新 latest 文件
        latest_file = os.path.join(data_dir, 'latest_news.json')
        with open(latest_file, 'w', encoding='utf-8') as f:
            json.dump(standard_items, f, ensure_ascii=False, indent=2)
        logger.info(f"最新数据已保存到: {latest_file}")
        
        # 汇总所有 tagged_news 文件 (合并近7天)
        self._merge_tagged_news(data_dir, date_str)
        
        return True
    
    def _merge_tagged_news(self, data_dir: str, today_str: str):
        """合并近7天的 tagged_news 文件为一个完整文件"""
        try:
            all_items = []
            seen_hashes = set()
            
            # 读取当前目录下所有 tagged_news_ 文件
            for fname in sorted(os.listdir(data_dir)):
                if not fname.startswith('tagged_news_') or not fname.endswith('.json'):
                    continue
                file_path = os.path.join(data_dir, fname)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        items = json.load(f)
                    for item in items:
                        h = item.get('content_hash', '')
                        if h and h not in seen_hashes:
                            seen_hashes.add(h)
                            all_items.append(item)
                        elif not h:
                            all_items.append(item)
                except Exception as e:
                    logger.warning(f"读取 {fname} 失败: {e}")
            
            if all_items:
                complete_file = os.path.join(data_dir, f'tagged_news_{today_str}.json')
                with open(complete_file, 'w', encoding='utf-8') as f:
                    json.dump(all_items, f, ensure_ascii=False, indent=2)
                logger.info(f"合并完成: {len(all_items)} 条 -> {complete_file}")
        except Exception as e:
            logger.error(f"合并 tagged_news 失败: {e}")
        
        return True
    
    def broadcast_event(self, items: List[Dict[str, Any]]) -> None:
        """广播事件"""
        logger.info(f"广播事件: 新新闻入库 {len(items)} 条")
        # 这里可以集成 OpenClaw 的事件系统
    
    def run(self) -> Dict[str, Any]:
        """运行收集器"""
        logger.info("开始运行新闻收集器")
        
        all_items = []
        success_sources = 0
        
        
        # 1. 获取数据
        for source in self.config['sources']:
            try:
                source_type = source['type']
                
                if source_type == 'rss':
                    items = self.fetch_rss(source)
                elif source_type == 'api':
                    items = self.fetch_api(source)
                else:
                    logger.warning(f"未知源类型: {source_type}")
                    continue
                
                if items:
                    success_sources += 1
                    all_items.extend(items)
                    
            except Exception as e:
                logger.error(f"处理源 {source['name']} 时出错: {e}")
        
        # 检查成功率
        total_sources = len(self.config['sources'])
        success_rate = success_sources / total_sources if total_sources > 0 else 0
        
        if success_rate < self.config['fallback']['min_success_rate']:
            logger.warning(f"成功率 {success_rate:.2%} 低于阈值 {self.config['fallback']['min_success_rate']:.2%}")
        
        # 2. 去重
        deduped_items = self.deduplicate(all_items)
        
        # 3. 过滤今日新闻
        today_items = self.filter_today_news(deduped_items)
        
        # 4. 标签和摘要
        enriched_items = self.enrich_with_llm(today_items)
        
        # 4. 持久化
        persist_success = self.persist_to_vectorstore(enriched_items)
        
        # 5. 事件通知
        if persist_success and enriched_items:
            self.broadcast_event(enriched_items)
        
        result = {
            'total_sources': total_sources,
            'success_sources': success_sources,
            'success_rate': success_rate,
            'total_items': len(all_items),
            'deduped_items': len(deduped_items),
            'today_items': len(today_items),
            'enriched_items': len(enriched_items),
            'persist_success': persist_success,
            'target_date': self.target_date,
            'timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"收集器运行完成: {result}")
        return result

def main():
    """主函数"""
    collector = NewsCollector()
    
    try:
        result = collector.run()
        
        # 输出结果
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        # 检查是否成功
        if result['success_rate'] >= collector.config['fallback']['min_success_rate']:
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"收集器运行失败: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()