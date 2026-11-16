#!/usr/bin/env python3
"""
每日市场地图 - 自动更新脚本 (完整版)

数据流：
  华尔街见闻 API → 原始快讯 → LLM 三层漏斗筛选 → 结构化 JSON → 网站自动展示

使用方法：
  python3 update_daily.py                        # 抓取今天的数据
  python3 update_daily.py --date 2026-11-17      # 指定日期
  python3 update_daily.py --dry-run              # 只抓取不保存（测试用）
  python3 update_daily.py --source rss           # 用 RSS 源而非 API

crontab（每个交易日13:00自动执行）：
  0 13 * * 1-5 cd /path/to/market-map-site && python3 scripts/update_daily.py >> logs/update.log 2>&1

环境变量：
  LLM_API_KEY    - LLM API 密钥（用于三层漏斗筛选，可选，无则用规则筛选）
  LLM_API_BASE   - LLM API 地址（默认使用公开API）
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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 华尔街见闻 API 端点
WSCN_API = "https://api.wallstreetcn.com/apiv1/content/lives?channel=global-channel&limit=200"
WSCN_RSS = "https://wallstreetcn.com/rss"
WSCN_PAGE = "https://wallstreetcn.com/live/global"

# 市场关键词（用于第一层漏斗过滤）
MARKET_KEYWORDS = [
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

# 噪声关键词（过滤掉无关内容）
NOISE_KEYWORDS = [
    "广告", "推广", "赞助", "活动", "报名", "直播预约",
    "课程", "会员", "订阅", "下载APP",
]


def log(msg):
    """带时间戳的日志输出"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


# ============================================================
# 第一层：数据抓取
# ============================================================

def fetch_via_api():
    """通过华尔街见闻 API 抓取快讯"""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://wallstreetcn.com/live/global",
    }
    try:
        log(f"[API] 正在请求: {WSCN_API}")
        resp = requests.get(WSCN_API, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        log(f"[API] 获取 {len(items)} 条快讯")
        headlines = []
        for item in items:
            text = item.get("content_text", "") or item.get("content", "")
            # 清理 HTML 标签
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
            })
        return headlines
    except Exception as e:
        log(f"[API] 抓取失败: {e}")
        return []


def fetch_via_rss():
    """通过 RSS 抓取华尔街见闻快讯"""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    }
    try:
        log(f"[RSS] 正在请求: {WSCN_RSS}")
        resp = requests.get(WSCN_RSS, headers=headers, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")
        log(f"[RSS] 获取 {len(items)} 条快讯")
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
            })
        return headlines
    except Exception as e:
        log(f"[RSS] 抓取失败: {e}")
        return []


def fetch_via_page():
    """通过直接抓取网页获取快讯（兜底方案）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://wallstreetcn.com/",
    }
    try:
        log(f"[PAGE] 正在请求: {WSCN_PAGE}")
        resp = requests.get(WSCN_PAGE, headers=headers, timeout=30)
        resp.raise_for_status()

        # 华尔街见闻是 SPA，数据通过 JSON 注入
        # 尝试从页面中提取内嵌的 JSON 数据
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
                            headlines.append({"text": t, "time": "", "timestamp": 0})
                    break

        log(f"[PAGE] 共提取 {len(headlines)} 条快讯")
        return headlines
    except Exception as e:
        log(f"[PAGE] 抓取失败: {e}")
        return []


def fetch_headlines(source="auto"):
    """抓取快讯（自动尝试多种方式）"""
    if source == "api":
        return fetch_via_api()
    elif source == "rss":
        return fetch_via_rss()
    elif source == "page":
        return fetch_via_page()
    else:
        # auto: 依次尝试 API → RSS → 页面
        for fetch_fn in [fetch_via_api, fetch_via_rss, fetch_via_page]:
            headlines = fetch_fn()
            if headlines:
                return headlines
            time.sleep(1)
        log("所有抓取方式均失败")
        return []


# ============================================================
# 第二层：三层漏斗筛选
# ============================================================

def funnel_filter(headlines):
    """
    三层漏斗筛选
    第一层：与价格变动/新信息/宏观/资产相关的条目
    第二层：去重去噪
    第三层：保留最重要的10-15条
    """
    # === 第一层：关键词过滤 ===
    filtered = []
    for h in headlines:
        text = h["text"]
        # 跳过噪声内容
        if any(kw in text for kw in NOISE_KEYWORDS):
            continue
        # 必须包含至少一个市场关键词
        if any(kw in text for kw in MARKET_KEYWORDS):
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

    # === 第三层：保留最重要的条目（优先含价格变动数据） ===
    def importance_score(h):
        """打分：含具体数字、涨跌幅、多关键词的条目得分更高"""
        text = h["text"]
        score = 0
        # 含具体数字 +5
        if re.search(r'\d+\.?\d*%?', text):
            score += 5
        # 含涨跌关键词 +3
        price_words = sum(1 for kw in ["涨", "跌", "新高", "新低", "飙升", "暴跌"] if kw in text)
        score += price_words * 3
        # 含多个市场关键词 +2 each
        market_count = sum(1 for kw in MARKET_KEYWORDS if kw in text)
        score += market_count * 2
        # 长文本可能信息更丰富
        if len(text) > 50:
            score += 3
        if len(text) > 100:
            score += 2
        return score

    scored = [(h, importance_score(h)) for h in deduped]
    scored.sort(key=lambda x: x[1], reverse=True)

    # 保留前 40 条供 LLM 进一步筛选
    top_headlines = [h for h, s in scored[:40]]
    log(f"第三层排序: 保留前 {len(top_headlines)} 条高分快讯")

    return top_headlines


# ============================================================
# 第三层：LLM 结构化（可选，需要 API key）
# ============================================================

LLM_PROMPT = """你是一个金融市场分析师。请从以下快讯中提取信息，生成每日市场地图。

快讯列表：
{headlines}

请按以下JSON格式输出（严格输出JSON，不要其他文字）：
{{
  "stats": [
    {{"label": "资产名称（含时间范围）", "value": "变动数值", "change": "一句话说明", "dir": "up或down"}}
  ],
  "events": [
    {{
      "tags": [{{"type": "ai/fed/energy/china/bio/macro", "text": "标签文字"}}],
      "event": "事件描述（一句话说清楚发生了什么）",
      "assets": "影响的资产（逗号分隔）",
      "dir": "up/down/neutral/split",
      "logic": "传导逻辑（A→B→C 格式）"
    }}
  ],
  "chains": [
    {{
      "title": "因果链标题（① 编号 + 简述）",
      "status": "consensus或unverified",
      "nodes": [
        {{"text": "节点描述<br>第二行", "type": "trigger/normal/result-up/result-down"}}
      ],
      "jargon": [
        {{"term": "术语名称", "explain": "白话解释"}}
      ]
    }}
  ],
  "verifications": [
    {{
      "title": "待验证问题",
      "vars": ["需盯变量1", "需盯变量2", "需盯变量3", "需盯变量4"],
      "analogy_title": "历史类比标题",
      "analogy_text": "历史类比描述",
      "lesson": "教训（红字）",
      "diff": "关键区别（绿字）"
    }}
  ]
}}

要求：
1. stats 保留 5-8 个最重要的市场数据
2. events 保留 8-12 条核心要闻
3. chains 提取 5-8 条因果链，按重要性排序
4. verifications 生成 3-5 条待验证问题
5. 节点text中用 <br> 换行
6. 严格输出合法 JSON"""


def llm_structure(headlines):
    """用 LLM 对筛选后的快讯进行结构化"""
    api_key = os.environ.get("LLM_API_KEY", "")
    api_base = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")

    # 格式化快讯列表
    headline_text = "\n".join(
        f"[{i+1}] ({h.get('time','')}) {h['text']}"
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
        return structured
    except Exception as e:
        log(f"[LLM] 请求失败: {e}")
        return None


def rule_based_structure(headlines):
    """
    无 LLM 时的规则兜底方案：
    从快讯中提取关键信息，生成基础结构化数据
    """
    import re

    events = []
    seen_topics = set()

    for h in headlines:
        text = h["text"]
        if len(text) < 15:
            continue

        # 判断方向
        dir = "neutral"
        if any(kw in text for kw in ["涨", "升", "高", "增", "涨超"]):
            if any(kw in text for kw in ["跌", "降", "低", "减", "跌超"]):
                dir = "split"
            else:
                dir = "up"
        elif any(kw in text for kw in ["跌", "降", "低", "减", "跌超", "暴跌"]):
            dir = "down"

        # 判断标签
        tags = []
        if any(kw in text for kw in ["AI", "芯片", "英伟达", "半导体", "人工智能", "OpenAI", "数据中心"]):
            tags.append({"type": "ai", "text": "AI"})
        if any(kw in text for kw in ["美联储", "央行", "加息", "降息", "利率", "PPI", "CPI", "通胀"]):
            tags.append({"type": "fed", "text": "央行"})
        if any(kw in text for kw in ["原油", "油价", "布油", "OPEC", "能源"]):
            tags.append({"type": "energy", "text": "能源"})
        if any(kw in text for kw in ["中国", "A股", "社零", "工业增加值", "地产", "统计局", "创业板", "港股"]):
            tags.append({"type": "china", "text": "中国"})
        if any(kw in text for kw in ["生物科技", "创新药", "医药", "临床"]):
            tags.append({"type": "bio", "text": "生物科技"})
        if any(kw in text for kw in ["赤字", "财政", "国债", "发债"]):
            tags.append({"type": "macro", "text": "财政"})
        if not tags:
            tags.append({"type": "macro", "text": "宏观"})

        # 提取数字
        numbers = re.findall(r'(\d+\.?\d*%?)', text)
        # 简化事件描述（取前120字符）
        event_text = text[:150] + ("..." if len(text) > 150 else "")

        # 简单去重：用前30字符做topic hash
        topic = text[:30]
        if topic in seen_topics:
            continue
        seen_topics.add(topic)

        events.append({
            "tags": tags,
            "event": event_text,
            "assets": "",
            "dir": dir,
            "logic": "",
        })

        if len(events) >= 10:
            break

    # 提取关键数字做 stats
    stats = []
    stat_seen = set()
    for h in headlines:
        text = h["text"]
        # 找 "XX涨/跌XX%" 或 "XX新高/新低" 等模式
        patterns = [
            r'([\u4e00-\u9fa5\w]{2,10})[，,]?\s*(?:涨|跌|升|降)([\d.]+%)',
            r'([\u4e00-\u9fa5\w]{2,10}).*?创.*?(?:新高|新低)',
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                label = m.group(1)[:15]
                if label in stat_seen:
                    continue
                stat_seen.add(label)

                value = ""
                change = text[:40]
                dir = "up"
                if "跌" in text or "降" in text:
                    dir = "down"
                if m.lastindex >= 2:
                    value = m.group(2)

                stats.append({
                    "label": label,
                    "value": value or ("新高" if dir == "up" else "新低"),
                    "change": change,
                    "dir": dir,
                })
                if len(stats) >= 6:
                    break
        if len(stats) >= 6:
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
    """生成指定日期的数据文件"""
    if target_date is None:
        target_date = date.today().isoformat()

    weekday_idx = datetime.strptime(target_date, "%Y-%m-%d").weekday()
    weekday = WEEKDAYS[weekday_idx]

    log(f"{'='*50}")
    log(f"开始生成 {target_date} ({weekday}) 的市场地图数据")
    log(f"{'='*50}")

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

    # Step 4: 组装最终数据
    data = {
        "date": target_date,
        "weekday": weekday,
        "crawl_time": f"约{datetime.now().strftime('%H:%M')}（北京时间）",
        "source": "wallstreetcn.com/live/global",
        "filter_result": f"{len(structured.get('events',[]))}条核心要闻 / {len(structured.get('chains',[]))}条因果链",
        "stats": structured.get("stats", []),
        "events": structured.get("events", []),
        "chains": structured.get("chains", []),
        "verifications": structured.get("verifications", []),
    }

    if dry_run:
        log(f"[DRY-RUN] 不保存文件，数据预览:")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:1000])
        return True

    # Step 5: 保存
    filepath = os.path.join(DATA_DIR, f"{target_date}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log(f"数据已保存: {filepath}")
    log(f"统计: {len(data['stats'])} 条统计, {len(data['events'])} 条事件, "
        f"{len(data['chains'])} 条因果链, {len(data['verifications'])} 条待验证")
    return True


def main():
    parser = argparse.ArgumentParser(description="每日市场地图自动更新")
    parser.add_argument("--date", type=str, default=None, help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--source", type=str, default="auto",
                        choices=["auto", "api", "rss", "page"],
                        help="数据源: auto/api/rss/page")
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
