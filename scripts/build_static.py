#!/usr/bin/env python3
"""
静态构建脚本 - 将 data/*.json 渲染为静态 HTML（支持中英文切换）
用于 GitHub Pages 部署（无需后端服务器）
"""

import json
import os
import glob
import shutil
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "public")

# ========== 翻译字典 ==========

I18N = {
    # 导航
    "today": {"zh": "今日", "en": "Today"},
    "history": {"zh": "历史归档", "en": "Archive"},
    "rss": {"zh": "RSS订阅", "en": "RSS"},
    "json_api": {"zh": "JSON API", "en": "JSON API"},
    # 分享
    "copy_link": {"zh": "🔗 复制链接", "en": "🔗 Copy Link"},
    "link_copied": {"zh": "链接已复制！", "en": "Link copied!"},
    # 章节
    "core_news": {"zh": "📌 核心要闻", "en": "📌 Key Headlines"},
    "causal_chains": {"zh": "🔗 因果链逐条拆解", "en": "🔗 Causal Chain Breakdown"},
    "verify_list": {"zh": "🔍 待验证清单", "en": "🔍 Watchlist"},
    # 事件卡
    "affected_assets": {"zh": "影响资产：", "en": "Affected Assets: "},
    # 因果链
    "market_consensus": {"zh": "市场共识", "en": "Consensus"},
    "to_verify": {"zh": "待验证", "en": "Unverified"},
    # 待验证
    "analogy_label": {"zh": "📖 历史类比：", "en": "📖 Historical Analogy: "},
    "lesson_label": {"zh": "💡 教训：", "en": "💡 Lesson: "},
    "diff_label": {"zh": "⚡ 关键区别：", "en": "⚡ Key Difference: "},
    # 页脚
    "footer_source": {"zh": "📊 本市场地图基于华尔街见闻快讯", "en": "📊 Based on WallstreetCN flash news"},
    "footer_funnel": {"zh": "三层漏斗：① 价格变动/新信息/宏观/资产相关 → ② 去重去噪 → ③ 保留", "en": "3-layer funnel: ① Price/Info/Macro → ② Dedup → ③ Top "},
    "footer_funnel_mid": {"zh": "条核心，", "en": " key events, "},
    "footer_funnel_end": {"zh": "条待验证", "en": " watchlist items"},
    "footer_disclaimer": {"zh": "⚠️ 仅供研究参考，不构成投资建议", "en": "⚠️ For research reference only, not investment advice"},
    "footer_auto": {"zh": "🤖 自动更新：GitHub Actions 每半小时自动抓取 → 构建 → 部署", "en": "🤖 Auto-updated: GitHub Actions every 30min → Build → Deploy"},
    # 历史
    "back_today": {"zh": "← 返回今日", "en": "← Back to Today"},
    "history_title": {"zh": "📅 历史归档", "en": "📅 Archive"},
    "weekday_map": {
        "星期一": {"zh": "星期一", "en": "Monday"},
        "星期二": {"zh": "星期二", "en": "Tuesday"},
        "星期三": {"zh": "星期三", "en": "Wednesday"},
        "星期四": {"zh": "星期四", "en": "Thursday"},
        "星期五": {"zh": "星期五", "en": "Friday"},
        "星期六": {"zh": "星期六", "en": "Saturday"},
        "星期日": {"zh": "星期日", "en": "Sunday"},
    }
}

# ========== HTML 模板 ==========

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日市场地图 · Daily Market Map · {{ date }}</title>
<meta name="description" content="华尔街见闻要闻三层漏斗筛选 → 四列表 → 因果链 → 待验证">
<style>
  :root {
    --bg: #0a0e17;
    --card: #131826;
    --card-2: #1a2030;
    --border: #2a3344;
    --text: #e8ecf1;
    --text-dim: #8b95a7;
    --accent: #d4af37;
    --accent-2: #4a9eff;
    --green: #26a69a;
    --red: #ef5350;
    --orange: #ff9800;
    --purple: #ab47bc;
  }

  [data-theme="light"] {
    --bg: #f5f7fa;
    --card: #ffffff;
    --card-2: #eef1f5;
    --border: #dde3ed;
    --text: #1a2030;
    --text-dim: #5a6478;
    --accent: #b8860b;
    --accent-2: #2563eb;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    transition: background 0.3s, color 0.3s;
  }

  .container { max-width: 1200px; margin: 0 auto; padding: 20px; }

  /* Top bar */
  .topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 14px;
    padding: 16px 20px;
    background: var(--card);
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 100;
    flex-wrap: wrap;
  }
  .topbar-left { display: flex; align-items: center; gap: 14px; }
  .topbar-logo { font-size: 22px; font-weight: 700; color: var(--accent); }
  .topbar-date { color: var(--text-dim); font-size: 14px; }
  .topbar-nav { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .topbar-nav a {
    color: var(--text-dim);
    text-decoration: none;
    font-size: 13px;
    padding: 5px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    transition: all 0.2s;
  }
  .topbar-nav a:hover { color: var(--accent); border-color: var(--accent); }
  .icon-btn {
    background: var(--card-2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 12px;
    cursor: pointer;
    font-size: 14px;
    color: var(--text);
    transition: all 0.2s;
  }
  .icon-btn:hover { border-color: var(--accent); }
  .lang-toggle {
    background: var(--card-2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 12px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    color: var(--accent);
    transition: all 0.2s;
    min-width: 56px;
    text-align: center;
  }
  .lang-toggle:hover { border-color: var(--accent); background: rgba(212,175,55,0.1); }

  /* Stats */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin: 20px 0;
  }
  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    text-align: center;
  }
  .stat-card .stat-label { font-size: 12px; color: var(--text-dim); margin-bottom: 6px; }
  .stat-card .stat-value { font-size: 28px; font-weight: 700; }
  .stat-card .stat-change { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
  .stat-up { color: var(--red); }
  .stat-down { color: var(--green); }
  .stat-neutral { color: var(--text-dim); }

  /* Section */
  .section { margin: 30px 0; }
  .section-title {
    font-size: 20px;
    font-weight: 700;
    color: var(--accent);
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--border);
  }

  /* Event card */
  .event-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 12px;
  }
  .event-tags { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
  .tag {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
  }
  .tag-ai { background: rgba(74,158,255,0.15); color: var(--accent-2); }
  .tag-fed { background: rgba(212,175,55,0.15); color: var(--accent); }
  .tag-energy { background: rgba(255,152,0,0.15); color: var(--orange); }
  .tag-china { background: rgba(239,83,80,0.15); color: var(--red); }
  .tag-bio { background: rgba(171,71,188,0.15); color: var(--purple); }
  .tag-macro { background: rgba(38,166,154,0.15); color: var(--green); }

  .event-text { font-size: 15px; margin-bottom: 10px; }
  .event-assets { font-size: 13px; color: var(--text-dim); margin-bottom: 8px; }
  .event-assets strong { color: var(--accent-2); }
  .event-logic {
    font-size: 13px;
    color: var(--text-dim);
    padding: 10px;
    background: var(--card-2);
    border-radius: 6px;
    border-left: 3px solid var(--accent);
  }
  .dir-arrow { font-size: 18px; font-weight: 700; }
  .dir-up { color: var(--red); }
  .dir-down { color: var(--green); }
  .dir-split { color: var(--orange); }
  .dir-neutral { color: var(--text-dim); }

  /* Chain */
  .chain-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 16px;
  }
  .chain-title { font-size: 16px; font-weight: 700; margin-bottom: 14px; }
  .chain-status {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 4px;
    margin-left: 8px;
    vertical-align: middle;
  }
  .status-consensus { background: rgba(38,166,154,0.15); color: var(--green); }
  .status-unverified { background: rgba(255,152,0,0.15); color: var(--orange); }

  .flow-nodes {
    display: flex;
    align-items: stretch;
    gap: 4px;
    flex-wrap: wrap;
    margin-bottom: 14px;
  }
  .flow-node {
    flex: 1;
    min-width: 120px;
    background: var(--card-2);
    border-radius: 8px;
    padding: 12px 8px;
    text-align: center;
    font-size: 12px;
    position: relative;
  }
  .flow-node.trigger { border: 2px solid var(--accent); }
  .flow-node.result-down { border: 2px solid var(--green); }
  .flow-node.result-up { border: 2px solid var(--red); }
  .flow-arrow {
    display: flex;
    align-items: center;
    color: var(--text-dim);
    font-size: 18px;
  }

  .jargon-list { margin-top: 10px; }
  .jargon-item {
    font-size: 13px;
    margin-bottom: 8px;
    padding: 8px 12px;
    background: var(--card-2);
    border-radius: 6px;
  }
  .jargon-term { color: var(--accent); font-weight: 600; }
  .jargon-explain { color: var(--text-dim); }

  /* Verify */
  .verify-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 16px;
  }
  .verify-title { font-size: 15px; font-weight: 700; margin-bottom: 12px; }
  .verify-list { list-style: none; margin-bottom: 12px; }
  .verify-list li {
    font-size: 13px;
    color: var(--text-dim);
    margin-bottom: 6px;
    padding-left: 20px;
    position: relative;
  }
  .verify-list li::before {
    content: "\\2610";
    position: absolute;
    left: 0;
    color: var(--accent);
  }
  .analogy {
    font-size: 13px;
    padding: 10px 12px;
    background: var(--card-2);
    border-radius: 6px;
    border-left: 3px solid var(--purple);
    margin-bottom: 8px;
  }
  .analogy strong { color: var(--purple); }
  .lesson {
    font-size: 13px;
    color: var(--accent);
    padding: 8px 12px;
    background: rgba(212,175,55,0.08);
    border-radius: 6px;
    margin-bottom: 8px;
  }
  .diff {
    font-size: 12px;
    color: var(--text-dim);
    padding: 8px 12px;
    background: var(--card-2);
    border-radius: 6px;
  }

  /* Share */
  .share-bar {
    display: flex;
    gap: 10px;
    margin: 20px 0;
    flex-wrap: wrap;
  }
  .share-btn {
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 13px;
    cursor: pointer;
    border: 1px solid var(--border);
    background: var(--card);
    color: var(--text);
    text-decoration: none;
    transition: all 0.2s;
  }
  .share-btn:hover { border-color: var(--accent); color: var(--accent); }

  /* Footer */
  footer {
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
    text-align: center;
    color: var(--text-dim);
    font-size: 12px;
  }

  /* i18n: hide non-active language by default */
  [data-lang="en"] { display: none; }
  body.lang-en [data-lang="zh"] { display: none; }
  body.lang-en [data-lang="en"] { display: inline; }
  body.lang-en [data-lang="en"][style*="block"] { display: block; }

  /* Responsive */
  @media (max-width: 768px) {
    .container { padding: 12px; }
    .topbar { padding: 12px; }
    .topbar-logo { font-size: 18px; }
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
    .stat-card .stat-value { font-size: 22px; }
    .flow-nodes { flex-direction: column; }
    .flow-arrow { transform: rotate(90deg); justify-content: center; }
    .event-card, .chain-card, .verify-card { padding: 14px; }
    .section-title { font-size: 17px; }
  }
</style>
</head>
<body data-theme="dark" class="lang-zh">

<div class="topbar">
  <div class="topbar-left">
    <div class="topbar-logo">📊 Macro Market Map</div>
    <div class="topbar-date">{{ date }} <span data-lang="zh">{{ weekday_zh }}</span><span data-lang="en">{{ weekday_en }}</span></div>
  </div>
  <div class="topbar-nav">
    <a href="{{ base }}index.html"><span data-lang="zh">今日</span><span data-lang="en">Today</span></a>
    <a href="{{ base }}history.html"><span data-lang="zh">历史归档</span><span data-lang="en">Archive</span></a>
    <a href="{{ base }}rss.xml">RSS</a>
    <a href="{{ base }}api/latest.json">JSON API</a>
    <button class="lang-toggle" onclick="toggleLang()">EN</button>
    <button class="icon-btn" onclick="toggleTheme()">🌙/☀️</button>
  </div>
</div>

<div class="container">

  <div class="share-bar">
    <a class="share-btn" href="https://twitter.com/intent/tweet?text=Daily%20Market%20Map%20{{ date }}" target="_blank">🐦 Twitter</a>
    <a class="share-btn" href="https://service.weibo.com/share/share.php?title=每日市场地图 {{ date }}" target="_blank"><span data-lang="zh">📷 微博</span><span data-lang="en">📷 Weibo</span></a>
    <button class="share-btn" onclick="copyLink()"><span data-lang="zh">🔗 复制链接</span><span data-lang="en">🔗 Copy Link</span></button>
  </div>

  <!-- Stats -->
  <div class="stats-grid">
    {{ stats_html }}
  </div>

  <!-- Events -->
  <div class="section">
    <div class="section-title"><span data-lang="zh">📌 核心要闻（{{ events_count }}条）</span><span data-lang="en">📌 Key Headlines ({{ events_count }})</span></div>
    {{ events_html }}
  </div>

  <!-- Chains -->
  <div class="section">
    <div class="section-title"><span data-lang="zh">🔗 因果链逐条拆解（{{ chains_count }}条）</span><span data-lang="en">🔗 Causal Chain Breakdown ({{ chains_count }})</span></div>
    {{ chains_html }}
  </div>

  <!-- Verifications -->
  <div class="section">
    <div class="section-title"><span data-lang="zh">🔍 待验证清单（{{ verifications_count }}条）</span><span data-lang="en">🔍 Watchlist ({{ verifications_count }})</span></div>
    {{ verifications_html }}
  </div>

  <footer>
    <p><span data-lang="zh">📊 本市场地图基于华尔街见闻快讯（{{ source }}）{{ date }} {{ crawl_time }}抓取内容生成</span><span data-lang="en">📊 Based on WallstreetCN flash news ({{ source }}), {{ date }} {{ crawl_time }}</span></p>
    <p><span data-lang="zh">三层漏斗：① 价格变动/新信息/宏观/资产相关 → ② 去重去噪 → ③ 保留{{ events_count }}条核心，{{ chains_count }}条因果链，{{ verifications_count }}条待验证</span><span data-lang="en">3-layer funnel: ① Price/Info/Macro filter → ② Dedup → ③ Top {{ events_count }} events, {{ chains_count }} chains, {{ verifications_count }} watchlist items</span></p>
    <p style="margin-top:8px; color: var(--text-dim);"><span data-lang="zh">⚠️ 仅供研究参考，不构成投资建议</span><span data-lang="en">⚠️ For research reference only, not investment advice</span></p>
    <p style="margin-top:8px;"><span data-lang="zh">🤖 自动更新：GitHub Actions 每半小时自动抓取 → 构建 → 部署</span><span data-lang="en">🤖 Auto-updated: GitHub Actions every 30min → Build → Deploy</span></p>
  </footer>
</div>

<script>
// Theme toggle
function toggleTheme() {
  var body = document.body;
  var current = body.getAttribute('data-theme');
  var next = current === 'dark' ? 'light' : 'dark';
  body.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
}
(function() {
  var saved = localStorage.getItem('theme');
  if (saved) document.body.setAttribute('data-theme', saved);
})();

// Language toggle
function toggleLang() {
  var body = document.body;
  var current = body.className.indexOf('lang-en') >= 0 ? 'en' : 'zh';
  if (current === 'zh') {
    body.className = body.className.replace('lang-zh', 'lang-en');
    document.querySelector('.lang-toggle').textContent = '中';
    document.documentElement.lang = 'en';
    localStorage.setItem('lang', 'en');
  } else {
    body.className = body.className.replace('lang-en', 'lang-zh');
    document.querySelector('.lang-toggle').textContent = 'EN';
    document.documentElement.lang = 'zh-CN';
    localStorage.setItem('lang', 'zh');
  }
}
(function() {
  var saved = localStorage.getItem('lang');
  if (saved === 'en') {
    document.body.className = document.body.className.replace('lang-zh', 'lang-en');
    var btn = document.querySelector('.lang-toggle');
    if (btn) btn.textContent = '中';
    document.documentElement.lang = 'en';
  }
})();

// Copy link
function copyLink() {
  navigator.clipboard.writeText(window.location.href).then(function() {
    var msg = document.body.className.indexOf('lang-en') >= 0 ? 'Link copied!' : '链接已复制！';
    alert(msg);
  });
}

// Auto refresh every 5 minutes
setTimeout(function() { location.reload(); }, 5 * 60 * 1000);
</script>
</body>
</html>'''


def translate_weekday(weekday_zh):
    """把中文星期翻译成英文"""
    mapping = {
        "星期一": "Monday", "星期二": "Tuesday", "星期三": "Wednesday",
        "星期四": "Thursday", "星期五": "Friday", "星期六": "Saturday", "星期日": "Sunday",
    }
    return mapping.get(weekday_zh, weekday_zh)


def render_stats(stats):
    """渲染统计卡片，中文和英文都包含"""
    html = ""
    for s in stats:
        dir_class = f"stat-{s.get('dir', 'neutral')}"
        label_en = s.get("label_en", s.get("label", ""))
        change_en = s.get("change_en", s.get("change", ""))
        html += f'''<div class="stat-card">
      <div class="stat-label"><span data-lang="zh">{s.get('label','')}</span><span data-lang="en">{label_en}</span></div>
      <div class="stat-value {dir_class}">{s.get('value','')}</div>
      <div class="stat-change"><span data-lang="zh">{s.get('change','')}</span><span data-lang="en">{change_en}</span></div>
    </div>\n'''
    return html


def translate_tag(text):
    """翻译标签"""
    mapping = {
        "AI": "AI", "政策": "Policy", "央行": "Central Bank", "能源": "Energy",
        "中国": "China", "生物科技": "Biotech", "财政": "Fiscal", "科技": "Tech",
        "流动性": "Liquidity",
    }
    return mapping.get(text, text)


def translate_event(ev):
    """翻译事件内容"""
    return {
        "event_en": ev.get("event_en", ev.get("event", "")),
        "assets_en": ev.get("assets_en", ev.get("assets", "")),
        "logic_en": ev.get("logic_en", ev.get("logic", "")),
    }


def render_events(events):
    """渲染事件卡片，中英文双语"""
    html = ""
    for ev in events:
        tags_html = ""
        for tag in ev.get("tags", []):
            tag_en = translate_tag(tag["text"])
            tags_html += f'<span class="tag tag-{tag["type"]}"><span data-lang="zh">{tag["text"]}</span><span data-lang="en">{tag_en}</span></span>'

        dir = ev.get("dir", "neutral")
        dir_class = f"dir-{dir}"
        arrow = {"up": "📈", "down": "📉", "split": "⚖️", "neutral": "➡️"}.get(dir, "➡️")

        tr = translate_event(ev)

        html += f'''<div class="event-card">
      <div class="event-tags">{tags_html}</div>
      <div class="event-text"><span class="dir-arrow {dir_class}">{arrow}</span> <span data-lang="zh">{ev.get("event","")}</span><span data-lang="en">{tr["event_en"]}</span></div>
      <div class="event-assets"><strong><span data-lang="zh">影响资产：</span><span data-lang="en">Affected Assets: </span></strong><span data-lang="zh">{ev.get("assets","")}</span><span data-lang="en">{tr["assets_en"]}</span></div>
      <div class="event-logic"><span data-lang="zh">{ev.get("logic","")}</span><span data-lang="en">{tr["logic_en"]}</span></div>
    </div>\n'''
    return html


def render_chains(chains):
    """渲染因果链，中英文双语"""
    html = ""
    for ch in chains:
        status = ch.get("status", "unverified")
        status_class = f"status-{status}"
        status_zh = "市场共识" if status == "consensus" else "待验证"
        status_en = "Consensus" if status == "consensus" else "Unverified"

        title_en = ch.get("title_en", ch["title"])

        nodes_html = ""
        for i, node in enumerate(ch.get("nodes", [])):
            node_type = node.get("type", "normal")
            node_class = f"flow-node {node_type}"
            node_en = node.get("text_en", node["text"])
            nodes_html += f'<div class="{node_class}"><span data-lang="zh">{node["text"]}</span><span data-lang="en">{node_en}</span></div>'
            if i < len(ch["nodes"]) - 1:
                nodes_html += '<div class="flow-arrow">→</div>'

        jargon_html = ""
        for j in ch.get("jargon", []):
            term_en = j.get("term_en", j["term"])
            explain_en = j.get("explain_en", j["explain"])
            jargon_html += f'''<div class="jargon-item">
        <span class="jargon-term"><span data-lang="zh">{j["term"]}</span><span data-lang="en">{term_en}</span></span>：<span data-lang="zh">{j["explain"]}</span><span data-lang="en">{explain_en}</span>
      </div>\n'''

        html += f'''<div class="chain-card">
      <div class="chain-title"><span data-lang="zh">{ch["title"]}</span><span data-lang="en">{title_en}</span> <span class="chain-status {status_class}"><span data-lang="zh">{status_zh}</span><span data-lang="en">{status_en}</span></span></div>
      <div class="flow-nodes">{nodes_html}</div>
      <div class="jargon-list">{jargon_html}</div>
    </div>\n'''
    return html


def render_verifications(verifications):
    """渲染待验证清单，中英文双语"""
    html = ""
    for v in verifications:
        vars_html = ""
        for var in v.get("vars", []):
            var_en = var if var.startswith("http") else var  # 变量项保持原文
            vars_html += f"<li>{var}</li>\n"

        title_en = v.get("title_en", v["title"])
        analogy_title_en = v.get("analogy_title_en", v.get("analogy_title", ""))
        analogy_text_en = v.get("analogy_text_en", v.get("analogy_text", ""))
        lesson_en = v.get("lesson_en", v.get("lesson", ""))
        diff_en = v.get("diff_en", v.get("diff", ""))

        html += f'''<div class="verify-card">
      <div class="verify-title"><span data-lang="zh">{v["title"]}</span><span data-lang="en">{title_en}</span></div>
      <ul class="verify-list">{vars_html}</ul>
      <div class="analogy"><strong><span data-lang="zh">📖 历史类比：</span><span data-lang="en">📖 Historical Analogy: </span></strong><span data-lang="zh">{v.get("analogy_title","")} — {v.get("analogy_text","")}</span><span data-lang="en">{analogy_title_en} — {analogy_text_en}</span></div>
      <div class="lesson">💡 <strong><span data-lang="zh">教训：</span><span data-lang="en">Lesson: </span></strong><span data-lang="zh">{v.get("lesson","")}</span><span data-lang="en">{lesson_en}</span></div>
      <div class="diff">⚡ <strong><span data-lang="zh">关键区别：</span><span data-lang="en">Key Difference: </span></strong><span data-lang="zh">{v.get("diff","")}</span><span data-lang="en">{diff_en}</span></div>
    </div>\n'''
    return html


def build_page(data, base=""):
    """渲染单日数据为 HTML（双语）
    base: 相对路径前缀，首页为 ""，子目录页面为 "../"
    """
    tpl = HTML_TEMPLATE
    weekday_zh = data.get("weekday", "")
    weekday_en = translate_weekday(weekday_zh)

    replacements = {
        "{{ date }}": data.get("date", ""),
        "{{ weekday_zh }}": weekday_zh,
        "{{ weekday_en }}": weekday_en,
        "{{ crawl_time }}": data.get("crawl_time", ""),
        "{{ source }}": data.get("source", ""),
        "{{ events_count }}": str(len(data.get("events", []))),
        "{{ chains_count }}": str(len(data.get("chains", []))),
        "{{ verifications_count }}": str(len(data.get("verifications", []))),
        "{{ stats_html }}": render_stats(data.get("stats", [])),
        "{{ events_html }}": render_events(data.get("events", [])),
        "{{ chains_html }}": render_chains(data.get("chains", [])),
        "{{ verifications_html }}": render_verifications(data.get("verifications", [])),
        "{{ base }}": base,
    }
    for k, v in replacements.items():
        tpl = tpl.replace(k, v)
    return tpl


def build_history(dates):
    """构建历史归档页（双语）"""
    items = ""
    for d in dates:
        items += f'<li><a href="date/{d}.html">📅 {d}</a></li>\n'

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>历史归档 · Archive · 市场地图</title>
<style>
  :root {{ --bg:#0a0e17; --card:#131826; --border:#2a3344; --text:#e8ecf1; --text-dim:#8b95a7; --accent:#d4af37; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text); }}
  .container {{ max-width:800px; margin:0 auto; padding:40px 20px; }}
  h1 {{ color:var(--accent); margin-bottom:20px; }}
  a {{ color:var(--text-dim); text-decoration:none; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:24px; }}
  ul {{ list-style:none; }}
  li {{ margin-bottom:10px; font-size:16px; }}
  li a:hover {{ color:var(--accent); }}
  .nav a {{ color:var(--accent); margin-right:14px; }}
  [data-lang="en"] {{ display:none; }}
  body.lang-en [data-lang="zh"] {{ display:none; }}
  body.lang-en [data-lang="en"] {{ display:inline; }}
  .lang-toggle {{ background:var(--card); border:1px solid var(--border); border-radius:6px; padding:5px 12px; cursor:pointer; font-size:13px; font-weight:600; color:var(--accent); }}
</style></head><body class="lang-zh"><div class="container">
<div class="nav">
  <a href="index.html"><span data-lang="zh">← 返回今日</span><span data-lang="en">← Back to Today</span></a>
  <button class="lang-toggle" onclick="toggleLang()">EN</button>
</div>
<h1><span data-lang="zh">📅 历史归档</span><span data-lang="en">📅 Archive</span></h1>
<div class="card"><ul>{items}</ul></div>
<script>
function toggleLang() {{
  var b = document.body;
  if (b.className.indexOf('lang-en') >= 0) {{
    b.className = b.className.replace('lang-en','lang-zh');
    document.querySelector('.lang-toggle').textContent = 'EN';
    localStorage.setItem('lang','zh');
  }} else {{
    b.className = b.className.replace('lang-zh','lang-en');
    document.querySelector('.lang-toggle').textContent = '中';
    localStorage.setItem('lang','en');
  }}
}}
(function() {{
  if (localStorage.getItem('lang') === 'en') {{
    document.body.className = 'lang-en';
    document.querySelector('.lang-toggle').textContent = '中';
  }}
}})();
</script>
</div></body></html>'''


def build_rss(dates, all_data):
    """构建 RSS feed"""
    items_xml = ""
    for d in dates[:30]:
        data = all_data.get(d)
        if not data:
            continue
        title = f"每日市场地图 · {data.get('date', d)}"
        desc_parts = []
        for ev in data.get("events", [])[:5]:
            desc_parts.append(ev.get("event", ""))
        description = " | ".join(desc_parts)[:300]
        items_xml += f"""<item>
  <title>{title}</title>
  <link>https://anniexu991203-sys.github.io/market-map/date/{d}.html</link>
  <description><![CDATA[{description}]]></description>
  <pubDate>{d}T13:00:00+08:00</pubDate>
  <guid>https://anniexu991203-sys.github.io/market-map/date/{d}.html</guid>
</item>
"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>每日市场地图 · Daily Market Map</title>
  <link>https://anniexu991203-sys.github.io/market-map/</link>
  <description>华尔街见闻要闻三层漏斗筛选 → 四列表 → 因果链 → 待验证</description>
  <language>zh-CN</language>
  <lastBuildDate>{datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0800')}</lastBuildDate>
{items_xml}
</channel>
</rss>"""


def build_all():
    """构建所有静态文件到 public/ 目录"""
    # 清空输出目录
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR)
    os.makedirs(os.path.join(OUTPUT_DIR, "date"))
    os.makedirs(os.path.join(OUTPUT_DIR, "api"))

    # 读取所有数据
    json_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")), reverse=True)
    dates = []
    all_data = {}

    for f in json_files:
        with open(f, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        d = data.get("date", os.path.basename(f).replace(".json", ""))
        dates.append(d)
        all_data[d] = data

    if not dates:
        print("⚠️ 没有找到数据文件！")
        return

    print(f"找到 {len(dates)} 期数据: {dates}")

    # 1. 构建首页（最新一期）
    latest_date = dates[0]
    latest_data = all_data[latest_date]
    index_html = build_page(latest_data, base="")
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"✅ 首页 → index.html ({latest_date})")

    # 2. 构建每日页面（子目录，需要 ../ 前缀）
    for d, data in all_data.items():
        page_html = build_page(data, base="../")
        with open(os.path.join(OUTPUT_DIR, "date", f"{d}.html"), "w", encoding="utf-8") as f:
            f.write(page_html)
        print(f"✅ 日期页 → date/{d}.html")

    # 3. 历史归档页
    history_html = build_history(dates)
    with open(os.path.join(OUTPUT_DIR, "history.html"), "w", encoding="utf-8") as f:
        f.write(history_html)
    print("✅ 历史归档 → history.html")

    # 4. RSS feed
    rss_xml = build_rss(dates, all_data)
    with open(os.path.join(OUTPUT_DIR, "rss.xml"), "w", encoding="utf-8") as f:
        f.write(rss_xml)
    print("✅ RSS → rss.xml")

    # 5. JSON API（静态文件模拟）
    with open(os.path.join(OUTPUT_DIR, "api", "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest_data, f, ensure_ascii=False, indent=2)
    print("✅ API → api/latest.json")

    with open(os.path.join(OUTPUT_DIR, "api", "dates.json"), "w", encoding="utf-8") as f:
        json.dump({"dates": dates}, f, ensure_ascii=False, indent=2)
    print("✅ API → api/dates.json")

    for d, data in all_data.items():
        with open(os.path.join(OUTPUT_DIR, "api", f"{d}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ API → {len(dates)} 个日期JSON")

    print(f"\n🎉 构建完成！输出目录: {OUTPUT_DIR}")
    print(f"   总文件数: {sum(len(files) for _, _, files in os.walk(OUTPUT_DIR))}")


if __name__ == "__main__":
    build_all()
