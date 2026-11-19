#!/usr/bin/env python3
"""
每日市场地图 - 自动更新脚本 (完整版 v3)

数据流：
  华尔街见闻API抓取 → 原始快讯 → 三层漏斗筛选 → LLM结构化/规则兜底 → 中英双语JSON → 网站自动展示

数据源（按优先级）：
  1. 华尔街见闻 API            (中文, 主数据源, ~100条/次)
     域名: api-one-wscn.awtmt.com (2026年迁移，旧域名 api.wallstreetcn.com 已失效)
  2. CNBC Top News RSS        (英文, 备用)
  3. CNBC World News RSS       (英文, 备用)
  4. CNBC Economy RSS          (英文, 备用)
  5. MarketWatch Top Stories   (英文, 备用)
  6. Investing.com News RSS    (英文, 备用)
  7. 华尔街见闻 RSS            (中文, 备用)
  8. 华尔街见闻 页面           (中文, 备用)

使用方法：
  python3 update_daily.py                        # 抓取今天的数据
  python3 update_daily.py --date 2026-11-19      # 指定日期
  python3 update_daily.py --dry-run              # 只抓取不保存（测试用）
  python3 update_daily.py --source api           # 只用华尔街见闻API
  python3 update_daily.py --source rss           # 只用RSS源

环境变量：
  LLM_API_KEY    - LLM API 密钥（用于结构化，可选，无则用规则筛选）
  LLM_API_BASE   - LLM API 地址（默认使用公开API）
  LLM_MODEL      - LLM 模型名称（默认 gpt-4o）
"""

import json
import os
import sys
import re
import time
import argparse
import hashlib
import requests
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ============================================================
# 数据源配置
# ============================================================

# 华尔街见闻 API（主数据源 — 2026年域名迁移至 awtmt.com）
# 旧域名 api.wallstreetcn.com 已返回403，新域名 api-one-wscn.awtmt.com 正常
WSCN_API = "https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit=200"
WSCN_RSS = "https://wallstreetcn.com/rss"          # 保留尝试（可能404）
WSCN_PAGE = "https://wallstreetcn.com/live/global"  # SPA页面（保留尝试）

# 备用 RSS 数据源（当华尔街见闻不可用时使用）
RSS_SOURCES = [
    {
        "name": "CNBC Top News",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "lang": "en",
        "weight": 3,
    },
    {
        "name": "CNBC World News",
        "url": "https://www.cnbc.com/id/100727362/device/rss/rss.html",
        "lang": "en",
        "weight": 2,
    },
    {
        "name": "CNBC Economy",
        "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
        "lang": "en",
        "weight": 2,
    },
    {
        "name": "MarketWatch Top Stories",
        "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "lang": "en",
        "weight": 2,
    },
    {
        "name": "Investing.com News",
        "url": "https://www.investing.com/rss/news_1.rss",
        "lang": "en",
        "weight": 1,
    },
]

# ============================================================
# 关键词配置（中英双语）
# ============================================================

# 市场关键词（用于第一层漏斗过滤）— 中文
MARKET_KEYWORDS_ZH = [
    # 价格变动
    "涨", "跌", "涨超", "跌超", "大涨", "大跌", "飙升", "暴跌", "新高", "新低",
    "涨幅", "跌幅", "上涨", "下跌", "收涨", "收跌", "累涨", "累跌",
    # 资产类别
    "美股", "A股", "港股", "日股", "欧股", "纳指", "标普", "道指", "创业板", "科创",
    "美元", "日元", "欧元", "英镑", "人民币", "汇率",
    "美债", "国债", "收益率", "十年期", "两年期",
    "原油", "布油", "黄金", "白银", "铜", "铁矿石",
    "比特币", "以太坊", "加密",
    # 宏观
    "美联储", "加息", "降息", "缩表", "QE", "利率", "PPI", "CPI", "PMI",
    "非农", "就业", "通胀", "GDP", "赤字", "财政",
    "央行", "日本央行", "欧央行", "人民银行",
    # 行业/公司
    "英伟达", "苹果", "特斯拉", "微软", "谷歌", "亚马逊", "Meta",
    "半导体", "芯片", "AI", "人工智能", "数据中心",
    "SpaceX", "OpenAI", "生物科技", "创新药",
    # 中国
    "社零", "工业增加值", "地产", "房地产", "基建", "出口", "进口",
    "统计局", "国务院", "证监会",
]

# 市场关键词 — 英文
MARKET_KEYWORDS_EN = [
    # Price action
    "surge", "soar", "rally", "jump", "rise", "gain", "climb", "rally",
    "plunge", "slump", "tumble", "drop", "fall", "decline", "sink", "slide",
    "surge", "spike", "dive", "crash", "correction", "selloff",
    "record high", "record low", "new high", "new low", "all-time high",
    # Asset classes
    "stock", "stocks", "equity", "equities", "share", "shares",
    "Nasdaq", "S&P", "Dow", "Russell", "NYSE",
    "dollar", "yen", "euro", "pound", "sterling", "yuan", "currency", "currencies", "FX",
    "Treasury", "Treasuries", "yield", "bond", "bonds", "10-year", "2-year",
    "oil", "crude", "Brent", "WTI", "gold", "silver", "copper",
    "Bitcoin", "Ethereum", "crypto", "cryptocurrency",
    "A-shares", "HK stocks", "Hang Seng",
    # Macro
    "Fed", "Federal Reserve", "rate hike", "rate cut", "interest rate",
    "PPI", "CPI", "PMI", "nonfarm", "payrolls", "jobs report",
    "inflation", "GDP", "deficit", "fiscal", "treasury",
    "central bank", "Bank of Japan", "BOJ", "ECB", "PBOC",
    " Powell", "Warsh", "Yellen",
    # Industry / Companies
    "Nvidia", "Apple", "Tesla", "Microsoft", "Google", "Alphabet",
    "Amazon", "Meta", "Facebook",
    "semiconductor", "chip", "chips", "AI", "artificial intelligence",
    "data center", "SpaceX", "OpenAI", "Anthropic",
    "biotech", "pharma", "drug",
    # Energy
    "OPEC", "OPEC+", "energy", "oil price",
    # Market terms
    "earnings", "revenue", "guidance", "IPO", "SPAC",
    "merger", "acquisition", "M&A",
    "bullish", "bearish", "volatility", "VIX",
    "safe haven", "risk-off", "risk-on", "flight to safety",
    "recession", "soft landing", "hard landing",
    "valuation", "bubble", "correction",
]

# 合并关键词列表（兼容旧代码）
MARKET_KEYWORDS = MARKET_KEYWORDS_ZH + MARKET_KEYWORDS_EN

# 噪声关键词（过滤掉无关内容）— 中英双语
NOISE_KEYWORDS = [
    "广告", "推广", "赞助", "活动", "报名", "直播预约",
    "课程", "会员", "订阅", "下载APP",
    # 英文噪声
    "subscribe", "newsletter", "sign up", "download app",
    "advertisement", "sponsored", "promoted",
]

# 突发/高重要性关键词 — 命中这些的不受条数限制
BREAKING_KEYWORDS_ZH = [
    "紧急", "突发", "重磅", "暴跌", "飙升", "熔断", "崩盘",
    "加息", "降息", "非农", "CPI", "PPI", "GDP",
    "美联储", "主席", "声明", "决议",
]
BREAKING_KEYWORDS_EN = [
    "breaking", "urgent", "just in", "alert",
    "crash", "plunge", "surge", "spike", "circuit breaker",
    "rate hike", "rate cut", "nonfarm", "payrolls",
    "Fed Chair", "Powell says", "Warsh says",
    "emergency", "crisis", "historic",
]

# ============================================================
# 中英双语翻译辅助
# ============================================================

# 常见金融术语中英对照表（用于规则兜底方案的自动翻译）
FINANCIAL_GLOSSARY = {
    # 宏观
    "美联储": "the Fed", "加息": "rate hike", "降息": "rate cut",
    "通胀": "inflation", "通胀扩散": "broadening inflation",
    "收益率": "yield", "美债": "US Treasuries", "国债": "government bonds",
    "美元指数": "Dollar Index", "日元": "JPY", "人民币": "CNY",
    "工业增加值": "industrial output", "社零": "retail sales",
    "固定资产投资": "fixed asset investment", "地产投资": "property investment",
    "财政赤字": "fiscal deficit", "PPI": "PPI", "CPI": "CPI",
    # 资产
    "英伟达": "Nvidia", "特斯拉": "Tesla", "苹果": "Apple",
    "微软": "Microsoft", "亚马逊": "Amazon", "谷歌": "Google",
    "半导体": "semiconductors", "芯片": "chips",
    "原油": "crude oil", "布油": "Brent crude", "黄金": "gold",
    "比特币": "Bitcoin", "创业板": "ChiNext", "港股": "HK stocks",
    "A股": "A-shares", "纳指": "Nasdaq", "标普": "S&P",
    # 方向
    "新高": "new high", "新低": "new low",
    "飙升": "surge", "暴跌": "plunge", "大涨": "rally", "大跌": "selloff",
    # 其他
    "SpaceX": "SpaceX", "OpenAI": "OpenAI", "生物科技": "biotech",
    "创新药": "innovative drugs", "防御切换": "defensive rotation",
    "估值重估": "re-rating", "估值泡沫": "valuation bubble",
    "风险偏好": "risk appetite", "流动性": "liquidity",
    "实际利率": "real interest rate", "供应过剩": "supply surplus",
}


def translate_text(text):
    """
    基础规则翻译：用术语词典做简单替换。
    仅用于规则兜底方案，质量不如 LLM 翻译。
    """
    if not text:
        return ""
    result = text
    # 按词长度降序替换，避免短词覆盖长词
    sorted_terms = sorted(FINANCIAL_GLOSSARY.items(), key=lambda x: len(x[0]), reverse=True)
    for zh, en in sorted_terms:
        result = result.replace(zh, en)
    return result


def log(msg):
    """带时间戳的日志输出"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


# ============================================================
# 第一层：数据抓取
# ============================================================

def fetch_via_rss_source(source):
    """通过 RSS 抓取单个数据源"""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    try:
        log(f"[RSS] 正在请求: {source['name']} ({source['url']})")
        resp = requests.get(source["url"], headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")
        log(f"[RSS] {source['name']}: 获取 {len(items)} 条")
        headlines = []
        for item in items:
            title = item.find("title")
            desc = item.find("description")
            pub = item.find("pubDate")
            link = item.find("link")

            # 合并标题和描述
            text = ""
            if title:
                text += title.get_text(strip=True)
            if desc:
                desc_text = desc.get_text(strip=True)
                if desc_text and desc_text != text:
                    # 清理HTML标签
                    if "<" in desc_text:
                        desc_text = BeautifulSoup(desc_text, "html.parser").get_text(strip=True)
                    text += " | " + desc_text[:200]

            # 解析时间
            time_str = ""
            timestamp = 0
            if pub:
                time_str = pub.get_text(strip=True)
                try:
                    dt = parsedate_to_datetime(time_str)
                    timestamp = int(dt.timestamp())
                    time_str = dt.strftime("%H:%M")
                except Exception:
                    pass

            if text and len(text) > 5:
                headlines.append({
                    "text": text.strip(),
                    "time": time_str,
                    "timestamp": timestamp,
                    "source": source["name"],
                    "lang": source["lang"],
                    "weight": source.get("weight", 1),
                })
        return headlines
    except Exception as e:
        log(f"[RSS] {source['name']} 抓取失败: {e}")
        return []


def fetch_all_rss():
    """抓取所有 RSS 数据源"""
    all_headlines = []
    for source in RSS_SOURCES:
        headlines = fetch_via_rss_source(source)
        all_headlines.extend(headlines)
        time.sleep(0.5)  # 礼貌等待
    log(f"[RSS] 所有源合计: {len(all_headlines)} 条快讯")
    return all_headlines


def fetch_via_api():
    """通过华尔街见闻 API 抓取快讯（主数据源，2026年迁移至 api-one-wscn.awtmt.com）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://wallstreetcn.com",
        "Referer": "https://wallstreetcn.com/live/global",
    }
    try:
        log(f"[API] 正在请求华尔街见闻 API: {WSCN_API}")
        resp = requests.get(WSCN_API, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        log(f"[API] 华尔街见闻: 获取 {len(items)} 条快讯")
        headlines = []
        for item in items:
            text = item.get("content_text", "") or item.get("content", "")
            if "<" in text:
                text = BeautifulSoup(text, "html.parser").get_text(strip=True)
            # 华尔街见闻使用 display_time 字段（Unix时间戳）
            create_time = item.get("display_time", 0) or item.get("created_at", 0)
            if create_time:
                dt = datetime.fromtimestamp(create_time)
            else:
                dt = datetime.now()
            headlines.append({
                "text": text.strip(),
                "time": dt.strftime("%H:%M"),
                "timestamp": create_time,
                "source": "华尔街见闻",
                "lang": "zh",
                "weight": 3,
            })
        return headlines
    except Exception as e:
        log(f"[API] 华尔街见闻API抓取失败: {e}")
        return []


def fetch_via_wscn_rss():
    """通过华尔街见闻 RSS 抓取（可能404，保留尝试）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    }
    try:
        log(f"[RSS] 正在请求华尔街见闻 RSS: {WSCN_RSS}")
        resp = requests.get(WSCN_RSS, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")
        log(f"[RSS] 华尔街见闻: 获取 {len(items)} 条快讯")
        headlines = []
        for item in items:
            title = item.find("title")
            desc = item.find("description")
            pub = item.find("pubDate")
            text = ""
            if title:
                text += title.get_text(strip=True)
            if desc:
                text += " " + BeautifulSoup(desc.get_text(), "html.parser").get_text(strip=True)
            time_str = ""
            if pub:
                time_str = pub.get_text(strip=True)
            headlines.append({
                "text": text.strip(),
                "time": time_str,
                "timestamp": 0,
                "source": "华尔街见闻RSS",
                "lang": "zh",
                "weight": 3,
            })
        return headlines
    except Exception as e:
        log(f"[RSS] 华尔街见闻RSS抓取失败: {e}")
        return []


def fetch_via_page():
    """通过直接抓取华尔街见闻网页获取快讯（SPA，可能无数据，保留尝试）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://wallstreetcn.com/",
    }
    try:
        log(f"[PAGE] 正在请求华尔街见闻页面: {WSCN_PAGE}")
        resp = requests.get(WSCN_PAGE, headers=headers, timeout=15)
        resp.raise_for_status()

        text = resp.text
        headlines = []

        # 方案1：找 __INITIAL_STATE__ 或类似变量
        patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});',
            r'window\.__NUXT__\s*=\s*(\{.*?\});',
            r'"content_text"\s*:\s*"([^"]+)"',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            if matches:
                log(f"[PAGE] 通过正则匹配到 {len(matches)} 条内容")
                for m in matches[:200]:
                    if len(m) > 10 and not m.startswith("{"):
                        clean = BeautifulSoup(m, "html.parser").get_text(strip=True)
                        if clean:
                            headlines.append({
                                "text": clean,
                                "time": "",
                                "timestamp": 0,
                                "source": "华尔街见闻页面",
                                "lang": "zh",
                                "weight": 3,
                            })
                if headlines:
                    break

        # 方案2：用 BeautifulSoup 找快讯元素
        if not headlines:
            soup = BeautifulSoup(text, "html.parser")
            selectors = [
                ".live-item", ".news-item", ".timeline-item",
                "[data-type='live']", ".wscn-live-item",
                ".live-content", ".content-text",
            ]
            for sel in selectors:
                items = soup.select(sel)
                if items:
                    log(f"[PAGE] 通过选择器 {sel} 找到 {len(items)} 条")
                    for item in items:
                        t = item.get_text(strip=True)
                        if t and len(t) > 10:
                            headlines.append({
                                "text": t, "time": "", "timestamp": 0,
                                "source": "华尔街见闻页面", "lang": "zh", "weight": 3,
                            })
                    break

        log(f"[PAGE] 华尔街见闻共提取 {len(headlines)} 条快讯")
        return headlines
    except Exception as e:
        log(f"[PAGE] 华尔街见闻页面抓取失败: {e}")
        return []


def fetch_headlines(source="auto"):
    """
    抓取快讯（多源聚合）
    主数据源：华尔街见闻 API（中文快讯，最新最全）
    备用数据源：国际RSS（当华尔街见闻不可用时使用）
    """
    if source == "api":
        return fetch_via_api()
    elif source == "rss":
        return fetch_all_rss()
    elif source == "page":
        return fetch_via_page()
    elif source == "cnbc":
        cnbc_sources = [s for s in RSS_SOURCES if "CNBC" in s["name"]]
        all_h = []
        for s in cnbc_sources:
            all_h.extend(fetch_via_rss_source(s))
        return all_h
    else:
        # auto: 优先华尔街见闻（主数据源），失败则用国际RSS备用
        all_headlines = []

        # 1. 华尔街见闻 API（主数据源）
        wscn_headlines = fetch_via_api()
        if wscn_headlines:
            all_headlines.extend(wscn_headlines)
            log(f"✅ 华尔街见闻: {len(wscn_headlines)} 条（主数据源）")

        # 2. 如果华尔街见闻不可用或数据不足，补充国际RSS
        if not wscn_headlines or len(wscn_headlines) < 20:
            log("华尔街见闻数据不足，补充国际RSS源...")
            rss_headlines = fetch_all_rss()
            all_headlines.extend(rss_headlines)

        # 3. 尝试华尔街见闻 RSS 和页面作为额外补充（可选）
        if len(all_headlines) < 30:
            for fetch_fn in [fetch_via_wscn_rss, fetch_via_page]:
                extra = fetch_fn()
                if extra:
                    all_headlines.extend(extra)
                    break
                time.sleep(1)

        if not all_headlines:
            log("❌ 所有抓取方式均失败")
        else:
            # 多源去重（不同源可能有相同新闻）
            seen_texts = set()
            deduped = []
            for h in all_headlines:
                text_hash = hashlib.md5(h["text"][:80].lower().encode()).hexdigest()
                if text_hash not in seen_texts:
                    seen_texts.add(text_hash)
                    deduped.append(h)
            log(f"多源聚合去重: {len(all_headlines)} → {len(deduped)} 条")
            all_headlines = deduped

        return all_headlines


# ============================================================
# 第二层：三层漏斗筛选（动态阈值，无硬编码上限）
# ============================================================

def funnel_filter(headlines):
    """
    三层漏斗筛选（v2: 动态阈值，重要新闻不受条数限制）
    第一层：与价格变动/新信息/宏观/资产相关的条目（中英关键词）
    第二层：去重去噪
    第三层：按重要性打分排序，保留所有高分条目（不再固定40条上限）
            突发重要新闻不受上限限制
    """
    # === 第一层：关键词过滤 ===
    filtered = []
    for h in headlines:
        text = h["text"]
        text_lower = text.lower()
        # 跳过噪声内容
        if any(kw in text_lower for kw in [n.lower() for n in NOISE_KEYWORDS]):
            continue
        # 必须包含至少一个市场关键词（中英都检查）
        if any(kw in text for kw in MARKET_KEYWORDS_ZH) or \
           any(kw in text_lower for kw in MARKET_KEYWORDS_EN):
            filtered.append(h)

    log(f"第一层过滤: {len(headlines)} → {len(filtered)} 条")

    # === 第二层：去重去噪 ===
    seen_hashes = set()
    deduped = []
    for h in filtered:
        # 用文本前100字符的hash做去重
        text_hash = hashlib.md5(h["text"][:100].encode()).hexdigest()
        if text_hash not in seen_hashes:
            seen_hashes.add(text_hash)
            deduped.append(h)

    log(f"第二层去重: {len(filtered)} → {len(deduped)} 条")

    # === 第三层：按重要性打分排序（动态保留） ===
    def importance_score(h):
        """打分：含具体数字、涨跌幅、多关键词、突发新闻的条目得分更高"""
        text = h["text"]
        text_lower = text.lower()
        score = 0

        # 含具体数字 +5
        if re.search(r'\d+\.?\d*%?', text):
            score += 5

        # 含涨跌关键词 +3（中文）
        price_words_zh = sum(1 for kw in ["涨", "跌", "新高", "新低", "飙升", "暴跌"] if kw in text)
        score += price_words_zh * 3

        # 含涨跌关键词 +3（英文）
        price_words_en = sum(1 for kw in [
            "surge", "soar", "rally", "jump", "plunge", "slump",
            "tumble", "drop", "fall", "crash", "spike", "dive",
            "record high", "record low", "new high", "new low",
            "surge", "selloff", "correction"
        ] if kw in text_lower)
        score += price_words_en * 3

        # 含多个市场关键词 +2 each
        market_count = sum(1 for kw in MARKET_KEYWORDS_ZH if kw in text)
        market_count += sum(1 for kw in MARKET_KEYWORDS_EN if kw in text_lower)
        score += market_count * 2

        # 突发/高重要性关键词 +10
        breaking_zh = sum(1 for kw in BREAKING_KEYWORDS_ZH if kw in text)
        breaking_en = sum(1 for kw in BREAKING_KEYWORDS_EN if kw in text_lower)
        score += (breaking_zh + breaking_en) * 10

        # 长文本可能信息更丰富
        if len(text) > 50:
            score += 3
        if len(text) > 100:
            score += 2
        if len(text) > 200:
            score += 1  # 超长文本边际递减

        # 数据源权重加成
        score += h.get("weight", 1)

        return score

    scored = [(h, importance_score(h)) for h in deduped]
    scored.sort(key=lambda x: x[1], reverse=True)

    # 动态保留：保留所有得分 >= 阈值的条目，不再固定上限
    # 阈值 = 平均得分的 60%
    if scored:
        avg_score = sum(s for _, s in scored) / len(scored)
        threshold = avg_score * 0.6
        top_headlines = [h for h, s in scored if s >= threshold]
        # 至少保留15条（如果有的话），最多80条（防止LLM token爆炸）
        if len(top_headlines) < 15 and len(scored) >= 15:
            top_headlines = [h for h, s in scored[:15]]
        elif len(top_headlines) > 80:
            top_headlines = [h for h, s in scored[:80]]
    else:
        top_headlines = []

    log(f"第三层排序: 保留 {len(top_headlines)} 条高分快讯 (动态阈值)")

    return top_headlines


# ============================================================
# 第三层：LLM 结构化（双语输出，需要 API key）
# ============================================================

LLM_PROMPT = """You are a professional financial market analyst. Extract information from the following flash news headlines and generate a daily market map in BOTH Chinese and English.

Flash news headlines (from multiple sources, may be in English or Chinese):
{headlines}

Output strictly in the following JSON format (output JSON only, no other text):
{{
  "stats": [
    {{
      "label": "资产名称（含时间范围，中文）",
      "label_en": "Asset name (with time range, English)",
      "value": "变动数值",
      "change": "一句话说明（中文）",
      "change_en": "One-sentence description (English)",
      "dir": "up or down"
    }}
  ],
  "events": [
    {{
      "tags": [{{"type": "ai/fed/energy/china/bio/macro", "text": "标签（中文）", "text_en": "Tag (English)"}}],
      "event": "事件描述（中文，一句话说清楚发生了什么）",
      "event_en": "Event description (English, one clear sentence)",
      "assets": "影响的资产（中文，逗号分隔）",
      "assets_en": "Affected assets (English, comma-separated)",
      "dir": "up/down/neutral/split",
      "logic": "传导逻辑（中文，A→B→C 格式）",
      "logic_en": "Transmission logic (English, A→B→C format)"
    }}
  ],
  "chains": [
    {{
      "title": "因果链标题（中文，① 编号 + 简述）",
      "title_en": "Causal chain title (English, numbered)",
      "status": "consensus or unverified",
      "nodes": [
        {{"text": "节点描述（中文）<br>第二行", "text_en": "Node description (English)<br>line 2", "type": "trigger/normal/result-up/result-down"}}
      ],
      "jargon": [
        {{
          "term": "术语名称（中文）",
          "term_en": "Term (English)",
          "explain": "白话解释（中文）",
          "explain_en": "Plain-language explanation (English)"
        }}
      ]
    }}
  ],
  "verifications": [
    {{
      "title": "待验证问题（中文）",
      "title_en": "Question to verify (English)",
      "vars": ["需盯变量1（中文）", "需盯变量2（中文）", "需盯变量3（中文）", "需盯变量4（中文）"],
      "vars_en": ["Variable to watch 1 (English)", "Variable to watch 2 (English)", "Variable to watch 3 (English)", "Variable to watch 4 (English)"],
      "analogy_title": "历史类比标题（中文）",
      "analogy_title_en": "Historical analogy title (English)",
      "analogy_text": "历史类比描述（中文）",
      "analogy_text_en": "Historical analogy description (English)",
      "lesson": "教训（中文）",
      "lesson_en": "Lesson (English)",
      "diff": "关键区别（中文）",
      "diff_en": "Key difference (English)"
    }}
  ],
  "four_column_table": [
    {{
      "tags": [{{"type": "ai/fed/energy/china/bio/macro/geopolitics", "text": "标签（中文）", "text_en": "Tag (English)"}}],
      "event": "事件描述（中文，简洁完整）",
      "event_en": "Event description (English)",
      "assets": "影响资产（中文，逗号分隔）",
      "assets_en": "Affected assets (English)",
      "dir": "up/down/neutral/split",
      "logic": "传导逻辑（中文，A→B→C格式）",
      "logic_en": "Transmission logic (English, A→B→C)"
    }}
  ],
  "historical_analogies": [
    {{
      "event": "历史类比标题（中文）",
      "event_en": "Analogy title (English)",
      "lesson": "历史事件+教训（中文）",
      "lesson_en": "Historical event + lesson (English)",
      "diff": "关键区别（中文）",
      "diff_en": "Key difference (English)"
    }}
  ]
}}

Requirements:
1. stats: extract ALL important market data points (no fixed limit)
2. events: include ALL significant market events — no fixed cap
3. four_column_table: generate the 4-column table data (Event / Affected Assets / Direction / Logic) for the 6-10 most important events after funnel filtering
4. chains: extract causal chains for every significant market narrative (3-7 chains, based on actual importance)
5. verifications: generate watchlist items with TWO layers — layer1 = core question, vars = 3-4 specific variables to watch
6. historical_analogies: generate 3-4 real historical parallels with lesson and key difference
7. Use <br> for line breaks in node text
8. CRITICAL: Every *_en field MUST be in pure English with NO Chinese characters whatsoever
9. CRITICAL: Every Chinese field MUST have a corresponding *_en English field
10. English must use proper financial terminology
11. Output strictly valid JSON"""


def llm_structure(headlines):
    """用 LLM 对筛选后的快讯进行中英双语结构化"""
    api_key = os.environ.get("LLM_API_KEY", "")
    api_base = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")

    # 格式化快讯列表
    headline_text = "\n".join(
        f"[{i+1}] ({h.get('time','')}) [{h.get('source','')}] {h['text']}"
        for i, h in enumerate(headlines)
    )

    prompt = LLM_PROMPT.format(headlines=headline_text)

    if not api_key:
        log("[LLM] 未设置 LLM_API_KEY，跳过 LLM 结构化")
        return None

    try:
        log(f"[LLM] 正在请求 LLM 结构化 ({len(headlines)} 条快讯)...")
        resp = requests.post(
            f"{api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.environ.get("LLM_MODEL", "gpt-4o"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            },
            timeout=120,
        )
        resp.raise_for_status()
        result = resp.json()
        content = result["choices"][0]["message"]["content"]
        structured = json.loads(content)
        log(f"[LLM] 结构化完成: {len(structured.get('events',[]))} 条事件, {len(structured.get('chains',[]))} 条因果链")

        # 验证双语完整性
        issues = validate_bilingual(structured)
        if issues:
            log(f"[LLM] ⚠️ 双语校验发现 {len(issues)} 个问题:")
            for issue in issues[:5]:
                log(f"  - {issue}")
            # 尝试修复缺失的英文字段
            structured = auto_fill_english(structured)
            log("[LLM] 已自动补充缺失的英文字段")

        return structured
    except Exception as e:
        log(f"[LLM] 请求失败: {e}")
        return None


def validate_bilingual(data):
    """
    校验数据中每个中文字段是否有对应的英文字段。
    返回问题列表（空列表表示无问题）。
    """
    issues = []
    chinese_re = re.compile(r'[\u4e00-\u9fff]')

    # 需要成对出现的字段
    field_pairs = [
        ("label", "label_en"), ("change", "change_en"),
        ("event", "event_en"), ("assets", "assets_en"), ("logic", "logic_en"),
        ("title", "title_en"),
        ("term", "term_en"), ("explain", "explain_en"),
        ("text", "text_en"),
        ("analogy_title", "analogy_title_en"), ("analogy_text", "analogy_text_en"),
        ("lesson", "lesson_en"), ("diff", "diff_en"),
    ]

    def check_item(item, context):
        for zh_field, en_field in field_pairs:
            if zh_field in item:
                # 检查英文字段是否存在
                if en_field not in item or not item[en_field]:
                    issues.append(f"{context}: 缺少 {en_field}")
                # 检查英文字段中是否有中文字符
                elif en_field in item and item[en_field] and chinese_re.search(item[en_field]):
                    issues.append(f"{context}: {en_field} 中包含中文字符")

    # 检查 stats
    for i, s in enumerate(data.get("stats", [])):
        check_item(s, f"stats[{i}]")

    # 检查 events
    for i, e in enumerate(data.get("events", [])):
        check_item(e, f"events[{i}]")
        # 检查 tags
        for j, tag in enumerate(e.get("tags", [])):
            if "text" in tag and ("text_en" not in tag or not tag["text_en"]):
                issues.append(f"events[{i}].tags[{j}]: 缺少 text_en")

    # 检查 chains
    for i, c in enumerate(data.get("chains", [])):
        check_item(c, f"chains[{i}]")
        for j, node in enumerate(c.get("nodes", [])):
            check_item(node, f"chains[{i}].nodes[{j}]")
        for j, jargon in enumerate(c.get("jargon", [])):
            check_item(jargon, f"chains[{i}].jargon[{j}]")

    # 检查 verifications
    for i, v in enumerate(data.get("verifications", [])):
        check_item(v, f"verifications[{i}]")
        # 检查 vars_en
        if "vars" in v and ("vars_en" not in v or len(v.get("vars_en", [])) != len(v["vars"])):
            issues.append(f"verifications[{i}]: vars_en 缺失或数量不匹配")

    return issues


def auto_fill_english(data):
    """
    自动补充缺失的英文字段（使用规则翻译）。
    质量不如 LLM 翻译，但保证不会缺失。
    """
    chinese_re = re.compile(r'[\u4e00-\u9fff]')
    field_pairs = [
        ("label", "label_en"), ("change", "change_en"),
        ("event", "event_en"), ("assets", "assets_en"), ("logic", "logic_en"),
        ("title", "title_en"),
        ("term", "term_en"), ("explain", "explain_en"),
        ("text", "text_en"),
        ("analogy_title", "analogy_title_en"), ("analogy_text", "analogy_text_en"),
        ("lesson", "lesson_en"), ("diff", "diff_en"),
    ]

    def fill_item(item):
        for zh_field, en_field in field_pairs:
            if zh_field in item:
                if en_field not in item or not item[en_field]:
                    # 用规则翻译补充
                    item[en_field] = translate_text(item[zh_field])
                elif chinese_re.search(item[en_field]):
                    # 英文字段中有中文，用规则翻译覆盖
                    item[en_field] = translate_text(item[en_field])

    for s in data.get("stats", []):
        fill_item(s)

    for e in data.get("events", []):
        fill_item(e)
        for tag in e.get("tags", []):
            if "text" in tag and ("text_en" not in tag or not tag["text_en"]):
                tag["text_en"] = translate_text(tag["text"])

    for c in data.get("chains", []):
        fill_item(c)
        for node in c.get("nodes", []):
            fill_item(node)
        for jargon in c.get("jargon", []):
            fill_item(jargon)

    for v in data.get("verifications", []):
        fill_item(v)
        if "vars" in v:
            if "vars_en" not in v or len(v.get("vars_en", [])) != len(v["vars"]):
                v["vars_en"] = [translate_text(var) for var in v["vars"]]

    return data


def extract_assets_from_text(text):
    """从快讯文本中提取影响资产"""
    assets = []
    text_lower = text.lower()

    # 中文资产
    asset_map_zh = {
        "沪指": "A股/沪指", "深成指": "A股/深成指", "创业板": "创业板",
        "科创50": "科创50", "恒生科技": "港股/恒生科技", "港股": "港股",
        "纳指": "纳指", "标普": "标普500", "道指": "道指",
        "美元": "美元指数", "日元": "日元", "人民币": "人民币",
        "美债": "美债", "十年期": "10年期美债",
        "原油": "原油", "布油": "布伦特原油", "黄金": "黄金", "白银": "白银",
        "铜": "铜", "铁矿石": "铁矿石",
        "比特币": "比特币",
        "英伟达": "英伟达", "苹果": "苹果", "特斯拉": "特斯拉",
        "阿里巴巴": "阿里巴巴", "阿里": "阿里巴巴",
        "半导体": "半导体板块", "芯片": "芯片板块", "光刻机": "光刻机板块",
    }
    for kw, asset in asset_map_zh.items():
        if kw in text and asset not in assets:
            assets.append(asset)

    # 英文资产
    asset_map_en = {
        "nasdaq": "Nasdaq", "s&p": "S&P 500", "dow": "Dow Jones",
        "oil": "Crude Oil", "crude": "Crude Oil", "brent": "Brent Oil",
        "gold": "Gold", "silver": "Silver", "copper": "Copper",
        "dollar": "USD Index", "treasury": "US Treasuries", "yield": "Bond Yields",
        "bitcoin": "Bitcoin", "nvidia": "Nvidia", "apple": "Apple",
        "tesla": "Tesla", "fed": "Fed Policy",
    }
    for kw, asset in asset_map_en.items():
        if kw in text_lower and asset not in assets:
            assets.append(asset)

    if not assets:
        assets.append("详见原文")
    return " / ".join(assets[:5])


def extract_logic_from_text(text, dir):
    """从快讯文本中生成简化传导逻辑"""
    text_lower = text.lower()

    # 按事件类型生成逻辑
    if any(kw in text for kw in ["加息", "鹰派"]) or "rate hike" in text_lower or "hawkish" in text_lower:
        return "央行鹰派信号 → 加息预期升温 → 美元走强/利率上行 → 风险资产承压"
    if any(kw in text for kw in ["降息", "鸽派"]) or "rate cut" in text_lower or "dovish" in text_lower:
        return "央行鸽派信号 → 降息预期升温 → 流动性预期改善 → 风险资产受益"
    if any(kw in text for kw in ["地缘", "战争", "冲突", "制裁"]) or "geopolitical" in text_lower or "sanction" in text_lower:
        return "地缘风险事件 → 避险情绪升温 → 避险资产上涨/风险资产下跌"
    if any(kw in text for kw in ["财报", "营收", "利润", "EPS"]) or "earnings" in text_lower or "revenue" in text_lower:
        if "超预期" in text or "beat" in text_lower:
            return "财报超预期 → 盈利预期上修 → 股价上涨"
        elif "不及预期" in text or "miss" in text_lower:
            return "财报不及预期 → 盈利预期下修 → 股价下跌"
        return "财报发布 → 盈利/指引更新 → 估值重估"
    if any(kw in text for kw in ["AI", "芯片", "算力"]) or "artificial intelligence" in text_lower:
        return "AI产业事件 → 算力/芯片需求预期变化 → 相关板块联动"
    if any(kw in text for kw in ["原油", "油价", "OPEC"]) or "oil" in text_lower or "opec" in text_lower:
        return "原油供给/需求变化 → 油价波动 → 能源股/通胀预期联动"
    if any(kw in text for kw in ["出口", "进口", "贸易"]) or "trade" in text_lower or "export" in text_lower:
        return "贸易数据变化 → 全球需求/供应链预期调整 → 相关货币/股市影响"
    if "ipo" in text_lower:
        return "IPO事件 → 市场资金流向/行业估值锚定 → 相关板块联动"

    # 默认逻辑
    if dir == "up":
        return "利好事件 → 市场预期改善 → 资产价格上涨"
    elif dir == "down":
        return "利空事件 → 市场预期恶化 → 资产价格下跌"
    elif dir == "split":
        return "多空因素交织 → 板块/资产分化 → 需关注后续催化"
    return "事件发生 → 市场消化信息 → 资产价格调整"


def extract_assets_en(assets_zh):
    """翻译资产名称为英文"""
    mapping = {
        "A股": "A-shares", "沪指": "Shanghai Composite", "深成指": "Shenzhen Component",
        "创业板": "ChiNext", "科创50": "STAR 50", "港股": "HK Stocks",
        "恒生科技": "Hang Seng Tech", "纳指": "Nasdaq", "标普500": "S&P 500",
        "道指": "Dow Jones", "美元指数": "USD Index", "日元": "JPY",
        "人民币": "CNY", "美债": "US Treasuries", "10年期美债": "10Y Treasury",
        "原油": "Crude Oil", "布伦特原油": "Brent", "黄金": "Gold",
        "白银": "Silver", "铜": "Copper", "铁矿石": "Iron Ore",
        "比特币": "Bitcoin", "英伟达": "Nvidia", "苹果": "Apple",
        "特斯拉": "Tesla", "阿里巴巴": "Alibaba", "半导体板块": "Semiconductors",
        "芯片板块": "Chips", "光刻机板块": "Lithography",
        "Nasdaq": "Nasdaq", "S&P 500": "S&P 500", "Dow Jones": "Dow Jones",
        "Crude Oil": "Crude Oil", "Brent Oil": "Brent", "Gold": "Gold",
        "Silver": "Silver", "Copper": "Copper", "USD Index": "USD Index",
        "US Treasuries": "US Treasuries", "Bond Yields": "Bond Yields",
        "Bitcoin": "Bitcoin", "Nvidia": "Nvidia", "Apple": "Apple",
        "Tesla": "Tesla", "Fed Policy": "Fed Policy",
        "详见原文": "See source",
    }
    parts = assets_zh.split(" / ")
    return " / ".join(mapping.get(p.strip(), p) for p in parts)


def extract_logic_en(logic_zh):
    """翻译传导逻辑为英文"""
    mapping = {
        "央行鹰派信号": "Central bank hawkish signal",
        "加息预期升温": "rate hike expectations rise",
        "美元走强/利率上行": "USD strengthens / yields rise",
        "风险资产承压": "risk assets under pressure",
        "央行鸽派信号": "Central bank dovish signal",
        "降息预期升温": "rate cut expectations rise",
        "流动性预期改善": "liquidity expectations improve",
        "风险资产受益": "risk assets benefit",
        "地缘风险事件": "Geopolitical risk event",
        "避险情绪升温": "safe-haven sentiment rises",
        "避险资产上涨/风险资产下跌": "safe-haven up / risk assets down",
        "财报超预期": "Earnings beat",
        "盈利预期上修": "earnings estimates revised up",
        "股价上涨": "stock price rises",
        "财报不及预期": "Earnings miss",
        "盈利预期下修": "earnings estimates revised down",
        "股价下跌": "stock price falls",
        "财报发布": "Earnings released",
        "盈利/指引更新": "earnings/guidance update",
        "估值重估": "re-rating",
        "AI产业事件": "AI industry event",
        "算力/芯片需求预期变化": "compute/chip demand expectations shift",
        "相关板块联动": "related sectors correlate",
        "原油供给/需求变化": "Oil supply/demand shift",
        "油价波动": "oil price volatility",
        "能源股/通胀预期联动": "energy stocks / inflation expectations correlate",
        "贸易数据变化": "Trade data shift",
        "全球需求/供应链预期调整": "global demand / supply chain expectations adjust",
        "相关货币/股市影响": "related currencies / stocks impacted",
        "IPO事件": "IPO event",
        "市场资金流向/行业估值锚定": "capital flows / sector valuation anchoring",
        "利好事件": "Positive event",
        "市场预期改善": "market expectations improve",
        "资产价格上涨": "asset prices rise",
        "利空事件": "Negative event",
        "市场预期恶化": "market expectations worsen",
        "资产价格下跌": "asset prices fall",
        "多空因素交织": "Mixed bullish/bearish factors",
        "板块/资产分化": "sector / asset divergence",
        "需关注后续催化": "watch for next catalyst",
        "事件发生": "Event occurs",
        "市场消化信息": "market digests info",
        "资产价格调整": "asset prices adjust",
    }
    result = logic_zh
    for zh, en in sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True):
        result = result.replace(zh, en)
    return result


def generate_four_column_table(events):
    """从事件列表生成四列表数据"""
    table = []
    for ev in events:
        table.append({
            "event": ev.get("event", ""),
            "event_en": ev.get("event_en", ev.get("event", "")),
            "assets": ev.get("assets", "") or extract_assets_from_text(ev.get("event", "")),
            "assets_en": ev.get("assets_en", "") or extract_assets_en(extract_assets_from_text(ev.get("event", ""))),
            "dir": ev.get("dir", "neutral"),
            "logic": ev.get("logic", "") or extract_logic_from_text(ev.get("event", ""), ev.get("dir", "neutral")),
            "logic_en": ev.get("logic_en", "") or extract_logic_en(extract_logic_from_text(ev.get("event", ""), ev.get("dir", "neutral"))),
            "tags": ev.get("tags", []),
        })
    return table


def generate_chains_from_events(events):
    """从事件中提取因果链（规则兜底版）"""
    chains = []
    seen_themes = set()

    # 按主题分组事件
    theme_groups = {}
    for ev in events:
        tags = ev.get("tags", [])
        for tag in tags:
            tag_type = tag.get("type", "macro")
            if tag_type not in theme_groups:
                theme_groups[tag_type] = []
            theme_groups[tag_type].append(ev)

    # 为每个有3+事件的主题生成一条因果链
    for theme, group_events in theme_groups.items():
        if len(group_events) < 2:
            continue
        # 取该主题下前3个最重要的事件
        top_events = group_events[:4]

        theme_names = {
            "ai": ("AI产业链因果链", "AI Industry Chain Causal Chain"),
            "fed": ("央行政策因果链", "Central Bank Policy Causal Chain"),
            "energy": ("能源市场因果链", "Energy Market Causal Chain"),
            "china": ("中国市场因果链", "China Market Causal Chain"),
            "bio": ("生物科技因果链", "Biotech Causal Chain"),
            "macro": ("宏观经济因果链", "Macro Economy Causal Chain"),
        }
        title_zh, title_en = theme_names.get(theme, ("市场因果链", "Market Causal Chain"))

        if title_zh in seen_themes:
            continue
        seen_themes.add(title_zh)

        # 构建流程节点
        nodes = []
        for i, ev in enumerate(top_events):
            node_type = "cause" if i == 0 else ("effect" if i == len(top_events) - 1 else "intermediate")
            text = ev.get("event", "")[:80]
            text_en = ev.get("event_en", text)[:80]
            nodes.append({"text": text, "text_en": text_en, "type": node_type})

        # 判断状态
        has_breaking = any(
            any(kw in ev.get("event", "") for kw in BREAKING_KEYWORDS_ZH)
            for ev in top_events
        )
        status = "consensus" if not has_breaking else "unverified"

        # 生成术语白话
        jargon = generate_jargon_for_theme(theme, top_events)

        chains.append({
            "title": title_zh,
            "title_en": title_en,
            "status": status,
            "nodes": nodes,
            "jargon": jargon,
        })

        if len(chains) >= 7:
            break

    return chains


def generate_jargon_for_theme(theme, events):
    """为特定主题的因果链生成术语白话"""
    jargon_map = {
        "ai": [
            {"term": "AI Capex（资本支出）", "term_en": "AI Capex (Capital Expenditure)",
             "explain": "AI公司花在买GPU、建数据中心、租算力上的钱。这笔钱最终流向芯片公司。",
             "explain_en": "Money AI companies spend on GPUs, data centers, and compute. Ultimately flows to chip makers."},
            {"term": "算力", "term_en": "Compute Power",
             "explain": "计算机处理信息的能力，AI训练和推理都需要大量算力。算力越多，AI越强。",
             "explain_en": "Computing capacity for AI training and inference. More compute = stronger AI."},
        ],
        "fed": [
            {"term": "FOMC会议纪要", "term_en": "FOMC Minutes",
             "explain": "美联储开会讨论的'会议记录'，透露委员们对加息的真实想法。比官方声明更'说真话'。",
             "explain_en": "Records of Fed meetings revealing members' true thinking on rates. More candid than official statements."},
            {"term": "鹰派/鸽派", "term_en": "Hawkish / Dovish",
             "explain": "鹰派偏向加息控通胀，鸽派偏向降息保就业。就像'刹车'和'油门'两种驾驶风格。",
             "explain_en": "Hawks favor rate hikes to control inflation; doves favor cuts to support employment."},
        ],
        "energy": [
            {"term": "地缘风险溢价", "term_en": "Geopolitical Risk Premium",
             "explain": "因为打仗或可能打仗，市场给油价多加的'保险费'。和平了，这笔钱就退掉。",
             "explain_en": "Extra 'insurance' added to oil prices due to war risk. Recedes when peace returns."},
            {"term": "OPEC+", "term_en": "OPEC+",
             "explain": "石油输出国组织及其盟友，控制全球约40%原油产量。减产=涨价，增产=跌价。",
             "explain_en": "Oil producers' alliance controlling ~40% of global supply. Cut = price up, increase = price down."},
        ],
        "china": [
            {"term": "社零（社会消费品零售总额）", "term_en": "Retail Sales",
             "explain": "老百姓花钱消费的总量，反映内需强弱。升=消费旺，降=消费弱。",
             "explain_en": "Total consumer spending, reflecting domestic demand strength."},
            {"term": "北向资金", "term_en": "Northbound Capital",
             "explain": "通过沪港通/深港通从香港流入A股的资金，被视为'外资风向标'。",
             "explain_en": "Capital flowing from HK into A-shares via Stock Connect, seen as 'foreign capital barometer'."},
        ],
        "macro": [
            {"term": "美元走强→商品下跌", "term_en": "Strong USD → Commodity Down",
             "explain": "国际大宗商品以美元计价。美元贵了，同样一桶油用美元买就贵了，需求减少，价格就跌。",
             "explain_en": "Commodities priced in USD. Stronger dollar = more expensive commodities = lower demand."},
            {"term": "避险情绪", "term_en": "Risk-Off Sentiment",
             "explain": "市场害怕风险时，资金从股票等高风险资产流向黄金/美债等安全资产。",
             "explain_en": "When markets fear risk, capital flows from stocks to safe havens like gold/Treasuries."},
        ],
    }

    base_jargon = jargon_map.get(theme, jargon_map["macro"])
    # 如果事件中有具体数字，增加一条关于数字的术语
    for ev in events:
        text = ev.get("event", "")
        if re.search(r'\d+\.?\d*%', text):
            base_jargon = base_jargon + [{
                "term": "涨跌幅", "term_en": "Price Change %",
                "explain": "价格变化的百分比。涨5%意味着如果你有100元，现在变成了105元。",
                "explain_en": "Percentage price change. +5% means 100 units become 105.",
            }]
            break

    return base_jargon[:3]


def generate_verifications_from_events(events, chains):
    """从事件和因果链生成待验证清单"""
    verifications = []

    # 取最重要的事件（有突发关键词或有方向分化的）
    key_events = []
    for ev in events:
        text = ev.get("event", "")
        score = 0
        if any(kw in text for kw in BREAKING_KEYWORDS_ZH):
            score += 10
        if ev.get("dir") == "split":
            score += 5
        if any(kw in text for kw in ["美联储", "加息", "降息", "CPI", "非农"]):
            score += 5
        if score > 0:
            key_events.append((ev, score))

    key_events.sort(key=lambda x: x[1], reverse=True)
    key_events = [ev for ev, _ in key_events[:4]]

    for ev in key_events:
        text = ev.get("event", "")
        text_en = ev.get("event_en", text)

        # 生成验证问题
        title = text[:60] + ("..." if len(text) > 60 else "")
        title_en = text_en[:60] + ("..." if len(text_en) > 60 else "")

        # 第一层：核心问题
        layer1 = f"该事件的后续发展如何？市场当前定价是否充分？"
        layer1_en = "How will this event develop? Is current market pricing adequate?"

        # 第二层：盯哪些变量
        vars_zh = [
            "相关资产价格次日开盘方向",
            "成交量是否异常放大（恐慌or追涨）",
            "官方/公司是否有后续声明或澄清",
            "关联资产是否同步反应（验证逻辑链）",
        ]
        vars_en = [
            "Related asset price direction at next open",
            "Volume anomaly (panic or chasing)",
            "Official/company follow-up statement",
            "Correlated assets confirmation",
        ]

        verifications.append({
            "title": title,
            "title_en": title_en,
            "layer1": layer1,
            "layer1_en": layer1_en,
            "vars": vars_zh,
            "vars_en": vars_en,
        })

        if len(verifications) >= 4:
            break

    return verifications


def generate_historical_analogies(events):
    """从事件中生成金融历史类比"""
    analogies = []
    seen_types = set()

    analogy_templates = {
        "ipo": {
            "event": "史上最大IPO → 市场顶部信号？",
            "event_en": "Largest IPO ever → Market top signal?",
            "lesson": "2000年思科市值5000亿成全球最大，随后互联网泡沫破裂跌80%。2021年Rivian上市首日涨29%，随后跌90%。史上最大IPO往往出现在产业泡沫顶部。",
            "lesson_en": "Historic IPOs often mark industry bubble tops: Cisco 2000 (-80%), Rivian 2021 (-90%).",
            "diff": "需关注公司是否有真实收入和产品，而非纯概念。",
            "diff_en": "Key: does the company have real revenue and product, not just concept?",
        },
        "fed_hawkish": {
            "event": "美联储鹰派 + 美元走强 → 新兴市场失血",
            "event_en": "Fed hawkish + strong USD → EM outflows",
            "lesson": "2022年美联储连续加息75bp，美元指数冲至114，新兴市场货币集体崩溃，港股恒生科技跌60%。",
            "lesson_en": "2022: Fed hiked 75bp consecutively, DXY hit 114, EM currencies collapsed, Hang Seng Tech -60%.",
            "diff": "当前美元指数远低于2022年峰值，中国央行有更大政策空间。",
            "diff_en": "Current DXY well below 2022 peak; PBOC has more policy room.",
        },
        "geopolitics_oil": {
            "event": "地缘冲突 → 油价跳涨",
            "event_en": "Geopolitical conflict → Oil price spike",
            "lesson": "1984年两伊'油轮战'数百艘船被击沉，油价从$29飙至$40。2019年阿曼湾油轮被袭，油价单日跳涨4%。",
            "lesson_en": "1984 Tanker War: oil $29→$40. 2019 Gulf of Oman: oil +4% in one day.",
            "diff": "需关注是否有和平对冲力量同时存在，以及海峡实际通行能力是否受影响。",
            "diff_en": "Key: is there a peace counter-force? Is the strait actually blocked?",
        },
        "ai_capex": {
            "event": "AI Capex暴增 → 烧钱还是投资未来？",
            "event_en": "AI Capex surge → Burning cash or investing in future?",
            "lesson": "2012-2015年亚马逊Capex占营收比超10%，FCF多次为负，华尔街质疑'烧钱'。但2015年后AWS贡献巨额利润，股价5年涨10倍。",
            "lesson_en": "2012-15 Amazon Capex >10% revenue, negative FCF. Post-2015 AWS profits drove 10x stock.",
            "diff": "需关注Capex/营收比是否持续上升，以及AI收入增速是否匹配投入。",
            "diff_en": "Key: is Capex/revenue ratio rising? Does AI revenue growth match spending?",
        },
        "chip_panic": {
            "event": "芯片股恐慌性杀跌 → 板块轮动信号？",
            "event_en": "Chip stock panic selloff → Sector rotation signal?",
            "lesson": "2018年中美贸易战期间，芯片股集体暴跌后迎来2019-2021年超级周期。恐慌往往是长期机会的起点。",
            "lesson_en": "2018 trade war chip selloff preceded 2019-2021 super cycle. Panic often marks long-term opportunity.",
            "diff": "需区分'恐慌性杀跌'和'基本面恶化'——前者是机会，后者是陷阱。",
            "diff_en": "Distinguish panic selling from fundamental deterioration — former is opportunity, latter is trap.",
        },
        "rate_sensitivity": {
            "event": "大宗商品全面承压 → 美元周期重现",
            "event_en": "Broad commodity selloff → USD cycle repeats",
            "lesson": "2014-2015年美元指数从80涨至100，黄金从$1300跌至$1050，原油从$100跌至$30。美元走强周期中大宗商品无一幸免。",
            "lesson_en": "2014-15: DXY 80→100, gold $1300→$1050, oil $100→$30. Strong dollar cycle spares no commodity.",
            "diff": "需关注美联储实际加息路径是否如预期，以及通胀是否支撑继续加息。",
            "diff_en": "Key: does Fed actually hike as expected? Does inflation support further hikes?",
        },
    }

    for ev in events:
        text = ev.get("event", "") + ev.get("event_en", "")
        text_lower = text.lower()

        analogy_type = None
        if "ipo" in text_lower or "上市" in text:
            analogy_type = "ipo"
        elif any(kw in text for kw in ["加息", "鹰派", "FOMC", "纪要"]) or "hawkish" in text_lower:
            analogy_type = "fed_hawkish"
        elif any(kw in text for kw in ["地缘", "战争", "冲突", "海峡", "油轮"]) or "geopolitical" in text_lower or "strait" in text_lower:
            analogy_type = "geopolitics_oil"
        elif any(kw in text for kw in ["AI", "资本支出", "Capex", "算力"]) and any(kw in text for kw in ["增", "暴", "亿"]):
            analogy_type = "ai_capex"
        elif any(kw in text for kw in ["芯片", "半导体", "代工", "断供"]) or "chip" in text_lower:
            analogy_type = "chip_panic"
        elif any(kw in text for kw in ["原油", "黄金", "铜", "大宗"]) and any(kw in text for kw in ["跌", "挫"]):
            analogy_type = "rate_sensitivity"

        if analogy_type and analogy_type not in seen_types:
            seen_types.add(analogy_type)
            template = analogy_templates[analogy_type]
            analogies.append(template)
            if len(analogies) >= 4:
                break

    return analogies


def rule_based_structure(headlines):
    """
    无 LLM 时的规则兜底方案 v4：
    生成完整标准结构：四列表 + 因果链 + 待验证 + 历史类比
    按重要性动态保留，不固定条数
    """
    events = []
    seen_topics = set()

    for h in headlines:
        text = h["text"]
        text_lower = text.lower()
        if len(text) < 15:
            continue

        # 判断方向（中文+英文）
        dir = "neutral"
        up_zh = any(kw in text for kw in ["涨", "升", "高", "增", "涨超"])
        down_zh = any(kw in text for kw in ["跌", "降", "低", "减", "跌超", "暴跌"])
        up_en = any(kw in text_lower for kw in ["surge", "soar", "rally", "jump", "rise", "gain", "climb", "record high", "new high"])
        down_en = any(kw in text_lower for kw in ["plunge", "slump", "tumble", "drop", "fall", "decline", "sink", "slide", "crash", "selloff", "record low", "new low"])

        if (up_zh or up_en) and (down_zh or down_en):
            dir = "split"
        elif up_zh or up_en:
            dir = "up"
        elif down_zh or down_en:
            dir = "down"

        # 判断标签（中文+英文）
        tags = []
        if any(kw in text for kw in ["AI", "芯片", "英伟达", "半导体", "人工智能", "OpenAI", "数据中心", "Anthropic"]) or \
           any(kw in text_lower for kw in ["ai ", "artificial intelligence", "nvidia", "chip", "semiconductor", "openai", "data center", "anthropic"]):
            tags.append({"type": "ai", "text": "AI", "text_en": "AI"})
        if any(kw in text for kw in ["美联储", "央行", "加息", "降息", "利率", "PPI", "CPI", "通胀", "FOMC"]) or \
           any(kw in text_lower for kw in ["fed", "federal reserve", "rate hike", "rate cut", "interest rate", "inflation", "cpi", "ppi", "powell", "fomc"]):
            tags.append({"type": "fed", "text": "央行", "text_en": "Central Bank"})
        if any(kw in text for kw in ["原油", "油价", "布油", "OPEC", "能源", "海峡", "油轮"]) or \
           any(kw in text_lower for kw in ["oil", "crude", "brent", "wti", "opec", "energy", "strait", "tanker"]):
            tags.append({"type": "energy", "text": "能源", "text_en": "Energy"})
        if any(kw in text for kw in ["中国", "A股", "社零", "工业增加值", "地产", "统计局", "创业板", "港股", "沪指"]) or \
           any(kw in text_lower for kw in ["china", "a-shares", "chinese", "beijing", "shanghai", "yuan", "hang seng"]):
            tags.append({"type": "china", "text": "中国", "text_en": "China"})
        if any(kw in text for kw in ["地缘", "战争", "冲突", "制裁", "宣言", "和平"]) or \
           any(kw in text_lower for kw in ["geopolitical", "war", "conflict", "sanction", "peace", "declaration"]):
            tags.append({"type": "geopolitics", "text": "地缘", "text_en": "Geopolitics"})
        if any(kw in text for kw in ["赤字", "财政", "国债", "发债", "出口", "贸易"]) or \
           any(kw in text_lower for kw in ["deficit", "fiscal", "treasury", "debt", "bond", "export", "trade"]):
            tags.append({"type": "macro", "text": "宏观", "text_en": "Macro"})
        if not tags:
            tags.append({"type": "macro", "text": "宏观", "text_en": "Macro"})

        # 提取事件描述
        event_text = text[:200] + ("..." if len(text) > 200 else "")
        chinese_re = re.compile(r'[\u4e00-\u9fff]')
        if chinese_re.search(event_text):
            event_en = translate_text(event_text)
        else:
            event_en = event_text

        # 提取资产和逻辑
        assets = extract_assets_from_text(text)
        assets_en_text = extract_assets_en(assets)
        logic = extract_logic_from_text(text, dir)
        logic_en = extract_logic_en(logic)

        # 简单去重（用前40字符）
        topic = text[:40].lower()
        if topic in seen_topics:
            continue
        seen_topics.add(topic)

        events.append({
            "tags": tags,
            "event": event_text,
            "event_en": event_en,
            "assets": assets,
            "assets_en": assets_en_text,
            "dir": dir,
            "logic": logic,
            "logic_en": logic_en,
        })

        if len(events) >= 50:
            break

    # 提取关键数字做 stats
    stats = []
    stat_seen = set()
    for h in headlines:
        text = h["text"]
        patterns_zh = [
            r'([\u4e00-\u9fa5\w]{2,10})[，,]?\s*(?:涨|跌|升|降)([\d.]+%)',
            r'([\u4e00-\u9fa5\w]{2,10}).*?创.*?(?:新高|新低)',
        ]
        patterns_en = [
            r'(Nasdaq|S&P|Dow|Nvidia|Apple|Tesla|Microsoft|Google|Amazon|Meta|oil|gold|Bitcoin|dollar|yen|euro|Treasury|yield)\s*(?:surge[sd]?|plunge[sd]?|rall(?:y|ies|ied)|drop[sd]?|fall[s]?|rose|fell|jump[sd]?|sink[s]?|slide[sd]?|decline[sd]?|gain[sd]?|climb[sd]?)?\s*(?:to)?\s*(?:\$)?([\d.]+%?)',
            r'([\d.]+%?)\s*(?:surge|plunge|rally|drop|fall|gain|decline)',
        ]
        for pattern in patterns_zh + patterns_en:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                label = m.group(1)[:20] if m.lastindex >= 1 else text[:20]
                if label.lower() in stat_seen:
                    continue
                stat_seen.add(label.lower())

                value = ""
                change = text[:60]
                dir_stat = "up"
                text_lower = text.lower()
                if any(kw in text for kw in ["跌", "降"]) or \
                   any(kw in text_lower for kw in ["plunge", "slump", "tumble", "drop", "fall", "decline", "sink", "slide", "crash", "selloff"]):
                    dir_stat = "down"
                if any(kw in text for kw in ["涨", "升"]) or \
                   any(kw in text_lower for kw in ["surge", "soar", "rally", "jump", "rise", "gain", "climb"]):
                    dir_stat = "up"
                if m.lastindex and m.lastindex >= 2:
                    value = m.group(2)

                chinese_re = re.compile(r'[\u4e00-\u9fff]')
                if chinese_re.search(label):
                    label_en = translate_text(label)
                else:
                    label_en = label

                stats.append({
                    "label": label,
                    "label_en": label_en,
                    "value": value or ("新高" if dir_stat == "up" else "新低"),
                    "change": change,
                    "change_en": translate_text(change) if chinese_re.search(change) else change,
                    "dir": dir_stat,
                })
                if len(stats) >= 12:
                    break
        if len(stats) >= 12:
            break

    # 生成四列表
    four_column_table = generate_four_column_table(events)

    # 生成因果链
    chains = generate_chains_from_events(events)

    # 生成待验证清单
    verifications = generate_verifications_from_events(events, chains)

    # 生成历史类比
    historical_analogies = generate_historical_analogies(events)

    log(f"[规则] 结构化完成: {len(events)} 条事件, {len(stats)} 条统计, "
        f"{len(four_column_table)} 行四列表, {len(chains)} 条因果链, "
        f"{len(verifications)} 项待验证, {len(historical_analogies)} 个历史类比")

    return {
        "stats": stats,
        "events": events,
        "four_column_table": four_column_table,
        "chains": chains,
        "verifications": verifications,
        "historical_analogies": historical_analogies,
    }


# ============================================================
# 主流程
# ============================================================

def generate_data_file(target_date=None, source="auto", dry_run=False):
    """生成指定日期的数据文件（中英双语）"""
    if target_date is None:
        target_date = date.today().isoformat()

    weekday_idx = datetime.strptime(target_date, "%Y-%m-%d").weekday()
    weekday = WEEKDAYS[weekday_idx]
    weekday_en = WEEKDAYS_EN[weekday_idx]

    log(f"{'='*60}")
    log(f"开始生成 {target_date} ({weekday} / {weekday_en}) 的市场地图数据")
    log(f"{'='*60}")

    # Step 1: 抓取
    headlines = fetch_headlines(source)
    if not headlines:
        log("抓取失败，退出")
        return False

    # Step 2: 三层漏斗筛选
    filtered = funnel_filter(headlines)
    if not filtered:
        log("筛选后无有效数据，退出")
        return False

    # Step 3: LLM 结构化（优先）或规则兜底
    structured = llm_structure(filtered)
    if structured is None:
        log("LLM 不可用，使用规则兜底方案")
        structured = rule_based_structure(filtered)

    # Step 4: 最终双语校验（确保万无一失）
    issues = validate_bilingual(structured)
    if issues:
        log(f"[校验] ⚠️ 发现 {len(issues)} 个双语问题，自动修复...")
        structured = auto_fill_english(structured)
        # 再次校验
        remaining = validate_bilingual(structured)
        if remaining:
            log(f"[校验] 仍有 {len(remaining)} 个问题无法自动修复:")
            for r in remaining[:5]:
                log(f"  - {r}")
        else:
            log("[校验] ✅ 所有问题已修复")
    else:
        log("[校验] ✅ 双语数据完整，无问题")

    # Step 5: 组装最终数据
    sources_used = list(set(h.get("source", "unknown") for h in headlines))
    data = {
        "date": target_date,
        "weekday": weekday,
        "weekday_en": weekday_en,
        "crawl_time": f"约{datetime.now().strftime('%H:%M')}（北京时间）",
        "source": " / ".join(sources_used[:5]),
        "sources_detail": sources_used,
        "filter_result": f"{len(structured.get('events',[]))}条核心要闻 / {len(structured.get('chains',[]))}条因果链 / {len(headlines)}条原始抓取",
        "stats": structured.get("stats", []),
        "events": structured.get("events", []),
        "four_column_table": structured.get("four_column_table", []),
        "chains": structured.get("chains", []),
        "verifications": structured.get("verifications", []),
        "historical_analogies": structured.get("historical_analogies", []),
    }

    if dry_run:
        log(f"[DRY-RUN] 不保存文件，数据预览:")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        return True

    # Step 6: 保存
    filepath = os.path.join(DATA_DIR, f"{target_date}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log(f"数据已保存: {filepath}")
    log(f"统计: {len(data['stats'])} 条统计, {len(data['events'])} 条事件, "
        f"{len(data.get('four_column_table', []))} 行四列表, "
        f"{len(data['chains'])} 条因果链, {len(data['verifications'])} 条待验证, "
        f"{len(data.get('historical_analogies', []))} 个历史类比")
    return True


def main():
    parser = argparse.ArgumentParser(description="每日市场地图自动更新（中英双语）")
    parser.add_argument("--date", type=str, default=None, help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--source", type=str, default="auto",
                        choices=["auto", "api", "rss", "page", "cnbc"],
                        help="数据源: auto/rss/api/page/cnbc")
    parser.add_argument("--dry-run", action="store_true", help="只抓取不保存")
    args = parser.parse_args()

    success = generate_data_file(
        target_date=args.date,
        source=args.source,
        dry_run=args.dry_run,
    )

    if success:
        log("✅ 更新成功")
        sys.exit(0)
    else:
        log("❌ 更新失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
