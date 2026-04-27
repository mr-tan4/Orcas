#!/usr/bin/env python3
"""
ner_fast.py — 快速级 NER 实体提取

两级流程：
1. jieba 分词 → 提取名词/专有名词
2. 正则模式 → 产品名、版本号、GitHub repo、引号内容

输出：候选实体列表 [{"name": str, "source": "jieba"|"regex"|"seed", ...}]
"""

import re
import jieba
import json
import yaml
from pathlib import Path

# HTML 标签剥离器（单一编译正则，覆盖多种情况）
_HTML_RE = re.compile(r'<[^>]+>')
_URL_RE = re.compile(r'https?://\S+')
_ATTR_RE = re.compile(r'\b(?:src|href|alt|title|class|id|style|width|height|data-\w+)="[^"]*"')
_CSS_RE = re.compile(r'[a-z-]+:\s*[^;]+;')
_PARAM_RE = re.compile(r'\?[\w=&%-]+')
_IMG_RE = re.compile(r'\b\w+\.(?:png|jpg|jpeg|gif|svg|webp)\b', re.I)
_ENTITY_RE = re.compile(r'&[a-zA-Z]+;')
_NOISE_RE = re.compile(r'[.#][a-zA-Z][\w-]*')


def _strip_html(text):
    if not text:
        return ""
    text = _HTML_RE.sub(' ', text)
    text = _ATTR_RE.sub(' ', text)
    text = _CSS_RE.sub(' ', text)
    text = _URL_RE.sub(' ', text)
    text = _PARAM_RE.sub(' ', text)
    text = _IMG_RE.sub(' ', text)
    text = _ENTITY_RE.sub(' ', text)
    text = _NOISE_RE.sub(' ', text)
    # 所有 URI 组件（如 %E4%B8%AD%E5%9B%BD）
    text = re.sub(r'%[0-9A-Fa-f]{2}', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# ===================== 配置 =====================
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
USER_DICT_PATH = PROJECT_DIR / "ner_user_dict.txt"

# 停用词 — 这些词绝不作为实体
STOP_WORDS = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
    '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
    '自己', '这', '他', '她', '它', '们', '那', '与', '及', '或', '但', '而', '于',
    '其', '中', '等', '对', '被', '把', '从', '向', '让', '将', '以', '为', '能',
    '可', '已', '还', '又', '再', '才', '只', '什么', '怎么', '如何', '为什么',
    '这个', '那个', '这些', '那些',
    'title', 'content', 'summary', 'description', 'url', 'source', 'category', 'tags',
    'article', '文章', '新闻', '报道', '来源', '发布', '时间', '图片', '视频', '消息',
    'nbsp', 'lt', 'gt', 'amp', 'quot', '版权', '声明', '编辑', '责任编辑', '作者',
}

# 常见英文停用词
EN_STOP_WORDS = {
    'the', 'a', 'an', 'this', 'that', 'these', 'those', 'is', 'are', 'was', 'were',
    'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'shall', 'should', 'may', 'might', 'must', 'can', 'could', 'about', 'above',
    'after', 'again', 'all', 'also', 'any', 'because', 'before', 'between',
    'both', 'each', 'few', 'for', 'from', 'further', 'here', 'how', 'just',
    'more', 'most', 'no', 'nor', 'not', 'now', 'off', 'once', 'only', 'other',
    'our', 'out', 'over', 'own', 'same', 'some', 'such', 'than', 'then',
    'there', 'through', 'too', 'under', 'until', 'up', 'very', 'what', 'when',
    'where', 'which', 'while', 'who', 'why',
}

# 产品名+版本号正则
PATTERN_PRODUCT_VERSION = re.compile(
    r'([A-Za-z][A-Za-z0-9]+(?:[- ](?:Pro|Max|Ultra|Mini|Plus|Lite|Air|Neo|GT|SE|X))?)'
    r'(?:\s*(?:v?\d+[.]\d+(?:[.]\d+)?(?:[-_][a-zA-Z0-9]+)?))?'
)

# GitHub repo 模式
PATTERN_GITHUB_REPO = re.compile(r'(?:github\.com/)?([a-zA-Z0-9_-]+)/([a-zA-Z0-9._-]+)')

# 从新闻标题提取产品发布模式：品牌+空格+系列+空格+数字
PATTERN_BRAND_PRODUCT = re.compile(
    r'((?:华为|小米|苹果|三星|Google|Apple|Samsung|Xiaomi|Huawei|OPPO|vivo)\s*[A-Za-z0-9]+(?:\s[A-Za-z0-9]+)*(?:\s\d+[A-Za-z]?)?)'
)

# 引号内容
PATTERN_QUOTED = re.compile(r'[\u201c\u201d"]([^\u201c\u201d"]{2,20})[\u201c\u201d"]')

# 中文品牌系列（如"千帆星座"、"鸿蒙智行"、"混元大模型"）
# 中文品牌系列（如"千帆星座"、"鸿蒙智行"、"混元大模型"）
PATTERN_CN_PRODUCT = re.compile(r'(?<!\w)([\u4e00-\u9fff]{2,5}(?:星座|系统|平台|芯片|系列|方案|架构|引擎|工具|框架|协议|OS|操作系统|大模型|智行))')

# 版本号：如 GPT-4o-mini, DeepSeek-R1, Llama-3.1-8B, Qwen2.5-7B
PATTERN_VERSIONED = re.compile(
    r'\b([A-Za-z]+[-_.]?\d+(?:\.\d+)*(?:[A-Za-z]*(?:[-_.]\d+)*[A-Za-z]*(?:-\w+)*))\b'
)

# 驼峰/大驼峰技术术语（排除误匹配）
PATTERN_CAMEL_CASE = re.compile(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b')

# HTML/CSS残留过滤
LOW_QUALITY = {
    'text-align', 'center', 'list-paddingleft', 'nbsp', 'src', 'href',
    'jpg', 'png', 'gif', 'img', 'div', 'span', 'class', 'style',
    'None', 'null', 'undefined', 'True', 'False',
    'lt;', 'gt;', 'amp;', 'quot;', 'nbsp;',
    'strong', 'em', 'br', 'hr', 'ul', 'ol', 'li', 'p', 'a', 'table', 'tr', 'td', 'th',
    'placeholder', 'iframe', 'embed', 'object', 'param', 'meta', 'link', 'script',
    'format', 'auto', 'f_auto', 'process', 'align', 'border', 'margin', 'padding',
    'width', 'height', 'size', 'color', 'font', 'background',
}

# 加载 YAML 黑名单配置
_BLACKLIST_PATH = Path(__file__).parent / "ner_blacklist.yaml"

def _load_common_nouns():
    """从 YAML 加载通用名词黑名单"""
    if not _BLACKLIST_PATH.exists():
        return set()
    with open(_BLACKLIST_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    result = set()
    for category, items in config.items():
        for item in items:
            result.add(item)
    return result

COMMON_NOUNS = _load_common_nouns()


def _load_user_dict():
    """加载 jieba 用户词典（如果存在）"""
    if USER_DICT_PATH.exists():
        jieba.load_userdict(str(USER_DICT_PATH))
        return True
    return False


def _is_low_quality(name):
    """过滤低质量候选"""
    if len(name) < 2:
        return True
    if len(name) > 40:
        return True
    nl = name.lower()
    if nl in LOW_QUALITY:
        return True
    if any(nl.startswith(f) for f in {'text-align', 'list-paddingleft', 'nbsp', 'lt;'}):
        return True
    if re.search(r'[{}:;]', name):
        return True
    # 看起来像文件路径/URL片段
    if re.search(r'(?:newsuploadfiles|\.(?:jpg|png|gif|svg|webp|ico)|[/\\]|https?://|[0-9a-f]{8,})', nl):
        return True
    if re.match(r'^[\d\s\-_.,;:!@#$%^&*()+=/\\\[\]{}|`~<>]+$', name):
        return True
    # 纯2字母英文（通常是缩写但不是实体）
    if re.match(r'^[A-Za-z]{2}$', name) and name.upper() not in {'AI', 'GT', 'SE', 'GO', 'ID', 'IP', 'MX', 'XR', 'AR', 'VR', 'MR'}:
        return True
    # 纯3字母大写缩写（通用缩写白名单保留）
    ALLOWED_3LETTER = {'API', 'GPT', 'CPU', 'GPU', 'RAM', 'ROM', 'SSD', 'HDD',
                       'LCD', 'LED', 'USB', 'NFC', 'GPS', 'LTE', 'AWS', 'GCP'}
    if re.match(r'^[A-Z]{3}$', name) and name not in ALLOWED_3LETTER:
        return True
    # 纯英文单词且在停用词表
    if re.match(r'^[a-zA-Z]+$', name) and nl in EN_STOP_WORDS:
        return True
    if name in STOP_WORDS:
        return True
    # 单字中文
    if re.match(r'^[\u4e00-\u9fff]$', name):
        return True
    if name in COMMON_NOUNS:
        return True
    return False


def extract_by_jieba(text, top_n=10):
    """jieba 分词提取候选名词/专有名词"""
    import jieba.posseg as pseg
    words = pseg.cut(text)
    
    candidates = []
    seen = set()
    
    for word, flag in words:
        if _is_low_quality(word):
            continue
        # 中文单字/双字词大部分不是实体（除非在种子列表中）
        if re.match(r'^[\u4e00-\u9fff]{1,2}$', word):
            continue
        # 英文单词但少于3个字母（除非大写专名）
        if re.match(r'^[a-z]{1,3}$', word) and flag != 'nz':
            continue
        # 常见英文名词（非专名），不包含大写字母
        if flag == 'eng' and not re.search(r'[A-Z]', word):
            continue
        # 只保留有意义的词性
        # n=名词, ns=地名, nt=机构名, nz=专名, nr=人名, vn=动名词, eng=英文
        if flag in ('n', 'ns', 'nt', 'nz', 'nr', 'vn', 'eng', 'x'):
            key = word.lower()
            if key not in seen:
                seen.add(key)
                candidates.append({
                    "name": word,
                    "pos": flag,
                    "source": "jieba",
                    "length": len(word)
                })
    
    # 按长度降序（长词通常是更有意义的专名）
    candidates.sort(key=lambda x: -x['length'])
    return candidates[:top_n]


def extract_by_regex(title, content=""):
    """正则提取产品名、版本号、GitHub repo等"""
    combined = f"{title} {content}" if content else title
    candidates = []
    seen = set()
    
    # GitHub repo
    for m in PATTERN_GITHUB_REPO.finditer(combined):
        full = f"{m.group(1)}/{m.group(2)}"
        if full not in seen and not _is_low_quality(full):
            seen.add(full)
            candidates.append({"name": full, "pattern": "github_repo", "source": "regex"})
    
    # 品牌+产品
    for m in PATTERN_BRAND_PRODUCT.finditer(combined):
        name = m.group(1).strip()
        if name not in seen and not _is_low_quality(name):
            seen.add(name)
            candidates.append({"name": name, "pattern": "brand_product", "source": "regex"})
    
    # 中文产品名
    for m in PATTERN_CN_PRODUCT.finditer(combined):
        name = m.group(1).strip()
        if name not in seen and not _is_low_quality(name):
            seen.add(name)
            candidates.append({"name": name, "pattern": "cn_product", "source": "regex"})
    
    # 版本号（GPT-4o-mini, DeepSeek-R1 等）
    for m in PATTERN_VERSIONED.finditer(combined):
        name = m.group(1).strip()
        if name not in seen and not _is_low_quality(name):
            seen.add(name)
            candidates.append({"name": name, "pattern": "versioned", "source": "regex"})
    
    # 驼峰技术术语
    for m in PATTERN_CAMEL_CASE.finditer(combined):
        name = m.group(1).strip()
        if name not in seen and not _is_low_quality(name):
            seen.add(name)
            candidates.append({"name": name, "pattern": "camel_case", "source": "regex"})
    
    # 引号内容
    for m in PATTERN_QUOTED.finditer(combined):
        name = m.group(1).strip()
        if name not in seen and not _is_low_quality(name) and len(name) >= 2:
            # 过滤纯数字/符号的引号内容
            if not re.match(r'^[\d\s\-_.,:;!@#$%^&*()+=/]+$', name):
                seen.add(name)
                candidates.append({"name": name, "pattern": "quoted", "source": "regex"})
    
    return candidates


def fast_ner(title, content="", max_candidates=15):
    """
    快速级 NER 主入口
    
    参数：
        title: 新闻标题
        content: 正文摘要
        max_candidates: 最大候选数
    
    返回：
        [{"name": "实体名", "source": "jieba"|"regex", "pos": "词性" (可选)}, ...]
    """
    # 加载词典
    _load_user_dict()
    
    # 先清理 HTML
    if content:
        clean = _strip_html(content)
    else:
        clean = ""
    combined = f"{title} {clean[:2000]}" if clean else title
    
    # 1. jieba 分词提取
    jieba_candidates = extract_by_jieba(combined, top_n=10)
    
    # 2. 正则模式
    regex_candidates = extract_by_regex(title, clean)
    
    # 合并去重（jieba优先）
    seen = set()
    merged = []
    
    for c in jieba_candidates:
        if c['name'] not in seen:
            seen.add(c['name'])
            merged.append(c)
    
    for c in regex_candidates:
        if c['name'] not in seen:
            seen.add(c['name'])
            merged.append(c)
    
    return merged[:max_candidates]


# ===================== 独立测试 =====================
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        test_title = sys.argv[1]
        test_content = sys.argv[2] if len(sys.argv) > 2 else ""
    else:
        # 默认测试样例
        test_title = "华为 MateBook 14 2026 及 MateBook Pro 通过开源鸿蒙评测认证预装 6.0"
        test_content = "华为发布了新款MateBook系列笔记本，搭载自研麒麟芯片，支持AI计算。同时小米也推出了小米17 Ultra手机。"
    
    print(f"标题: {test_title}")
    print(f"内容: {test_content}")
    print(f"\n候选实体:")
    
    results = fast_ner(test_title, test_content)
    for i, r in enumerate(results, 1):
        src = r.get('source', '?')
        pat = r.get('pattern', '') or r.get('pos', '')
        print(f"  [{i}] {r['name']:30s} | {src:6s} | {pat}")
