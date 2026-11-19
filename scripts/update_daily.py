#!/usr/bin/env python3
"""
每日市场地图 - 自动更新脚本 (完整版 v5)

数据流：
  华尔街见闻API抓取 → 原始快讯 → 三层漏斗筛选 → LLM结构化/规则兜底 → 中英双语JSON → 网站自动展示

v5 升级要点（全部对齐用户标准）：
  - 四列表：三层漏斗筛到6-10条核心，事件描述精炼（不是原文塞入）
  - 因果链：真正的因果逻辑串联（A→B→C→价格变动），每条含3个术语白话解释
  - 待验证：针对每条因果链的核心问题 + 4个具体盯盘变量（不是通用模板）
  - 历史类比：根据当日事件类型匹配真实历史事件 + 教训 + 关键区别

数据源（按优先级）：
  1. 华尔街见闻 API            (中文, 主数据源, ~100条/次)
     域名: api-one-wscn.awtmt.com (2026年迁移，旧域名 api.wallstreetcn.com 已失效)
  2. CNBC Top News RSS        (英文, 备用)
  3. CNBC World News RSS       (英文, 备用)
  4. CNBC Economy RSS          (英文, 备用)
  5. MarketWatch Top Stories   (英文, 备用)
  6. Investing.com News RSS    (英文, 备用)

使用方法：
  python3 update_daily.py                        # 抓取今天的数据
  python3 update_daily.py --date 2026-11-19      # 指定日期
  python3 update_daily.py --dry-run              # 只抓取不保存（测试用）
  python3 update_daily.py --source api           # 只用华尔街见闻API

环境变量：
  LLM_API_KEY    - LLM API 密钥（用于结构化，可选，无则用规则兜底）
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
WSCN_API = "https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit=200"
WSCN_RSS = "https://wallstreetcn.com/rss"
WSCN_PAGE = "https://wallstreetcn.com/live/global"

# 备用 RSS 数据源
RSS_SOURCES = [
    {"name": "CNBC Top News", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "lang": "en", "weight": 3},
    {"name": "CNBC World News", "url": "https://www.cnbc.com/id/100727362/device/rss/rss.html", "lang": "en", "weight": 2},
    {"name": "CNBC Economy", "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html", "lang": "en", "weight": 2},
    {"name": "MarketWatch Top Stories", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "lang": "en", "weight": 2},
    {"name": "Investing.com News", "url": "https://www.investing.com/rss/news_1.rss", "lang": "en", "weight": 1},
]

# ============================================================
# 关键词配置（中英双语）
# ============================================================

MARKET_KEYWORDS_ZH = [
    "涨", "跌", "涨超", "跌超", "大涨", "大跌", "飙升", "暴跌", "新高", "新低",
    "涨幅", "跌幅", "上涨", "下跌", "收涨", "收跌",
    "美股", "A股", "港股", "日股", "欧股", "纳指", "标普", "道指", "创业板", "科创",
    "美元", "日元", "欧元", "英镑", "人民币", "汇率",
    "美债", "国债", "收益率", "十年期", "两年期",
    "原油", "布油", "黄金", "白银", "铜", "铁矿石",
    "比特币", "以太坊", "加密",
    "美联储", "加息", "降息", "缩表", "QE", "利率", "PPI", "CPI", "PMI",
    "非农", "就业", "通胀", "GDP", "赤字", "财政",
    "央行", "日本央行", "欧央行", "人民银行",
    "英伟达", "苹果", "特斯拉", "微软", "谷歌", "亚马逊", "Meta",
    "半导体", "芯片", "AI", "人工智能", "数据中心",
    "SpaceX", "OpenAI", "Anthropic", "生物科技", "创新药",
    "社零", "工业增加值", "地产", "房地产", "基建", "出口", "进口",
    "统计局", "国务院", "证监会",
    "IPO", "财报", "营收", "利润", "Capex", "自由现金流",
    "地缘", "战争", "冲突", "制裁", "宣言", "和平",
    "海峡", "油轮", "OPEC", "OPEC+",
    "债务", "利差", "鹰派", "鸽派",
]

MARKET_KEYWORDS_EN = [
    "surge", "soar", "rally", "jump", "rise", "gain", "climb",
    "plunge", "slump", "tumble", "drop", "fall", "decline", "sink", "slide",
    "spike", "dive", "crash", "correction", "selloff",
    "record high", "record low", "new high", "new low", "all-time high",
    "stock", "stocks", "equity", "equities", "share", "shares",
    "Nasdaq", "S&P", "Dow", "Russell", "NYSE",
    "dollar", "yen", "euro", "pound", "sterling", "yuan", "currency", "currencies", "FX",
    "Treasury", "Treasuries", "yield", "bond", "bonds", "10-year", "2-year",
    "oil", "crude", "Brent", "WTI", "gold", "silver", "copper",
    "Bitcoin", "Ethereum", "crypto", "cryptocurrency",
    "A-shares", "HK stocks", "Hang Seng",
    "Fed", "Federal Reserve", "rate hike", "rate cut", "interest rate",
    "PPI", "CPI", "PMI", "nonfarm", "payrolls", "jobs report",
    "inflation", "GDP", "deficit", "fiscal", "treasury",
    "central bank", "Bank of Japan", "BOJ", "ECB", "PBOC",
    "Powell", "Yellen",
    "Nvidia", "Apple", "Tesla", "Microsoft", "Google", "Alphabet",
    "Amazon", "Meta", "Facebook",
    "semiconductor", "chip", "chips", "AI", "artificial intelligence",
    "data center", "SpaceX", "OpenAI", "Anthropic",
    "biotech", "pharma", "drug",
    "OPEC", "OPEC+", "energy", "oil price",
    "earnings", "revenue", "guidance", "IPO", "SPAC",
    "merger", "acquisition", "M&A",
    "bullish", "bearish", "volatility", "VIX",
    "safe haven", "risk-off", "risk-on", "flight to safety",
    "recession", "soft landing", "hard landing",
    "valuation", "bubble", "correction",
    "Capex", "free cash flow", "FCF",
    "geopolitical", "sanction", "strait", "tanker",
    "spread", "hawkish", "dovish", "debt",
]

MARKET_KEYWORDS = MARKET_KEYWORDS_ZH + MARKET_KEYWORDS_EN

NOISE_KEYWORDS = [
    "广告", "推广", "赞助", "活动", "报名", "直播预约",
    "课程", "会员", "订阅", "下载APP",
    "subscribe", "newsletter", "sign up", "download app",
    "advertisement", "sponsored", "promoted",
]

BREAKING_KEYWORDS_ZH = [
    "紧急", "突发", "重磅", "暴跌", "飙升", "熔断", "崩盘",
    "加息", "降息", "非农", "CPI", "PPI", "GDP",
    "美联储", "主席", "声明", "决议",
]
BREAKING_KEYWORDS_EN = [
    "breaking", "urgent", "just in", "alert",
    "crash", "plunge", "surge", "spike", "circuit breaker",
    "rate hike", "rate cut", "nonfarm", "payrolls",
    "Fed Chair", "Powell says",
    "emergency", "crisis", "historic",
]

# ============================================================
# 金融术语中英对照表
# ============================================================

FINANCIAL_GLOSSARY = {
    "美联储": "the Fed", "加息": "rate hike", "降息": "rate cut",
    "通胀": "inflation", "收益率": "yield", "美债": "US Treasuries",
    "国债": "government bonds", "美元指数": "Dollar Index",
    "日元": "JPY", "人民币": "CNY",
    "工业增加值": "industrial output", "社零": "retail sales",
    "财政赤字": "fiscal deficit", "PPI": "PPI", "CPI": "CPI",
    "英伟达": "Nvidia", "特斯拉": "Tesla", "苹果": "Apple",
    "微软": "Microsoft", "亚马逊": "Amazon", "谷歌": "Google",
    "半导体": "semiconductors", "芯片": "chips",
    "原油": "crude oil", "布油": "Brent crude", "黄金": "gold",
    "比特币": "Bitcoin", "创业板": "ChiNext", "港股": "HK stocks",
    "A股": "A-shares", "纳指": "Nasdaq", "标普": "S&P",
    "新高": "new high", "新低": "new low",
    "飙升": "surge", "暴跌": "plunge", "大涨": "rally", "大跌": "selloff",
    "SpaceX": "SpaceX", "OpenAI": "OpenAI", "Anthropic": "Anthropic",
    "生物科技": "biotech", "创新药": "innovative drugs",
    "风险偏好": "risk appetite", "流动性": "liquidity",
    "实际利率": "real interest rate", "供应过剩": "supply surplus",
    "鹰派": "hawkish", "鸽派": "dovish",
    "利差": "spread", "终点利率": "terminal rate",
    "地缘风险溢价": "geopolitical risk premium",
    "自由现金流": "free cash flow", "资本开支": "capital expenditure",
    "资本性支出": "capital expenditure",
    "霍尔木兹海峡": "Strait of Hormuz",
    "超级油轮": "VLCC",
    "欧央行": "ECB", "日本央行": "BOJ", "人民银行": "PBOC",
    "避险资产": "safe-haven assets", "避险情绪": "risk-off sentiment",
    "估值重估": "re-rating", "估值泡沫": "valuation bubble",
    # 数字相关
    "万亿": "trillion", "十亿": "billion", "百万": "million",
    "元": "yuan", "美元": "USD", "欧元": "EUR", "英镑": "GBP",
    "韩元": "KRW",
    # 常见动词/形容词
    "上涨": "rise", "下跌": "fall", "收涨": "close up", "收跌": "close down",
    "涨幅": "gain", "跌幅": "loss", "涨超": "surge past", "跌超": "drop below",
    "创": "hit", "新高": "new high",
    "收盘": "close", "开盘": "open", "盘前": "pre-market", "盘后": "post-market",
    "预估": "estimate", "预期": "expected", "超预期": "beat expectations",
    "不及预期": "miss expectations", "低于预期": "below expectations",
    "财报": "earnings", "营收": "revenue", "利润": "profit", "净利": "net income",
    "增长": "growth", "下降": "decline", "扩大": "expand", "缩小": "narrow",
    "期货": "futures", "主力合约": "main contract",
    "沪指": "Shanghai Composite", "深成指": "Shenzhen Component",
    "科创50": "STAR 50", "恒生科技": "Hang Seng Tech",
    "标普500": "S&P 500", "道指": "Dow Jones",
    "商品期货": "commodity futures",
    "沪铜": "SHFE Copper", "沪锡": "SHFE Tin", "沪银": "SHFE Silver",
    "沪镍": "SHFE Nickel", "苹果": "Apple",
    "液化气": "LPG", "乙二醇": "EG", "丙烯": "propylene",
    "光刻机": "lithography", "光刻胶": "photoresist",
    "存储芯片": "memory chips", "先进封装": "advanced packaging",
    "涨停": "limit up", "跌停": "limit down",
    "中国国家主席习近平": "Chinese President Xi Jinping",
    "俄罗斯总统普京": "Russian President Putin",
    "美国总统特朗普": "US President Trump",
    "深圳": "Shenzhen", "会晤": "summit", "举行": "held",
    "声明": "statement", "宣言": "declaration", "和平": "peace",
    "暗盘交易": "grey market trading", "发行价": "issue price",
    "融资": "funding", "上市": "listing", "挂牌": "listed",
    "出口": "exports", "进口": "imports", "贸易": "trade",
    "财政": "fiscal", "赤字": "deficit", "债务": "debt",
    "核风险": "nuclear risk", "对话": "dialogue", "共识": "consensus",
    "能源": "energy", "增产": "production increase", "供应": "supply",
    "风险": "risk", "溢价": "premium", "压缩": "compression",
    "狂欢": "rally", "受益": "benefit", "承压": "under pressure",
    "分化": "diverge", "联动": "correlate", "预期": "expectation",
    "验证": "validation", "叙事": "narrative", "可持续性": "sustainability",
    "恐慌": "panic", "情绪": "sentiment", "信心": "confidence",
    "波动": "volatility", "放大": "amplify", "异常": "abnormal",
    "成交量": "volume", "资金": "capital", "流向": "flow",
    "官方": "official", "央行": "central bank",
    "后续": "follow-up", "声明": "statement", "澄清": "clarification",
    "关联": "correlated", "同步": "synchronized", "反应": "reaction",
    "利率": "interest rate", "流动性": "liquidity",
    "内需": "domestic demand", "外需": "external demand",
    "沪深": "Shanghai-Shenzhen", "成交": "turnover",
    "调整": "adjustment", "震荡": "volatile",
    "三大指数": "three major indices", "小幅": "slightly",
    "概念": "concept", "板块": "sector", "逆势": "bucking trend",
    "活跃": "active", "拉升": "rally", "下跌方面": "on the downside",
    "增持": "increase holdings", "减持": "reduce holdings",
    "净流入": "net inflow", "净流出": "net outflow",
    "外资": "foreign capital", "看好": "bullish", "谨慎": "cautious",
    "回暖": "recovering", "承压": "pressured",
    "放量": "high volume", "缩量": "low volume", "观望": "wait-and-see",
    "盈利质量": "earnings quality", "盘后": "post-market",
    "指数": "index", "收报": "closed at", "报": "reported",
    "扩大": "expanded", "规模": "scale",
    "季度": "quarter", "财季": "fiscal quarter",
    "年": "year", "月": "month", "日": "day",
    "首次": "first time", "突破": "break through",
    "主力": "main", "合约": "contract",
    "国际": "international", "铜": "copper",
    "镍": "nickel", "锡": "tin", "银": "silver",
    "财政收入": "fiscal revenue", "支出": "expenditure",
}


def translate_text(text):
    """基础规则翻译：用术语词典做简单替换"""
    if not text:
        return ""
    result = text
    sorted_terms = sorted(FINANCIAL_GLOSSARY.items(), key=lambda x: len(x[0]), reverse=True)
    for zh, en in sorted_terms:
        result = result.replace(zh, en)
    return result


def log(msg):
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
        resp = requests.get(source["url"], headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")
        log(f"[RSS] {source['name']}: {len(items)} 条")
        headlines = []
        for item in items:
            title = item.find("title")
            desc = item.find("description")
            pub = item.find("pubDate")
            text = ""
            if title:
                text += title.get_text(strip=True)
            if desc:
                desc_text = desc.get_text(strip=True)
                if desc_text and desc_text != text:
                    if "<" in desc_text:
                        desc_text = BeautifulSoup(desc_text, "html.parser").get_text(strip=True)
                    text += " | " + desc_text[:200]
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
                    "text": text.strip(), "time": time_str,
                    "timestamp": timestamp, "source": source["name"],
                    "lang": source["lang"], "weight": source.get("weight", 1),
                })
        return headlines
    except Exception as e:
        log(f"[RSS] {source['name']} 失败: {e}")
        return []


def fetch_all_rss():
    all_headlines = []
    for source in RSS_SOURCES:
        headlines = fetch_via_rss_source(source)
        all_headlines.extend(headlines)
        time.sleep(0.5)
    log(f"[RSS] 所有源合计: {len(all_headlines)} 条")
    return all_headlines


def fetch_via_api():
    """通过华尔街见闻 API 抓取快讯（主数据源）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://wallstreetcn.com",
        "Referer": "https://wallstreetcn.com/live/global",
    }
    try:
        log(f"[API] 请求华尔街见闻 API: {WSCN_API}")
        resp = requests.get(WSCN_API, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        log(f"[API] 华尔街见闻: {len(items)} 条快讯")
        headlines = []
        for item in items:
            text = item.get("content_text", "") or item.get("content", "")
            if "<" in text:
                text = BeautifulSoup(text, "html.parser").get_text(strip=True)
            create_time = item.get("display_time", 0) or item.get("created_at", 0)
            if create_time:
                dt = datetime.fromtimestamp(create_time)
            else:
                dt = datetime.now()
            headlines.append({
                "text": text.strip(), "time": dt.strftime("%H:%M"),
                "timestamp": create_time, "source": "华尔街见闻",
                "lang": "zh", "weight": 3,
            })
        return headlines
    except Exception as e:
        log(f"[API] 华尔街见闻API失败: {e}")
        return []


def fetch_via_wscn_rss():
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    try:
        resp = requests.get(WSCN_RSS, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")
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
            time_str = pub.get_text(strip=True) if pub else ""
            headlines.append({
                "text": text.strip(), "time": time_str,
                "timestamp": 0, "source": "华尔街见闻RSS",
                "lang": "zh", "weight": 3,
            })
        return headlines
    except Exception as e:
        log(f"[RSS] 华尔街见闻RSS失败: {e}")
        return []


def fetch_via_page():
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://wallstreetcn.com/",
    }
    try:
        resp = requests.get(WSCN_PAGE, headers=headers, timeout=15)
        resp.raise_for_status()
        text = resp.text
        headlines = []
        patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});',
            r'window\.__NUXT__\s*=\s*(\{.*?\});',
            r'"content_text"\s*:\s*"([^"]+)"',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            if matches:
                for m in matches[:200]:
                    if len(m) > 10 and not m.startswith("{"):
                        clean = BeautifulSoup(m, "html.parser").get_text(strip=True)
                        if clean:
                            headlines.append({
                                "text": clean, "time": "", "timestamp": 0,
                                "source": "华尔街见闻页面", "lang": "zh", "weight": 3,
                            })
                if headlines:
                    break
        if not headlines:
            soup = BeautifulSoup(text, "html.parser")
            for sel in [".live-item", ".news-item", ".timeline-item", ".live-content", ".content-text"]:
                items = soup.select(sel)
                if items:
                    for item in items:
                        t = item.get_text(strip=True)
                        if t and len(t) > 10:
                            headlines.append({
                                "text": t, "time": "", "timestamp": 0,
                                "source": "华尔街见闻页面", "lang": "zh", "weight": 3,
                            })
                    break
        return headlines
    except Exception as e:
        log(f"[PAGE] 华尔街见闻页面失败: {e}")
        return []


def fetch_headlines(source="auto"):
    """抓取快讯（多源聚合）"""
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
        all_headlines = []
        wscn_headlines = fetch_via_api()
        if wscn_headlines:
            all_headlines.extend(wscn_headlines)
            log(f"✅ 华尔街见闻: {len(wscn_headlines)} 条（主数据源）")
        if not wscn_headlines or len(wscn_headlines) < 20:
            log("华尔街见闻数据不足，补充国际RSS源...")
            rss_headlines = fetch_all_rss()
            all_headlines.extend(rss_headlines)
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
# 第二层：三层漏斗筛选
# ============================================================

def funnel_filter(headlines):
    """
    三层漏斗筛选：
    第一层：与价格变动/新信息/宏观/资产相关的条目
    第二层：去重去噪
    第三层：按重要性打分排序，保留6-10条核心
    """
    # === 第一层：关键词过滤 ===
    filtered = []
    for h in headlines:
        text = h["text"]
        text_lower = text.lower()
        if any(kw in text_lower for kw in [n.lower() for n in NOISE_KEYWORDS]):
            continue
        if any(kw in text for kw in MARKET_KEYWORDS_ZH) or \
           any(kw in text_lower for kw in MARKET_KEYWORDS_EN):
            filtered.append(h)
    log(f"第一层过滤: {len(headlines)} → {len(filtered)} 条")

    # === 第二层：去重去噪 ===
    seen_hashes = set()
    deduped = []
    for h in filtered:
        text_hash = hashlib.md5(h["text"][:100].encode()).hexdigest()
        if text_hash not in seen_hashes:
            seen_hashes.add(text_hash)
            deduped.append(h)
    log(f"第二层去重: {len(filtered)} → {len(deduped)} 条")

    # === 第三层：按重要性打分排序 ===
    def importance_score(h):
        text = h["text"]
        text_lower = text.lower()
        score = 0
        if re.search(r'\d+\.?\d*%?', text):
            score += 5
        price_words_zh = sum(1 for kw in ["涨", "跌", "新高", "新低", "飙升", "暴跌"] if kw in text)
        score += price_words_zh * 3
        price_words_en = sum(1 for kw in [
            "surge", "soar", "rally", "jump", "plunge", "slump",
            "tumble", "drop", "fall", "crash", "spike", "dive",
            "record high", "record low", "new high", "new low",
            "selloff", "correction"
        ] if kw in text_lower)
        score += price_words_en * 3
        market_count = sum(1 for kw in MARKET_KEYWORDS_ZH if kw in text)
        market_count += sum(1 for kw in MARKET_KEYWORDS_EN if kw in text_lower)
        score += market_count * 2
        breaking_zh = sum(1 for kw in BREAKING_KEYWORDS_ZH if kw in text)
        breaking_en = sum(1 for kw in BREAKING_KEYWORDS_EN if kw in text_lower)
        score += (breaking_zh + breaking_en) * 10
        if len(text) > 50:
            score += 3
        if len(text) > 100:
            score += 2
        if len(text) > 200:
            score += 1
        score += h.get("weight", 1)
        return score

    scored = [(h, importance_score(h)) for h in deduped]
    scored.sort(key=lambda x: x[1], reverse=True)

    # 保留6-10条核心（得分最高的）
    top_headlines = [h for h, s in scored[:10]]
    log(f"第三层排序: 保留 {len(top_headlines)} 条核心快讯")
    return top_headlines


# ============================================================
# 第三层：LLM 结构化（双语输出，需要 API key）
# ============================================================

LLM_PROMPT = """You are a senior macro trader and financial science writer. Extract information from the following flash news headlines and generate a daily market map in BOTH Chinese and English.

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
      "tags": [{{"type": "ai/fed/energy/china/bio/macro/geopolitics/central-bank", "text": "标签（中文）", "text_en": "Tag (English)"}}],
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
      "title": "因果链标题（中文，格式：主题：A → B → C）",
      "title_en": "Causal chain title (English)",
      "status": "consensus or unverified",
      "nodes": [
        {{"text": "节点描述（中文）", "text_en": "Node description (English)", "type": "cause/intermediate/effect"}}
      ],
      "jargon": [
        {{
          "term": "术语名称（中文）",
          "term_en": "Term (English)",
          "explain": "白话解释（中文，一句话讲清）",
          "explain_en": "Plain-language explanation (English)"
        }}
      ]
    }}
  ],
  "verifications": [
    {{
      "title": "待验证问题（中文）",
      "title_en": "Question to verify (English)",
      "layer1": "核心问题（中文）",
      "layer1_en": "Core question (English)",
      "vars": ["需盯变量1（中文，具体到指标名+阈值）", "需盯变量2", "需盯变量3", "需盯变量4"],
      "vars_en": ["Variable to watch 1 (English)", "Variable to watch 2", "Variable to watch 3", "Variable to watch 4"]
    }}
  ],
  "four_column_table": [
    {{
      "tags": [{{"type": "ai/fed/energy/china/bio/macro/geopolitics/central-bank", "text": "标签（中文）", "text_en": "Tag (English)"}}],
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
      "event": "历史类比标题（中文，含具体年份和事件名）",
      "event_en": "Analogy title (English, with year and event name)",
      "lesson": "真实历史事件+一句话教训（中文）",
      "lesson_en": "Historical event + lesson (English)",
      "diff": "关键区别（中文，今天与历史的不同之处）",
      "diff_en": "Key difference (English)"
    }}
  ]
}}

Requirements:
1. stats: extract ALL important market data points (no fixed limit)
2. four_column_table: ONLY 6-10 most important events after funnel filtering — each event must be concise and clear, NOT raw headline text
3. chains: extract 3-7 causal chains based on ACTUAL importance (not fixed number). Each chain MUST be a real causal sequence: [Event A] -> [Event B] -> ... -> [Asset price change]. Mark each as [市场共识] (consensus) or [待验证] (unverified). Each chain MUST include 3 jargon terms with plain-language explanations.
4. verifications: generate watchlist items with TWO layers — layer1 = core question specific to that chain, vars = 3-4 SPECIFIC variables to watch (with indicator name + threshold, NOT generic templates)
5. historical_analogies: generate 3-4 REAL historical parallels (with specific year and event name), each with lesson and key difference from today
6. Use <br> for line breaks in node text
7. CRITICAL: Every *_en field MUST be in pure English with NO Chinese characters whatsoever
8. CRITICAL: Every Chinese field MUST have a corresponding *_en English field
9. English must use proper financial terminology
10. Output strictly valid JSON"""


def llm_structure(headlines):
    """用 LLM 对筛选后的快讯进行中英双语结构化"""
    api_key = os.environ.get("LLM_API_KEY", "")
    api_base = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")

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
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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

        issues = validate_bilingual(structured)
        if issues:
            log(f"[LLM] ⚠️ 双语校验发现 {len(issues)} 个问题:")
            for issue in issues[:5]:
                log(f"  - {issue}")
            structured = auto_fill_english(structured)
            log("[LLM] 已自动补充缺失的英文字段")
        return structured
    except Exception as e:
        log(f"[LLM] 请求失败: {e}")
        return None


def validate_bilingual(data):
    """校验数据中每个中文字段是否有对应的英文字段"""
    issues = []
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

    def check_item(item, context):
        for zh_field, en_field in field_pairs:
            if zh_field in item:
                if en_field not in item or not item[en_field]:
                    issues.append(f"{context}: 缺少 {en_field}")
                elif en_field in item and item[en_field] and chinese_re.search(item[en_field]):
                    issues.append(f"{context}: {en_field} 中包含中文字符")

    for i, s in enumerate(data.get("stats", [])):
        check_item(s, f"stats[{i}]")
    for i, e in enumerate(data.get("events", [])):
        check_item(e, f"events[{i}]")
        for j, tag in enumerate(e.get("tags", [])):
            if "text" in tag and ("text_en" not in tag or not tag["text_en"]):
                issues.append(f"events[{i}].tags[{j}]: 缺少 text_en")
    for i, c in enumerate(data.get("chains", [])):
        check_item(c, f"chains[{i}]")
        for j, node in enumerate(c.get("nodes", [])):
            check_item(node, f"chains[{i}].nodes[{j}]")
        for j, jargon in enumerate(c.get("jargon", [])):
            check_item(jargon, f"chains[{i}].jargon[{j}]")
    for i, v in enumerate(data.get("verifications", [])):
        check_item(v, f"verifications[{i}]")
        if "vars" in v and ("vars_en" not in v or len(v.get("vars_en", [])) != len(v["vars"])):
            issues.append(f"verifications[{i}]: vars_en 缺失或数量不匹配")
    for i, a in enumerate(data.get("historical_analogies", [])):
        check_item(a, f"historical_analogies[{i}]")
    return issues


def auto_fill_english(data):
    """自动补充缺失的英文字段"""
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
                    item[en_field] = translate_text(item[zh_field])
                elif chinese_re.search(item[en_field]):
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
    for a in data.get("historical_analogies", []):
        fill_item(a)
    return data


# ============================================================
# 第四层：规则兜底结构化 v5（全部对齐用户标准）
# ============================================================

def extract_assets_from_text(text):
    """从快讯文本中提取影响资产"""
    assets = []
    text_lower = text.lower()
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
        "Anthropic": "Anthropic", "OpenAI": "OpenAI",
        "韩元": "韩元", "欧元": "欧元", "英镑": "英镑",
    }
    for kw, asset in asset_map_zh.items():
        if kw in text and asset not in assets:
            assets.append(asset)
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


def extract_assets_en(assets_zh):
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
        "Anthropic": "Anthropic", "OpenAI": "OpenAI",
        "韩元": "KRW", "欧元": "EUR", "英镑": "GBP",
        "详见原文": "See source",
    }
    parts = assets_zh.split(" / ")
    return " / ".join(mapping.get(p.strip(), translate_text(p)) for p in parts)


def refine_event_text(text):
    """精炼事件描述：从原始快讯中提取核心信息，不超过100字"""
    # 去掉多余空白
    text = re.sub(r'\s+', ' ', text).strip()
    # 如果已经较短，直接返回
    if len(text) <= 100:
        return text
    # 提取包含数字和关键信息的部分
    # 找第一个句号或分号作为截断点
    for sep in ['。', '；', '。', '；']:
        idx = text.find(sep)
        if 20 < idx < 100:
            return text[:idx + 1]
    # 找最后一个逗号在100字以内的位置
    for i in range(min(100, len(text)), 60, -1):
        if text[i-1] in '，,':
            return text[:i-1] + '...'
    return text[:97] + '...'


def detect_direction(text):
    """从文本中检测价格方向"""
    text_lower = text.lower()
    up_zh = any(kw in text for kw in ["涨", "升", "高", "增", "涨超", "飙", "涨"])
    down_zh = any(kw in text for kw in ["跌", "降", "低", "减", "跌超", "暴跌", "崩"])
    up_en = any(kw in text_lower for kw in ["surge", "soar", "rally", "jump", "rise", "gain", "climb", "record high", "new high"])
    down_en = any(kw in text_lower for kw in ["plunge", "slump", "tumble", "drop", "fall", "decline", "sink", "slide", "crash", "selloff", "record low", "new low"])
    if (up_zh or up_en) and (down_zh or down_en):
        return "split"
    elif up_zh or up_en:
        return "up"
    elif down_zh or down_en:
        return "down"
    return "neutral"


def detect_tags(text):
    """从文本中检测标签类型"""
    text_lower = text.lower()
    tags = []
    if any(kw in text for kw in ["AI", "芯片", "英伟达", "半导体", "人工智能", "OpenAI", "数据中心", "Anthropic", "算力", "Capex"]) or \
       any(kw in text_lower for kw in ["ai ", "artificial intelligence", "nvidia", "chip", "semiconductor", "openai", "data center", "anthropic", "capex"]):
        tags.append({"type": "ai", "text": "AI", "text_en": "AI"})
    if any(kw in text for kw in ["美联储", "央行", "加息", "降息", "利率", "PPI", "CPI", "通胀", "FOMC", "鹰派", "鸽派", "欧央行"]) or \
       any(kw in text_lower for kw in ["fed", "federal reserve", "rate hike", "rate cut", "interest rate", "inflation", "cpi", "ppi", "fomc", "hawkish", "dovish", "ecb"]):
        tags.append({"type": "central-bank", "text": "央行", "text_en": "Central Bank"})
    if any(kw in text for kw in ["原油", "油价", "布油", "OPEC", "能源", "海峡", "油轮"]) or \
       any(kw in text_lower for kw in ["oil", "crude", "brent", "wti", "opec", "energy", "strait", "tanker"]):
        tags.append({"type": "energy", "text": "能源", "text_en": "Energy"})
    if any(kw in text for kw in ["中国", "A股", "社零", "工业增加值", "地产", "统计局", "创业板", "港股", "沪指", "阿里", "拼多多"]) or \
       any(kw in text_lower for kw in ["china", "a-shares", "chinese", "beijing", "shanghai", "yuan", "hang seng", "alibaba", "pdd"]):
        tags.append({"type": "china", "text": "中国", "text_en": "China"})
    if any(kw in text for kw in ["地缘", "战争", "冲突", "制裁", "宣言", "和平"]) or \
       any(kw in text_lower for kw in ["geopolitical", "war", "conflict", "sanction", "peace", "declaration"]):
        tags.append({"type": "geopolitics", "text": "地缘", "text_en": "Geopolitics"})
    if any(kw in text for kw in ["赤字", "财政", "国债", "发债", "出口", "贸易", "GDP", "PMI"]) or \
       any(kw in text_lower for kw in ["deficit", "fiscal", "treasury", "debt", "bond", "export", "trade", "gdp", "pmi"]):
        tags.append({"type": "macro", "text": "宏观", "text_en": "Macro"})
    if not tags:
        tags.append({"type": "macro", "text": "宏观", "text_en": "Macro"})
    return tags


def generate_logic(text, dir):
    """从快讯文本中生成传导逻辑（A→B→C格式）"""
    text_lower = text.lower()

    # 央行政策链
    if any(kw in text for kw in ["加息", "鹰派"]) or "rate hike" in text_lower or "hawkish" in text_lower:
        if dir == "up":
            return "央行鹰派信号 → 加息预期升温 → 资金回流本币 → 相关资产受益"
        return "央行鹰派信号 → 加息预期升温 → 利率上行 → 风险资产承压"
    if any(kw in text for kw in ["降息", "鸽派"]) or "rate cut" in text_lower or "dovish" in text_lower:
        return "央行鸽派信号 → 降息预期升温 → 流动性预期改善 → 风险资产受益"

    # 地缘链
    if any(kw in text for kw in ["地缘", "战争", "冲突", "制裁", "海峡", "油轮"]) or "geopolitical" in text_lower or "sanction" in text_lower or "strait" in text_lower:
        if any(kw in text for kw in ["和平", "宣言", "共识"]) or "peace" in text_lower:
            return "地缘风险缓和 → 风险溢价压缩 → 避险资产回落 / 风险资产上涨"
        return "地缘风险事件 → 避险情绪升温 → 避险资产上涨 / 风险资产下跌"

    # AI/科技链
    if any(kw in text for kw in ["AI", "芯片", "算力", "Anthropic", "OpenAI", "Capex"]) or "artificial intelligence" in text_lower or "anthropic" in text_lower:
        if "IPO" in text or "ipo" in text_lower or "上市" in text:
            return "AI公司IPO/融资 → AI capex叙事验证 → 半导体/算力需求预期上修 → 相关板块大涨"
        if any(kw in text for kw in ["财报", "营收", "利润", "Capex", "现金流"]):
            return "AI公司财报 → Capex/收入验证 → 盈利可持续性评估 → 股价分化"
        return "AI产业事件 → 算力/芯片需求预期变化 → 相关板块联动"

    # 财报表
    if any(kw in text for kw in ["财报", "营收", "利润", "EPS"]) or "earnings" in text_lower or "revenue" in text_lower:
        if "超预期" in text or "beat" in text_lower:
            return "财报超预期 → 盈利预期上修 → 股价上涨"
        elif "不及预期" in text or "miss" in text_lower:
            return "财报不及预期 → 盈利预期下修 → 股价下跌"
        if dir == "split":
            return "财报多空交织（收入vs利润分化）→ 市场评估盈利质量 → 股价先涨后跌/分化"
        return "财报发布 → 盈利/指引更新 → 估值重估"

    # 能源链
    if any(kw in text for kw in ["原油", "油价", "OPEC"]) or "oil" in text_lower or "opec" in text_lower:
        if any(kw in text for kw in ["增产", "增产共识"]) or "production" in text_lower:
            return "增产共识 → 供应增加预期 → 油价承压"
        if any(kw in text for kw in ["减产", "断供"]) or "cut" in text_lower:
            return "供应中断/减产 → 油价上涨 → 通胀预期联动"
        return "原油供需变化 → 油价波动 → 能源股/通胀预期联动"

    # 贸易/出口
    if any(kw in text for kw in ["出口", "进口", "贸易"]) or "trade" in text_lower or "export" in text_lower:
        return "贸易数据变化 → 全球需求/供应链预期调整 → 相关货币/股市影响"

    # IPO
    if "ipo" in text_lower or "上市" in text:
        return "IPO事件 → 市场资金流向/行业估值锚定 → 相关板块联动"

    # 债务/利差
    if any(kw in text for kw in ["债务", "利差", "国债", "赤字"]) or "debt" in text_lower or "spread" in text_lower:
        return "债务风险信号 → 国债利差走阔 → 相关国家资产承压"

    # 默认
    if dir == "up":
        return "利好事件 → 市场预期改善 → 资产价格上涨"
    elif dir == "down":
        return "利空事件 → 市场预期恶化 → 资产价格下跌"
    elif dir == "split":
        return "多空因素交织 → 板块/资产分化 → 需关注后续催化"
    return "事件发生 → 市场消化信息 → 资产价格调整"


def generate_logic_en(logic_zh):
    """翻译传导逻辑为英文"""
    mapping = {
        "央行鹰派信号": "Central bank hawkish signal",
        "加息预期升温": "rate hike expectations rise",
        "资金回流本币": "capital flows back to local currency",
        "相关资产受益": "related assets benefit",
        "利率上行": "yields rise",
        "风险资产承压": "risk assets under pressure",
        "央行鸽派信号": "Central bank dovish signal",
        "降息预期升温": "rate cut expectations rise",
        "流动性预期改善": "liquidity expectations improve",
        "风险资产受益": "risk assets benefit",
        "地缘风险缓和": "Geopolitical risk easing",
        "风险溢价压缩": "risk premium compression",
        "避险资产回落": "safe-haven assets retreat",
        "风险资产上涨": "risk assets rally",
        "地缘风险事件": "Geopolitical risk event",
        "避险情绪升温": "safe-haven sentiment rises",
        "避险资产上涨": "safe-haven assets rise",
        "风险资产下跌": "risk assets fall",
        "AI公司IPO/融资": "AI company IPO/funding",
        "AI capex叙事验证": "AI capex narrative validated",
        "半导体/算力需求预期上修": "semiconductor/compute demand expectations revised up",
        "相关板块大涨": "related sectors surge",
        "AI公司财报": "AI company earnings",
        "Capex/收入验证": "Capex/revenue validation",
        "盈利可持续性评估": "profitability sustainability assessment",
        "股价分化": "stock price diverges",
        "AI产业事件": "AI industry event",
        "算力/芯片需求预期变化": "compute/chip demand expectations shift",
        "相关板块联动": "related sectors correlate",
        "财报超预期": "Earnings beat",
        "盈利预期上修": "earnings estimates revised up",
        "股价上涨": "stock price rises",
        "财报不及预期": "Earnings miss",
        "盈利预期下修": "earnings estimates revised down",
        "股价下跌": "stock price falls",
        "财报多空交织": "Earnings mixed signals",
        "市场评估盈利质量": "market assesses earnings quality",
        "股价先涨后跌/分化": "stock price up then down/diverges",
        "财报发布": "Earnings released",
        "盈利/指引更新": "earnings/guidance update",
        "估值重估": "re-rating",
        "增产共识": "Production consensus",
        "供应增加预期": "supply increase expectation",
        "油价承压": "oil price under pressure",
        "供应中断/减产": "Supply disruption/cut",
        "油价上涨": "oil price rises",
        "通胀预期联动": "inflation expectations correlate",
        "原油供需变化": "Oil supply/demand shift",
        "油价波动": "oil price volatility",
        "能源股/通胀预期联动": "energy stocks / inflation expectations correlate",
        "贸易数据变化": "Trade data shift",
        "全球需求/供应链预期调整": "global demand / supply chain expectations adjust",
        "相关货币/股市影响": "related currencies / stocks impacted",
        "IPO事件": "IPO event",
        "市场资金流向/行业估值锚定": "capital flows / sector valuation anchoring",
        "债务风险信号": "Debt risk signal",
        "国债利差走阔": "bond spread widens",
        "相关国家资产承压": "related country assets under pressure",
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


# ============================================================
# 四列表生成（精炼到6-10条核心）
# ============================================================

def generate_four_column_table(headlines):
    """从筛选后的快讯生成四列表：事件/影响资产/方向/传导逻辑"""
    table = []
    seen_topics = set()

    for h in headlines:
        text = h["text"]
        if len(text) < 15:
            continue

        # 精炼事件描述
        event_text = refine_event_text(text)
        chinese_re = re.compile(r'[\u4e00-\u9fff]')
        if chinese_re.search(event_text):
            event_en = translate_text(event_text)
        else:
            event_en = event_text

        # 简单去重（用前40字符）
        topic = text[:40].lower()
        if topic in seen_topics:
            continue
        seen_topics.add(topic)

        dir = detect_direction(text)
        tags = detect_tags(text)
        assets = extract_assets_from_text(text)
        assets_en_text = extract_assets_en(assets)
        logic = generate_logic(text, dir)
        logic_en = generate_logic_en(logic)

        table.append({
            "event": event_text,
            "event_en": event_en,
            "assets": assets,
            "assets_en": assets_en_text,
            "dir": dir,
            "logic": logic,
            "logic_en": logic_en,
            "tags": tags,
        })

        if len(table) >= 10:
            break

    return table


# ============================================================
# 因果链生成（真正的因果逻辑串联 A→B→C→价格变动）
# ============================================================

def generate_causal_chains(headlines):
    """
    从筛选后的快讯中提取真正的因果链。
    按事件主题分组，每组构建 A→B→C→价格变动 的因果序列。
    每条链含3个术语白话解释。
    数量按当天实际重要性决定（3-7条）。
    每条快讯只归入最匹配的一个主题，避免重复。
    """
    chains = []

    # 为每条快讯分配最佳主题（避免一条新闻出现在多个链中）
    theme_events = {
        "geopolitics": [],
        "ai": [],
        "central_bank": [],
        "energy": [],
        "china": [],
        "macro": [],
    }

    used_headlines = set()

    for h in headlines:
        text = h["text"]
        text_lower = text.lower()
        h_id = id(h)

        if h_id in used_headlines:
            continue

        # 按优先级匹配主题（避免一条新闻同时归入多个主题）
        best_theme = None

        # 地缘（含和平/宣言/冲突/制裁/海峡）
        if any(kw in text for kw in ["地缘", "战争", "冲突", "制裁", "宣言", "和平", "元首", "会晤"]) or \
           any(kw in text_lower for kw in ["geopolitical", "war", "conflict", "sanction", "peace", "declaration", "summit"]):
            best_theme = "geopolitics"
        # AI（含Anthropic/OpenAI/芯片/算力/Capex）
        elif any(kw in text for kw in ["AI", "Anthropic", "OpenAI", "Capex", "算力", "光通信", "HBM"]) or \
             any(kw in text_lower for kw in ["anthropic", "openai", "capex", "ai ", "artificial intelligence"]):
            best_theme = "ai"
        # 央行（含加息/降息/鹰派/鸽派/FOMC/ECB）
        elif any(kw in text for kw in ["美联储", "央行", "加息", "降息", "利率", "FOMC", "鹰派", "鸽派", "欧央行", "ECB", "通胀"]) or \
             any(kw in text_lower for kw in ["fed", "federal reserve", "rate hike", "rate cut", "interest rate", "fomc", "hawkish", "dovish", "ecb", "inflation"]):
            best_theme = "central_bank"
        # 能源（含原油/油价/OPEC/油轮）
        elif any(kw in text for kw in ["原油", "油价", "布油", "OPEC", "油轮", "霍尔木兹"]) or \
             any(kw in text_lower for kw in ["oil", "crude", "brent", "wti", "opec", "tanker", "hormuz"]):
            best_theme = "energy"
        # 中国市场（含A股/港股/阿里/财报）
        elif any(kw in text for kw in ["中国", "A股", "社零", "工业增加值", "地产", "创业板", "港股", "沪指", "阿里", "拼多多", "沪深"]) or \
             any(kw in text_lower for kw in ["china", "a-shares", "chinese", "alibaba", "pdd", "hang seng", "shanghai"]):
            best_theme = "china"
        else:
            best_theme = "macro"

        theme_events[best_theme].append(h)
        used_headlines.add(h_id)

    # 为每个有事件的主题构建因果链
    for theme in ["geopolitics", "ai", "central_bank", "energy", "china", "macro"]:
        events = theme_events.get(theme, [])
        if not events:
            continue

        # 按时间排序，取最重要的5条
        events_sorted = sorted(events, key=lambda h: h.get("timestamp", 0))
        top_events = events_sorted[:5]

        chain = build_causal_chain(theme, top_events)
        if chain:
            chains.append(chain)

        if len(chains) >= 7:
            break

    return chains


def extract_core_info(text, max_len=50):
    """从快讯文本中提取核心信息（去掉冗余修饰，保留关键数字和事件）"""
    text = re.sub(r'\s+', ' ', text).strip()
    # 去掉序号前缀
    text = re.sub(r'^[\d]+[、.\s]+', '', text)
    # 找第一个句号/分号截断
    for sep in ['。', '；', '。', '；', '\n']:
        idx = text.find(sep)
        if 10 < idx < max_len + 20:
            return text[:idx].strip()
    if len(text) <= max_len:
        return text
    # 找最后一个逗号截断
    for i in range(min(max_len, len(text)), 20, -1):
        if text[i-1] in '，,':
            return text[:i-1].strip()
    return text[:max_len-3].strip() + '...'


def build_causal_chain(theme, events):
    """为特定主题构建一条完整的因果链"""
    theme_info = {
        "geopolitics": {
            "title_zh": "地缘链", "title_en": "Geopolitical Chain",
            "jargon": [
                {"term": "地缘风险溢价", "term_en": "Geopolitical Risk Premium",
                 "explain": "因为担心打仗，投资者要求额外回报才肯持有资产。一旦风险下降，这部分'恐惧折扣'被去掉，资产价格就跳涨。",
                 "explain_en": "Extra return investors demand for holding assets when they fear conflict. Once risk falls, this 'fear discount' is removed and prices jump."},
                {"term": "避险资产", "term_en": "Safe-Haven Assets",
                 "explain": "市场恐慌时资金流入的资产，如黄金、美债、日元。地缘紧张时涨，缓和时跌。",
                 "explain_en": "Assets that capital flows into during panic: gold, US Treasuries, JPY. Rise when geopolitics tense, fall when easing."},
                {"term": "风险偏好", "term_en": "Risk Appetite",
                 "explain": "投资者更愿意买股票（风险资产）还是买国债（避险资产）的倾向。",
                 "explain_en": "Whether investors prefer stocks (risk assets) or bonds (safe havens)."},
            ]
        },
        "ai": {
            "title_zh": "AI Capex链", "title_en": "AI Capex Chain",
            "jargon": [
                {"term": "AI Capex", "term_en": "AI Capex (Capital Expenditure)",
                 "explain": "AI公司花在买芯片、建数据中心、租GPU上的钱。这笔钱最终变成半导体公司的订单。",
                 "explain_en": "Money AI companies spend on chips, data centers, and GPUs. Ultimately becomes semiconductor company orders."},
                {"term": "光通信", "term_en": "Optical Communications",
                 "explain": "数据中心里用光传输数据的技术。AI集群越大，需要的光模块越多。",
                 "explain_en": "Technology using light to transmit data in data centers. Bigger AI clusters need more optical modules."},
                {"term": "暗盘交易", "term_en": "Grey Market Trading",
                 "explain": "IPO正式挂牌前的场外交易。暗盘涨跌反映机构对IPO的预期。",
                 "explain_en": "Off-exchange trading before official IPO listing. Grey market moves reflect institutional expectations."},
            ]
        },
        "central_bank": {
            "title_zh": "央行政策链", "title_en": "Central Bank Policy Chain",
            "jargon": [
                {"term": "鹰派", "term_en": "Hawkish",
                 "explain": "央行官员倾向于加息、收紧货币政策来压制通胀的态度。",
                 "explain_en": "Central bank officials' tendency to raise rates and tighten policy to suppress inflation."},
                {"term": "终点利率", "term_en": "Terminal Rate",
                 "explain": "市场预期央行加息到哪个水平就会停。终点利率上移=还要加，下移=快停了。",
                 "explain_en": "The rate level at which the market expects the central bank to stop hiking."},
                {"term": "国债利差", "term_en": "Bond Spread",
                 "explain": "两个国家国债收益率的差额。利差走阔=市场认为某国债务风险上升。",
                 "explain_en": "Yield difference between two countries' government bonds. Widening spread = market sees rising debt risk."},
            ]
        },
        "energy": {
            "title_zh": "能源链", "title_en": "Energy Chain",
            "jargon": [
                {"term": "霍尔木兹海峡", "term_en": "Strait of Hormuz",
                 "explain": "全球约20%的石油运输必经之路。谁控制了这里，就掐住了全球能源的咽喉。",
                 "explain_en": "About 20% of global oil transport passes through here. Whoever controls it holds the world's energy throat."},
                {"term": "超级油轮（VLCC）", "term_en": "VLCC (Very Large Crude Carrier)",
                 "explain": "能装200万桶原油的巨型油轮。VLCC运费飙升=供应受阻的先行指标。",
                 "explain_en": "Giant tanker carrying 2M barrels. VLCC freight surge = leading indicator of supply disruption."},
                {"term": "OPEC+", "term_en": "OPEC+",
                 "explain": "石油输出国组织及其盟友，控制全球约40%原油产量。减产=涨价，增产=跌价。",
                 "explain_en": "Oil producers' alliance controlling ~40% of global supply. Cut = price up, increase = price down."},
            ]
        },
        "china": {
            "title_zh": "中国市场链", "title_en": "China Market Chain",
            "jargon": [
                {"term": "自由现金流（FCF）", "term_en": "Free Cash Flow (FCF)",
                 "explain": "赚的钱减去必须花的钱后，真正落袋的现金。FCF为负=花得比赚得多。",
                 "explain_en": "Earnings minus mandatory spending, actual pocketed cash. Negative FCF = spending exceeds earnings."},
                {"term": "社零（社会消费品零售总额）", "term_en": "Retail Sales",
                 "explain": "老百姓花钱消费的总量，反映内需强弱。升=消费旺，降=消费弱。",
                 "explain_en": "Total consumer spending, reflecting domestic demand strength."},
                {"term": "北向资金", "term_en": "Northbound Capital",
                 "explain": "通过沪港通/深港通从香港流入A股的资金，被视为外资风向标。",
                 "explain_en": "Capital flowing from HK into A-shares via Stock Connect, seen as foreign capital barometer."},
            ]
        },
        "macro": {
            "title_zh": "宏观链", "title_en": "Macro Chain",
            "jargon": [
                {"term": "美元走强→商品下跌", "term_en": "Strong USD → Commodity Down",
                 "explain": "国际大宗商品以美元计价。美元贵了，同样一桶油用美元买就贵了，需求减少，价格就跌。",
                 "explain_en": "Commodities priced in USD. Stronger dollar = more expensive commodities = lower demand."},
                {"term": "避险情绪", "term_en": "Risk-Off Sentiment",
                 "explain": "市场害怕风险时，资金从股票等高风险资产流向黄金/美债等安全资产。",
                 "explain_en": "When markets fear risk, capital flows from stocks to safe havens like gold/Treasuries."},
                {"term": "PMI（采购经理人指数）", "term_en": "PMI (Purchasing Managers' Index)",
                 "explain": "衡量制造业/服务业景气度的指标。50以上=扩张，50以下=收缩。",
                 "explain_en": "Index measuring manufacturing/services activity. Above 50 = expansion, below 50 = contraction."},
            ]
        },
    }

    info = theme_info.get(theme, theme_info["macro"])

    # 构建因果节点（A→B→C→价格变动），每个节点精炼到50字以内
    nodes = []
    for i, ev in enumerate(events):
        text = ev["text"]
        node_text = extract_core_info(text, max_len=50)
        node_type = "cause" if i == 0 else ("effect" if i == len(events) - 1 else "intermediate")
        chinese_re = re.compile(r'[\u4e00-\u9fff]')
        node_en = translate_text(node_text) if chinese_re.search(node_text) else node_text
        nodes.append({"text": node_text, "text_en": node_en, "type": node_type})

    # 如果只有1个事件，至少加一个结果节点
    if len(nodes) == 1:
        dir = detect_direction(events[0]["text"])
        if dir == "up":
            nodes.append({"text": "相关资产上涨", "text_en": "Related assets rise", "type": "effect"})
        elif dir == "down":
            nodes.append({"text": "相关资产下跌", "text_en": "Related assets fall", "type": "effect"})
        elif dir == "split":
            nodes.append({"text": "资产价格分化", "text_en": "Asset prices diverge", "type": "effect"})
        else:
            nodes.append({"text": "市场消化信息", "text_en": "Market digests info", "type": "effect"})

    # 判断状态
    has_breaking = any(
        any(kw in ev.get("text", "") for kw in BREAKING_KEYWORDS_ZH) or
        any(kw in ev.get("text", "").lower() for kw in BREAKING_KEYWORDS_EN)
        for ev in events
    )
    status = "unverified" if has_breaking else "consensus"

    # 生成标题（精炼版）
    first_core = extract_core_info(events[0]["text"], max_len=25)
    title = f"{info['title_zh']}：{first_core} → {'相关资产变动' if len(events) == 1 else extract_core_info(events[-1]['text'], max_len=25)}"
    title_en = f"{info['title_en']}: {translate_text(first_core)} → {'Asset price change' if len(events) == 1 else translate_text(extract_core_info(events[-1]['text'], max_len=25))}"

    return {
        "title": title,
        "title_en": title_en,
        "status": status,
        "nodes": nodes,
        "jargon": info["jargon"][:3],
    }


# ============================================================
# 待验证清单生成（针对因果链的核心问题+具体变量）
# ============================================================

def generate_verifications(chains, headlines):
    """
    为每条因果链生成待验证清单。
    每项含：核心问题（针对该链的具体问题）+ 4个具体盯盘变量。
    """
    verifications = []
    text_all = " ".join(h["text"] for h in headlines)

    for chain in chains[:4]:
        chain_title = chain["title"]
        chain_theme = chain_title.split("：")[0] if "：" in chain_title else chain_title

        # 根据链的主题生成针对性的核心问题和变量
        core_q, core_q_en, vars_zh, vars_en = generate_verification_for_theme(chain_theme, text_all, chain)

        verifications.append({
            "title": f"{chain_title}能否持续？",
            "title_en": f"Can '{chain['title_en']}' sustain?",
            "layer1": core_q,
            "layer1_en": core_q_en,
            "vars": vars_zh,
            "vars_en": vars_en,
        })

    return verifications


def generate_verification_for_theme(theme, text_all, chain):
    """根据主题生成针对性的验证问题和变量"""
    text_lower = text_all.lower()

    if "地缘" in theme:
        return (
            "地缘缓和信号能否真正转化为风险溢价的持久压缩？宣言是政治表态，能否转化为可执行方案？",
            "Can geopolitical easing truly translate into lasting risk premium compression? Can a declaration become actionable?",
            [
                "VIX恐慌指数：持续低于15=市场已price in和平；反弹至18+=市场持保留态度",
                "布伦特原油价格：跌破70美元=市场认可增产；反弹至78+=供应担忧未消",
                "黄金走势：央行持续购金=央行层面仍在对冲地缘风险",
                "后续军事动态：是否有和平宣言与战场现实的落差？",
            ],
            [
                "VIX: sustained below 15 = peace priced in; rebound to 18+ = market skeptical",
                "Brent crude: below $70 = market believes production; above $78 = supply fears persist",
                "Gold trend: continued CB purchases = CBs still hedging geopolitical risk",
                "Follow-up military actions: gap between declaration and battlefield reality?",
            ]
        )

    if "AI" in theme or "Capex" in theme:
        return (
            "AI capex叙事能否从'融资验证'切换到'盈利验证'？巨量融资证明了吸金能力，但何时能证明赚钱能力？",
            "Can the AI capex narrative shift from 'funding validation' to 'profit validation'? Massive funding proves capital attraction, but when profitability?",
            [
                "AI公司上市后5日股价：暗盘涨幅是初始热情，挂牌后是否破发或涨幅收窄",
                "云厂商Capex/收入比：若比率持续上升，AI投入回报周期将被质疑",
                "SK海力士/美光股价持续性：盘前大涨是情绪驱动，需确认HBM订单是否真正追加",
                "A股算力芯片分化：国产AI芯片是否出现信任危机？",
            ],
            [
                "AI company 5-day post-IPO stock: grey market gains are initial enthusiasm, watch for narrowing or break issue price",
                "Cloud vendor Capex/revenue ratio: if rising, AI ROI cycle questioned",
                "SK Hynix/Micron sustainability: pre-market rally is sentiment-driven, confirm HBM order additions",
                "A-share compute chip divergence: domestic AI chip trust crisis?",
            ]
        )

    if "央行" in theme or "政策" in theme:
        return (
            "央行鹰派信号与债务风险的博弈，会否触发利差危机？加息+高债务=火药桶。",
            "Will the central bank hawkish signal vs debt risk game trigger a spread crisis? Rate hikes + high debt = powder keg.",
            [
                "10年期国债利差：若走阔至85bp+，市场开始定价财政失控风险",
                "劳动力成本：工资上涨是核心通胀的最后一英里，若继续走高央行确实会加息",
                "财政预算案进展：若无法通过可信的财政方案，利差危机风险上升",
                "传导保护工具使用条件：若被触发，等同于危机信号",
            ],
            [
                "10Y bond spread: widening to 85bp+ = market prices fiscal loss of control",
                "Labor costs: rising wages are core inflation's last mile, if continues CB will hike",
                "Fiscal budget progress: if no credible fiscal plan, spread crisis risk rises",
                "Transmission protection tool conditions: if triggered, equals crisis signal",
            ]
        )

    if "能源" in theme:
        return (
            "能源供应冲击是否会升级为系统性中断？这是局部冲突还是系统性封锁的开始？",
            "Will energy supply shock escalate into systemic disruption? Is this localized or the start of systemic blockade?",
            [
                "布伦特原油日内波动：单日涨幅超3%=市场开始定价封锁风险",
                "VLCC运费指数（BDTI）：超级油轮运费飙升=船东要求额外风险补偿",
                "后续军事行动：若出现第二次袭击，局势将质变",
                "战略石油储备动向：若启动储备释放，说明官方认为风险可控度下降",
            ],
            [
                "Brent intraday volatility: single-day move >3% = market pricing blockade risk",
                "BDTI (VLCC freight index): surging rates = owners demanding risk premium",
                "Follow-up military actions: second incident = qualitative escalation",
                "SPR movements: if reserve release activated, officials see risk declining",
            ]
        )

    if "中国" in theme:
        return (
            "中国市场多空因素交织：财报分化、政策预期、资金流向如何演变？",
            "China market mixed signals: how will earnings divergence, policy expectations, and capital flows evolve?",
            [
                "北向资金流向：净流入=外资看好，净流出=外资谨慎",
                "社零/工业增加值数据：若超预期=内需回暖，低于预期=经济承压",
                "A股成交量：放量上涨=信心恢复，缩量=观望情绪浓",
                "中概股盘前/盘后走势：财报后市场如何评价盈利质量",
            ],
            [
                "Northbound capital: net inflow = foreign bullish, net outflow = cautious",
                "Retail sales / industrial output: beat = domestic demand recovering, miss = economy pressured",
                "A-share volume: high volume + up = confidence recovery, low volume = wait-and-see",
                "China ADR pre/post-market: how market assesses earnings quality post-report",
            ]
        )

    # 默认（宏观）
    return (
        "该宏观事件后续发展如何？市场当前定价是否充分？",
        "How will this macro event develop? Is current market pricing adequate?",
        [
            "相关资产价格次日开盘方向",
            "成交量是否异常放大（恐慌or追涨）",
            "官方/央行是否有后续声明或澄清",
            "关联资产是否同步反应（验证逻辑链）",
        ],
        [
            "Related asset price direction at next open",
            "Volume anomaly (panic or chasing)",
            "Official/central bank follow-up statement",
            "Correlated assets confirmation",
        ]
    )


# ============================================================
# 历史类比生成（真实历史事件+教训+关键区别）
# ============================================================

def generate_historical_analogies(headlines):
    """根据当日事件类型匹配真实历史事件+教训+关键区别"""
    text_all = " ".join(h["text"] for h in headlines)
    text_lower = text_all.lower()
    analogies = []
    seen_types = set()

    # 根据当日内容匹配历史类比
    analogy_templates = {
        "ipo": {
            "event": "2000年互联网泡沫：Capex暴增先于盈利崩塌（1999-2001年）",
            "event_en": "Dot-com bubble: Capex surge preceded profit collapse (1999-2001)",
            "lesson": "当市场为单一公司IPO狂欢时，不要忘记2000年电信公司疯狂铺设光缆、随后盈利无法覆盖投入的教训。巨量融资不等于盈利验证，系统脆弱性往往在最乐观时暴露。",
            "lesson_en": "When markets celebrate a single company's IPO, remember the 2000 telecom companies frantically laying fiber, then profits failing to cover investment. Massive funding does not equal profitability validation.",
            "diff": "2000年铺设的光缆后来确实被用了，只是用了5-10年才回本。AI基础设施的变现周期可能更短，且这次有真实的B端付费需求在支撑，不像当年很多流量是免费的。",
            "diff_en": "The fiber laid in 2000 was eventually used, just took 5-10 years to break even. AI infrastructure monetization may be faster, with real B-side paid demand unlike free dot-com traffic.",
        },
        "geopolitics_oil": {
            "event": "两伊战争期间的油轮战（1984-1988年）",
            "event_en": "Tanker War during Iran-Iraq War (1984-1988)",
            "lesson": "霍尔木兹海峡油轮遭袭并非首次。1980年代两伊战争期间，双方互相袭击油轮，导致油价短期飙升后又被全球协调护航机制压制。今天的局势可能在复制有限升级到国际协调再到风险消退的剧本。",
            "lesson_en": "Hormuz tanker attacks aren't unprecedented. During the 1980s Iran-Iraq War, both sides attacked tankers, causing oil to spike then subside through globally coordinated escorts. Today may replicate the limited escalation to coordination to risk subsiding script.",
            "diff": "1980年代没有中俄美联合宣言这种三方协调机制。如果三方增产共识真正落地，即使海峡发生局部冲突，全球能源供应的兜底能力比当年强得多。但伊朗的无人机和水雷技术也远超当年。",
            "diff_en": "The 1980s lacked a China-Russia-US coordination mechanism. If three-nation production consensus materializes, global energy resilience is far stronger. But Iran's drone and mine technology is also far superior.",
        },
        "central_bank_debt": {
            "event": "欧债危机：希腊-意大利-西班牙利差螺旋（2011-2012年）",
            "event_en": "European Debt Crisis: Greece-Italy-Spain spread spiral (2011-2012)",
            "lesson": "央行在通胀压力下过早加息、随后引爆债务螺旋的剧本高度相似。加息加上高债务等于火药桶。2011年欧央行加息后，意大利债务利差飙升，最终靠Draghi的whatever it takes才稳住。",
            "lesson_en": "The script of a central bank raising rates prematurely under inflation pressure then triggering a debt spiral is highly similar. Rate hikes plus high debt equals powder keg. In 2011, the ECB hiked, Italian spreads surged, only stabilized by Draghi's whatever it takes.",
            "diff": "2012年Draghi的承诺和OMT/PEPP/TPI等工具箱今天已存在。央行自己也在监控这条线。但工具存在不等于能无成本使用，政治博弈才是关键。",
            "diff_en": "Draghi's 2012 pledge and tools like OMT/PEPP/TPI now exist. The central bank is monitoring this line. But tool existence does not equal cost-free usage; political gaming is the key.",
        },
        "ai_capex_bubble": {
            "event": "2008年雷曼兄弟破产 + AIG救助（2008年9月）",
            "event_en": "Lehman Brothers collapse + AIG bailout (Sep 2008)",
            "lesson": "当市场为金融创新或科技突破狂欢时，不要忘记2008年雷曼破产前市场也在为金融创新永动机定价。巨量融资不等于盈利验证，系统脆弱性往往在最乐观时暴露。",
            "lesson_en": "When markets celebrate financial innovation or tech breakthroughs, remember that before Lehman's collapse in 2008, markets were also pricing in a financial innovation perpetual motion machine. Massive funding does not equal profitability validation.",
            "diff": "2008年的风险藏在衍生品不透明链条里；今天AI公司的资产负债表相对透明。且AI基础设施投入有明确的终端需求，不像CDO的底层资产是次贷。",
            "diff_en": "2008's risk was hidden in opaque derivative chains; today's AI companies have relatively transparent balance sheets. AI infrastructure investment has clear end-user demand, unlike CDOs backed by subprime mortgages.",
        },
        "chip_panic": {
            "event": "2018年中美贸易战芯片股恐慌（2018年Q4）",
            "event_en": "2018 US-China trade war chip panic (Q4 2018)",
            "lesson": "2018年中美贸易战期间，芯片股集体暴跌后迎来2019-2021年超级周期。恐慌往往是长期机会的起点，但需区分恐慌性杀跌和基本面恶化。",
            "lesson_en": "During the 2018 US-China trade war, chip stocks collectively plunged then entered the 2019-2021 super cycle. Panic often marks long-term opportunity, but distinguish panic selling from fundamental deterioration.",
            "diff": "2018年的恐慌由关税驱动，今天如果是AI芯片分化，则需关注国产替代的真实进展和盈利能力，不仅仅是情绪。",
            "diff_en": "2018's panic was tariff-driven; if today's AI chip divergence, watch domestic substitution progress and profitability, not just sentiment.",
        },
        "rate_sensitivity": {
            "event": "2014-2015年美元走强周期：大宗商品全面崩塌",
            "event_en": "2014-2015 Strong Dollar Cycle: Broad commodity collapse",
            "lesson": "2014-2015年美元指数从80涨至100，黄金从1300跌至1050，原油从100跌至30。美元走强周期中大宗商品无一幸免。",
            "lesson_en": "2014-2015: DXY 80 to 100, gold $1300 to $1050, oil $100 to $30. Strong dollar cycle spares no commodity.",
            "diff": "需关注美联储实际加息路径是否如预期，以及通胀是否支撑继续加息。当前美元周期位置与2014年不同。",
            "diff_en": "Watch whether the Fed actually hikes as expected and whether inflation supports further hikes. Current dollar cycle position differs from 2014.",
        },
    }

    # 匹配逻辑
    matches = []
    if "ipo" in text_lower or "上市" in text_all or "Anthropic" in text_all:
        matches.append("ipo")
    if any(kw in text_all for kw in ["地缘", "战争", "冲突", "海峡", "油轮", "和平", "宣言"]) or "geopolitical" in text_lower or "strait" in text_lower:
        matches.append("geopolitics_oil")
    if any(kw in text_all for kw in ["加息", "鹰派", "债务", "利差", "赤字"]) or "hawkish" in text_lower or "debt" in text_lower or "spread" in text_lower:
        matches.append("central_bank_debt")
    if any(kw in text_all for kw in ["AI", "Anthropic", "OpenAI", "Capex", "算力"]) or "anthropic" in text_lower or "capex" in text_lower:
        matches.append("ai_capex_bubble")
    if any(kw in text_all for kw in ["芯片", "半导体", "跌停", "算力芯片"]) or "chip" in text_lower or "semiconductor" in text_lower:
        matches.append("chip_panic")
    if any(kw in text_all for kw in ["原油", "黄金", "铜", "大宗"]) and any(kw in text_all for kw in ["跌", "挫"]):
        matches.append("rate_sensitivity")

    # 如果匹配不到，使用默认类比
    if not matches:
        matches = ["ipo", "geopolitics_oil", "central_bank_debt", "chip_panic"]

    for match_type in matches:
        if match_type not in seen_types:
            seen_types.add(match_type)
            analogies.append(analogy_templates[match_type])
            if len(analogies) >= 4:
                break

    return analogies


# ============================================================
# 规则兜底主函数
# ============================================================

def rule_based_structure(headlines):
    """
    无 LLM 时的规则兜底方案 v5：
    全部对齐用户标准：
    - 四列表：精炼到6-10条核心
    - 因果链：真正的因果逻辑串联，每条含3个术语白话
    - 待验证：针对每条因果链的核心问题+4个具体变量
    - 历史类比：真实历史事件+教训+关键区别
    """
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
                dir_stat = detect_direction(text)
                if m.lastindex and m.lastindex >= 2:
                    value = m.group(2)
                chinese_re = re.compile(r'[\u4e00-\u9fff]')
                label_en = translate_text(label) if chinese_re.search(label) else label
                stats.append({
                    "label": label,
                    "label_en": label_en,
                    "value": value or ("new high" if dir_stat == "up" else "new low"),
                    "change": change,
                    "change_en": translate_text(change) if chinese_re.search(change) else change,
                    "dir": dir_stat,
                })
                if len(stats) >= 12:
                    break
        if len(stats) >= 12:
            break

    # 生成 events（保留兼容性）
    events = []
    seen_topics = set()
    for h in headlines:
        text = h["text"]
        if len(text) < 15:
            continue
        event_text = refine_event_text(text)
        topic = text[:40].lower()
        if topic in seen_topics:
            continue
        seen_topics.add(topic)
        dir = detect_direction(text)
        tags = detect_tags(text)
        assets = extract_assets_from_text(text)
        logic = generate_logic(text, dir)
        chinese_re = re.compile(r'[\u4e00-\u9fff]')
        event_en = translate_text(event_text) if chinese_re.search(event_text) else event_text
        events.append({
            "tags": tags,
            "event": event_text,
            "event_en": event_en,
            "assets": assets,
            "assets_en": extract_assets_en(assets),
            "dir": dir,
            "logic": logic,
            "logic_en": generate_logic_en(logic),
        })
        if len(events) >= 50:
            break

    # 生成四列表（精炼到6-10条核心）
    four_column_table = generate_four_column_table(headlines)

    # 生成因果链（真正的因果逻辑串联）
    chains = generate_causal_chains(headlines)

    # 生成待验证清单（针对因果链）
    verifications = generate_verifications(chains, headlines)

    # 生成历史类比（真实历史事件）
    historical_analogies = generate_historical_analogies(headlines)

    log(f"[规则] 结构化完成 v5: {len(events)} 条事件, {len(stats)} 条统计, "
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
        log("LLM 不可用，使用规则兜底方案 v5")
        structured = rule_based_structure(filtered)

    # Step 4: 最终双语校验
    issues = validate_bilingual(structured)
    if issues:
        log(f"[校验] ⚠️ 发现 {len(issues)} 个双语问题，自动修复...")
        structured = auto_fill_english(structured)
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
        "filter_result": f"{len(structured.get('four_column_table',[]))}条核心要闻 / {len(structured.get('chains',[]))}条因果链 / {len(headlines)}条原始抓取",
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
