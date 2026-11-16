#!/usr/bin/env python3
"""
每日市场地图 - 自动更新脚本 (完整版 v2)

数据流：
  多源RSS抓取 → 原始快讯 → 三层漏斗筛选 → LLM结构化/规则兜底 → 中英双语JSON → 网站自动展示

数据源（按优先级）：
  1. CNBC Top News RSS        (英文, 30条)
  2. CNBC World News RSS       (英文, 30条)
  3. CNBC Economy RSS          (英文, 30条)
  4. MarketWatch Top Stories   (英文, 10条)
  5. Investing.com News RSS    (英文, 10条)
  6. 华尔街见闻 API            (中文, 可能403)
  7. 华尔街见闻 RSS            (中文, 可能404)
  8. 华尔街见闻 页面           (中文, SPA可能无数据)

使用方法：
  python3 update_daily.py                        # 抓取今天的数据
  python3 update_daily.py --date 2026-11-17      # 指定日期
  python3 update_daily.py --dry-run              # 只抓取不保存（测试用）
  python3 update_daily.py --source rss           # 只用RSS源
  python3 update_daily.py --source cnbc          # 只用CNBC

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

# RSS 数据源（全部已验证可用）
RSS_SOURCES = [
    {
        "name": "CNBC Top News",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "lang": "en",
        "weight": 3,  # 高权重
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

# 华尔街见闻（保留尝试，可能恢复）
WSCN_API = "https://api.wallstreetcn.com/apiv1/content/lives?channel=global-channel&limit=200"
WSCN_RSS = "https://wallstreetcn.com/rss"
WSCN_PAGE = "https://wallstreetcn.com/live/global"

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
    """通过华尔街见闻 API 抓取快讯（可能403，保留尝试）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://wallstreetcn.com/live/global",
    }
    try:
        log(f"[API] 正在请求华尔街见闻 API: {WSCN_API}")
        resp = requests.get(WSCN_API, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        log(f"[API] 获取 {len(items)} 条快讯")
        headlines = []
        for item in items:
            text = item.get("content_text", "") or item.get("content", "")
            if "<" in text:
                text = BeautifulSoup(text, "html.parser").get_text(strip=True)
            create_time = item.get("created_at", 0)
            if create_time:
                dt = datetime.fromtimestamp(create_time)
            else:
                dt = datetime.now()
            headlines.append({
                "text": text.strip(),
                "time": dt.strftime("%H:%M"),
                "timestamp": create_time,
                "source": "华尔街见闻API",
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
    优先尝试国际RSS源（已验证可用），同时尝试华尔街见闻（可能恢复）
    """
    if source == "api":
        return fetch_via_api()
    elif source == "rss":
        return fetch_all_rss()
    elif source == "page":
        return fetch_via_page()
    elif source == "cnbc":
        # 只用CNBC源
        cnbc_sources = [s for s in RSS_SOURCES if "CNBC" in s["name"]]
        all_h = []
        for s in cnbc_sources:
            all_h.extend(fetch_via_rss_source(s))
        return all_h
    else:
        # auto: 先抓国际RSS（可靠），再尝试华尔街见闻（可能失败）
        all_headlines = fetch_all_rss()

        # 尝试华尔街见闻（增加中文内容）
        for fetch_fn in [fetch_via_api, fetch_via_wscn_rss, fetch_via_page]:
            wscn_headlines = fetch_fn()
            if wscn_headlines:
                all_headlines.extend(wscn_headlines)
                break
            time.sleep(1)

        if not all_headlines:
            log("❌ 所有抓取方式均失败")
        else:
            # 多源去重（不同源可能有相同新闻）
            seen_texts = set()
            deduped = []
            for h in all_headlines:
                # 用文本前80字符的hash做跨源去重
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
  ]
}}

Requirements:
1. stats: extract ALL important market data points (no fixed limit — include every significant number: index moves, commodity prices, currency rates, crypto, yields, etc.)
2. events: include ALL significant market events — do NOT cap at a fixed number. If there are many important developments, include them all. Prioritize by importance but don't exclude important news just to fit a limit.
3. chains: extract causal chains for every significant market narrative (aim for completeness, not a fixed count)
4. verifications: generate watchlist items for key uncertainties
5. Use <br> for line breaks in node text
6. CRITICAL: Every *_en field MUST be in pure English with NO Chinese characters whatsoever
7. CRITICAL: Every Chinese field MUST have a corresponding *_en English field
8. English must use proper financial terminology (e.g., "re-rating" not "haircut", "rate hike" not "interest increase")
9. For English-language news headlines, the Chinese fields should be proper translations (not transliterations)
10. Output strictly valid JSON"""


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


def rule_based_structure(headlines):
    """
    无 LLM 时的规则兜底方案：
    从快讯中提取关键信息，生成基础中英双语结构化数据
    v2: 去掉硬编码上限，按重要性动态保留
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
        if any(kw in text for kw in ["AI", "芯片", "英伟达", "半导体", "人工智能", "OpenAI", "数据中心"]) or \
           any(kw in text_lower for kw in ["ai ", "artificial intelligence", "nvidia", "chip", "semiconductor", "openai", "data center", "anthropic"]):
            tags.append({"type": "ai", "text": "AI", "text_en": "AI"})
        if any(kw in text for kw in ["美联储", "央行", "加息", "降息", "利率", "PPI", "CPI", "通胀"]) or \
           any(kw in text_lower for kw in ["fed", "federal reserve", "rate hike", "rate cut", "interest rate", "inflation", "cpi", "ppi", "powell", "warsh"]):
            tags.append({"type": "fed", "text": "央行", "text_en": "Central Bank"})
        if any(kw in text for kw in ["原油", "油价", "布油", "OPEC", "能源"]) or \
           any(kw in text_lower for kw in ["oil", "crude", "brent", "wti", "opec", "energy"]):
            tags.append({"type": "energy", "text": "能源", "text_en": "Energy"})
        if any(kw in text for kw in ["中国", "A股", "社零", "工业增加值", "地产", "统计局", "创业板", "港股"]) or \
           any(kw in text_lower for kw in ["china", "a-shares", "chinese", "beijing", "shanghai", "yuan", "hang seng"]):
            tags.append({"type": "china", "text": "中国", "text_en": "China"})
        if any(kw in text for kw in ["生物科技", "创新药", "医药", "临床"]) or \
           any(kw in text_lower for kw in ["biotech", "pharma", "drug", "clinical", "fda"]):
            tags.append({"type": "bio", "text": "生物科技", "text_en": "Biotech"})
        if any(kw in text for kw in ["赤字", "财政", "国债", "发债"]) or \
           any(kw in text_lower for kw in ["deficit", "fiscal", "treasury", "debt", "bond"]):
            tags.append({"type": "macro", "text": "财政", "text_en": "Fiscal"})
        if not tags:
            tags.append({"type": "macro", "text": "宏观", "text_en": "Macro"})

        # 提取数字
        numbers = re.findall(r'(\d+\.?\d*%?)', text)
        # 简化事件描述
        event_text = text[:200] + ("..." if len(text) > 200 else "")
        # 如果原文是英文，event_en直接用原文；如果有中文，用规则翻译
        chinese_re = re.compile(r'[\u4e00-\u9fff]')
        if chinese_re.search(event_text):
            event_en = translate_text(event_text)
        else:
            # 英文原文，中文需要标记（规则兜底无法翻译英文→中文）
            event_en = event_text  # 英文原样保留
            event_text = event_text  # 也保留原文（LLM不可用时的妥协）

        # 简单去重（用前40字符）
        topic = text[:40].lower()
        if topic in seen_topics:
            continue
        seen_topics.add(topic)

        events.append({
            "tags": tags,
            "event": event_text,
            "event_en": event_en,
            "assets": "",
            "assets_en": "",
            "dir": dir,
            "logic": "",
            "logic_en": "",
        })

        # 不再硬编码上限 —— 保留所有有意义的条目
        # 但设置一个安全上限防止极端情况
        if len(events) >= 50:
            break

    # 提取关键数字做 stats
    stats = []
    stat_seen = set()
    for h in headlines:
        text = h["text"]
        # 中文模式
        patterns_zh = [
            r'([\u4e00-\u9fa5\w]{2,10})[，,]?\s*(?:涨|跌|升|降)([\d.]+%)',
            r'([\u4e00-\u9fa5\w]{2,10}).*?创.*?(?:新高|新低)',
        ]
        # 英文模式
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
                dir = "up"
                text_lower = text.lower()
                if any(kw in text for kw in ["跌", "降"]) or \
                   any(kw in text_lower for kw in ["plunge", "slump", "tumble", "drop", "fall", "decline", "sink", "slide", "crash", "selloff"]):
                    dir = "down"
                if any(kw in text for kw in ["涨", "升"]) or \
                   any(kw in text_lower for kw in ["surge", "soar", "rally", "jump", "rise", "gain", "climb"]):
                    dir = "up"
                if m.lastindex and m.lastindex >= 2:
                    value = m.group(2)

                chinese_re = re.compile(r'[\u4e00-\u9fff]')
                if chinese_re.search(label):
                    label_en = translate_text(label)
                else:
                    label_en = label

                stats.append({
                    "label": label if chinese_re.search(label) else label,
                    "label_en": label_en,
                    "value": value or ("新高" if dir == "up" else "新低"),
                    "change": change,
                    "change_en": translate_text(change) if chinese_re.search(change) else change,
                    "dir": dir,
                })
                if len(stats) >= 12:
                    break
        if len(stats) >= 12:
            break

    log(f"[规则] 结构化完成: {len(events)} 条事件, {len(stats)} 条统计")

    return {
        "stats": stats,
        "events": events,
        "chains": [],
        "verifications": [],
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
    # 列出所有数据源
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
        "chains": structured.get("chains", []),
        "verifications": structured.get("verifications", []),
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
        f"{len(data['chains'])} 条因果链, {len(data['verifications'])} 条待验证")
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
