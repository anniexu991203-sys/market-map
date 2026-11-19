#!/usr/bin/env python3
"""
静态构建脚本 v4 - 将 data/*.json 渲染为静态 HTML（支持中英文切换）

页面结构（按用户标准）：
  标题（含数据源+发布时间）→ 四列表（事件/影响资产/方向/传导逻辑）→
  因果链详解（流程图+术语白话）→ 待验证清单（两层：核心问题+具体盯3-4个变量）→
  金融历史类比（历史事件+教训+关键区别）
"""

import json
import os
import glob
import shutil
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "public")

# ========== HTML 模板 ==========

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日市场地图 · Daily Market Map · {{ date }}</title>
<meta name="description" content="华尔街见闻要闻三层漏斗筛选 → 四列表 → 因果链 → 待验证 → 历史类比">
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
    --yellow: #d29922;
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
    --green: #1a7f37;
    --red: #cf222e;
    --orange: #bc4c00;
    --purple: #8250df;
    --yellow: #9a6700;
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
    display: flex; justify-content: space-between; align-items: center;
    gap: 14px; padding: 16px 20px;
    background: var(--card); border-bottom: 1px solid var(--border);
    position: sticky; top: 0; z-index: 100; flex-wrap: wrap;
  }
  .topbar-left { display: flex; align-items: center; gap: 14px; }
  .topbar-logo { font-size: 22px; font-weight: 700; color: var(--accent); }
  .topbar-date { color: var(--text-dim); font-size: 14px; }
  .topbar-nav { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .topbar-nav a {
    color: var(--text-dim); text-decoration: none; font-size: 13px;
    padding: 5px 12px; border: 1px solid var(--border); border-radius: 6px;
    transition: all 0.2s;
  }
  .topbar-nav a:hover { color: var(--accent); border-color: var(--accent); }
  .icon-btn {
    background: var(--card-2); border: 1px solid var(--border); border-radius: 6px;
    padding: 5px 12px; cursor: pointer; font-size: 14px; color: var(--text); transition: all 0.2s;
  }
  .icon-btn:hover { border-color: var(--accent); }
  .lang-toggle {
    background: var(--card-2); border: 1px solid var(--border); border-radius: 6px;
    padding: 5px 12px; cursor: pointer; font-size: 13px; font-weight: 600;
    color: var(--accent); transition: all 0.2s; min-width: 56px; text-align: center;
  }
  .lang-toggle:hover { border-color: var(--accent); background: rgba(212,175,55,0.1); }

  /* Header */
  .page-header {
    text-align: center; padding: 30px 20px 20px;
    border-bottom: 1px solid var(--border); margin-bottom: 24px;
  }
  .page-header h1 { font-size: 26px; font-weight: 700; margin-bottom: 8px; }
  .page-header .meta { color: var(--text-dim); font-size: 14px; }
  .page-header .meta span { margin: 0 8px; }

  /* Section */
  .section { margin: 30px 0; }
  .section-title {
    font-size: 20px; font-weight: 700; color: var(--accent);
    margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid var(--border);
  }

  /* Stats */
  .stats-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px; margin: 20px 0;
  }
  .stat-card {
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px; text-align: center;
  }
  .stat-card .stat-label { font-size: 12px; color: var(--text-dim); margin-bottom: 6px; }
  .stat-card .stat-value { font-size: 28px; font-weight: 700; }
  .stat-card .stat-change { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
  .stat-up { color: var(--red); }
  .stat-down { color: var(--green); }
  .stat-neutral { color: var(--text-dim); }

  /* Four-column table */
  .market-table {
    width: 100%; border-collapse: collapse; margin-bottom: 10px;
  }
  .market-table th {
    background: var(--card); color: var(--accent);
    padding: 10px 12px; text-align: left; font-size: 13px; font-weight: 600;
    border: 1px solid var(--border); white-space: nowrap;
  }
  .market-table td {
    padding: 12px; border: 1px solid var(--border); vertical-align: top; font-size: 14px;
  }
  .market-table tr:hover td { background: var(--card-2); }
  .dir-up { color: var(--red); font-weight: 600; }
  .dir-down { color: var(--green); font-weight: 600; }
  .dir-neutral { color: var(--yellow); font-weight: 600; }
  .dir-split { color: var(--purple); font-weight: 600; }
  .tag {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 12px; margin: 2px; font-weight: 600;
  }
  .tag-geopolitics { background: rgba(239,83,80,0.15); color: var(--red); }
  .tag-central-bank { background: rgba(210,153,34,0.15); color: var(--yellow); }
  .tag-ai { background: rgba(74,158,255,0.15); color: var(--accent-2); }
  .tag-energy { background: rgba(255,152,0,0.15); color: var(--orange); }
  .tag-china { background: rgba(171,71,188,0.15); color: var(--purple); }
  .tag-macro { background: rgba(38,166,154,0.15); color: var(--green); }
  .tag-fed { background: rgba(210,153,34,0.15); color: var(--yellow); }
  .tag-bio { background: rgba(171,71,188,0.15); color: var(--purple); }

  /* Event cards (fallback if no four_column_table) */
  .event-card {
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 20px; margin-bottom: 12px;
  }
  .event-tags { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
  .event-text { font-size: 15px; margin-bottom: 10px; }
  .event-assets { font-size: 13px; color: var(--text-dim); margin-bottom: 8px; }
  .event-assets strong { color: var(--accent-2); }
  .event-logic {
    font-size: 13px; color: var(--text-dim); padding: 10px;
    background: var(--card-2); border-radius: 6px; border-left: 3px solid var(--accent);
  }
  .dir-arrow { font-size: 18px; font-weight: 700; }

  /* Chain cards */
  .chain-card {
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 20px; margin-bottom: 16px;
  }
  .chain-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 14px; flex-wrap: wrap; gap: 8px;
  }
  .chain-title { font-size: 16px; font-weight: 700; }
  .chain-badge {
    padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600;
  }
  .badge-consensus { background: rgba(38,166,154,0.15); color: var(--green); border: 1px solid rgba(38,166,154,0.3); }
  .badge-verify { background: rgba(255,152,0,0.15); color: var(--orange); border: 1px solid rgba(255,152,0,0.3); }

  /* Flow diagram */
  .flow-diagram {
    background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 16px; margin-bottom: 14px; overflow-x: auto;
  }
  .flow-nodes {
    display: flex; align-items: center; flex-wrap: wrap; gap: 4px; min-width: 600px;
  }
  .flow-node {
    background: var(--card-2); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 14px; font-size: 13px; white-space: nowrap; flex-shrink: 0;
  }
  .flow-node.cause { border-left: 3px solid var(--accent); }
  .flow-node.intermediate { border-left: 3px solid var(--yellow); }
  .flow-node.effect { border-left: 3px solid var(--red); }
  .flow-node.trigger { border: 2px solid var(--accent); }
  .flow-node.result-down { border: 2px solid var(--green); }
  .flow-node.result-up { border: 2px solid var(--red); }
  .flow-arrow { color: var(--text-dim); font-size: 18px; flex-shrink: 0; }

  /* Glossary */
  .glossary {
    background: var(--bg); border-radius: 8px; padding: 14px; margin-top: 12px;
  }
  .glossary-title { font-size: 13px; color: var(--text-dim); margin-bottom: 8px; font-weight: 600; }
  .glossary-item { margin-bottom: 6px; font-size: 13px; }
  .glossary-term { color: var(--accent); font-weight: 600; }

  /* Verify cards */
  .verify-card {
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 20px; margin-bottom: 16px;
  }
  .verify-title { font-size: 15px; font-weight: 700; margin-bottom: 12px; }
  .verify-layer { margin-bottom: 12px; }
  .verify-layer-title { font-size: 13px; color: var(--accent); font-weight: 600; margin-bottom: 6px; }
  .verify-detail { font-size: 13px; color: var(--text-dim); padding-left: 16px; }
  .verify-detail li { margin-bottom: 4px; list-style: disc; color: var(--text); }

  /* Historical analogy */
  .history-card {
    background: var(--card); border-left: 4px solid var(--purple);
    border-radius: 0 10px 10px 0; padding: 16px 20px; margin-bottom: 16px;
  }
  .history-event { font-size: 15px; font-weight: 700; color: var(--purple); margin-bottom: 6px; }
  .history-lesson { font-size: 14px; margin-bottom: 6px; }
  .history-diff { font-size: 13px; color: var(--text-dim); }

  /* Share */
  .share-bar { display: flex; gap: 10px; margin: 20px 0; flex-wrap: wrap; }
  .share-btn {
    padding: 8px 16px; border-radius: 8px; font-size: 13px; cursor: pointer;
    border: 1px solid var(--border); background: var(--card); color: var(--text);
    text-decoration: none; transition: all 0.2s;
  }
  .share-btn:hover { border-color: var(--accent); color: var(--accent); }

  /* Footer */
  footer {
    margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border);
    text-align: center; color: var(--text-dim); font-size: 12px;
  }

  /* i18n */
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
    .market-table { font-size: 12px; }
    .market-table th, .market-table td { padding: 8px 6px; }
    .flow-nodes { flex-direction: column; align-items: flex-start; min-width: 0; }
    .flow-arrow { transform: rotate(90deg); }
    .event-card, .chain-card, .verify-card, .history-card { padding: 14px; }
    .section-title { font-size: 17px; }
    .page-header h1 { font-size: 20px; }
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

  <!-- Header -->
  <div class="page-header">
    <h1>📊 <span data-lang="zh">每日市场地图</span><span data-lang="en">Daily Market Map</span></h1>
    <div class="meta">
      <span>📅 {{ date }} <span data-lang="zh">{{ weekday_zh }}</span><span data-lang="en">{{ weekday_en }}</span></span>
      <span>📡 <span data-lang="zh">数据源：华尔街见闻 wallstreetcn.com/live/global</span><span data-lang="en">Source: WallstreetCN</span></span>
      <span>🕐 {{ crawl_time }}</span>
    </div>
  </div>

  <!-- Stats -->
  {{ stats_html }}

  <!-- Section 1: Four-column table -->
  {{ four_column_html }}

  <!-- Section 2: Causal chains -->
  {{ chains_html }}

  <!-- Section 3: Verifications -->
  {{ verifications_html }}

  <!-- Section 4: Historical analogies -->
  {{ analogies_html }}

  <footer>
    <p><span data-lang="zh">📊 本市场地图基于华尔街见闻快讯（{{ source }}）{{ date }} {{ crawl_time }}抓取内容生成</span><span data-lang="en">📊 Based on WallstreetCN flash news ({{ source }}), {{ date }} {{ crawl_time }}</span></p>
    <p><span data-lang="zh">三层漏斗：① 价格变动/新信息/宏观/资产相关 → ② 去重去噪 → ③ 保留{{ events_count }}条核心，{{ chains_count }}条因果链，{{ verifications_count }}条待验证</span><span data-lang="en">3-layer funnel: ① Price/Info/Macro filter → ② Dedup → ③ Top {{ events_count }} events, {{ chains_count }} chains, {{ verifications_count }} watchlist items</span></p>
    <p style="margin-top:8px; color: var(--text-dim);"><span data-lang="zh">⚠️ 仅供研究参考，不构成投资建议</span><span data-lang="en">⚠️ For research reference only, not investment advice</span></p>
    <p style="margin-top:8px;"><span data-lang="zh">🤖 自动更新：GitHub Actions 每半小时自动抓取 → 构建 → 部署</span><span data-lang="en">🤖 Auto-updated: GitHub Actions every 30min → Build → Deploy</span></p>
  </footer>
</div>

<script>
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

function copyLink() {
  navigator.clipboard.writeText(window.location.href).then(function() {
    var msg = document.body.className.indexOf('lang-en') >= 0 ? 'Link copied!' : '链接已复制！';
    alert(msg);
  });
}

setTimeout(function() { location.reload(); }, 5 * 60 * 1000);
</script>
</body>
</html>'''


def translate_weekday(weekday_zh):
    mapping = {
        "星期一": "Monday", "星期二": "Tuesday", "星期三": "Wednesday",
        "星期四": "Thursday", "星期五": "Friday", "星期六": "Saturday", "星期日": "Sunday",
    }
    return mapping.get(weekday_zh, weekday_zh)


def render_stats(stats):
    html = '<div class="stats-grid">'
    for s in stats:
        dir_class = f"stat-{s.get('dir', 'neutral')}"
        label_en = s.get("label_en", s.get("label", ""))
        change_en = s.get("change_en", s.get("change", ""))
        html += f'''<div class="stat-card">
      <div class="stat-label"><span data-lang="zh">{s.get('label','')}</span><span data-lang="en">{label_en}</span></div>
      <div class="stat-value {dir_class}">{s.get('value','')}</div>
      <div class="stat-change"><span data-lang="zh">{s.get('change','')}</span><span data-lang="en">{change_en}</span></div>
    </div>\n'''
    html += '</div>'
    return html


def render_four_column_table(data):
    """渲染四列表：事件 / 影响资产 / 方向 / 传导逻辑"""
    table_data = data.get("four_column_table", [])

    if not table_data:
        # 回退：用 events 数据生成简化版四列表
        events = data.get("events", [])
        if not events:
            return ""
        table_data = []
        for ev in events:
            table_data.append({
                "event": ev.get("event", ""),
                "event_en": ev.get("event_en", ev.get("event", "")),
                "assets": ev.get("assets", ""),
                "assets_en": ev.get("assets_en", ev.get("assets", "")),
                "dir": ev.get("dir", "neutral"),
                "logic": ev.get("logic", ""),
                "logic_en": ev.get("logic_en", ""),
                "tags": ev.get("tags", []),
            })

    html = '''<div class="section">
    <div class="section-title"><span data-lang="zh">一、核心要闻四列速览</span><span data-lang="en">1. Key Headlines Overview</span></div>
    <table class="market-table">
      <thead>
        <tr>
          <th style="width:35%"><span data-lang="zh">事件</span><span data-lang="en">Event</span></th>
          <th style="width:20%"><span data-lang="zh">影响资产</span><span data-lang="en">Affected Assets</span></th>
          <th style="width:10%"><span data-lang="zh">方向</span><span data-lang="en">Direction</span></th>
          <th style="width:35%"><span data-lang="zh">传导逻辑</span><span data-lang="en">Transmission Logic</span></th>
        </tr>
      </thead>
      <tbody>\n'''

    for row in table_data:
        # Tags
        tags_html = ""
        for tag in row.get("tags", []):
            tag_type = tag.get("type", "macro")
            tag_text = tag.get("text", "")
            tag_en = tag.get("text_en", tag_text)
            tags_html += f'<span class="tag tag-{tag_type}"><span data-lang="zh">{tag_text}</span><span data-lang="en">{tag_en}</span></span> '

        # Direction
        dir = row.get("dir", "neutral")
        dir_map = {
            "up": ('<span data-lang="zh">↑ 涨</span><span data-lang="en">↑ Up</span>', "dir-up"),
            "down": ('<span data-lang="zh">↓ 跌</span><span data-lang="en">↓ Down</span>', "dir-down"),
            "neutral": ('<span data-lang="zh">→ 中性</span><span data-lang="en">→ Neutral</span>', "dir-neutral"),
            "split": ('<span data-lang="zh">↕ 分化</span><span data-lang="en">↕ Mixed</span>', "dir-split"),
        }
        dir_text, dir_class = dir_map.get(dir, dir_map["neutral"])

        event_en = row.get("event_en", row.get("event", ""))
        assets_en = row.get("assets_en", row.get("assets", ""))
        logic_en = row.get("logic_en", row.get("logic", ""))

        html += f'''        <tr>
          <td>{tags_html}<br><b><span data-lang="zh">{row.get('event','')}</span><span data-lang="en">{event_en}</span></b></td>
          <td><span data-lang="zh">{row.get('assets','')}</span><span data-lang="en">{assets_en}</span></td>
          <td class="{dir_class}">{dir_text}</td>
          <td><span data-lang="zh">{row.get('logic','')}</span><span data-lang="en">{logic_en}</span></td>
        </tr>\n'''

    html += '      </tbody>\n    </table>\n  </div>\n'
    return html


def render_chains(chains):
    if not chains:
        return ""

    html = f'''<div class="section">
    <div class="section-title"><span data-lang="zh">二、因果链逐条拆解（{len(chains)}条）</span><span data-lang="en">2. Causal Chain Breakdown ({len(chains)})</span></div>\n'''

    for idx, ch in enumerate(chains):
        status = ch.get("status", "unverified")
        status_class = f"badge-{status}" if status == "consensus" else "badge-verify"
        status_zh = "市场共识" if status == "consensus" else "待验证"
        status_en = "Consensus" if status == "consensus" else "Unverified"

        title_en = ch.get("title_en", ch["title"])

        # Flow nodes
        nodes_html = ""
        nodes = ch.get("nodes", [])
        for i, node in enumerate(nodes):
            node_type = node.get("type", "normal")
            node_class = f"flow-node {node_type}" if node_type != "normal" else "flow-node"
            node_en = node.get("text_en", node["text"])
            nodes_html += f'<div class="{node_class}"><span data-lang="zh">{node["text"]}</span><span data-lang="en">{node_en}</span></div>'
            if i < len(nodes) - 1:
                nodes_html += '<div class="flow-arrow">→</div>'

        # Jargon / glossary
        jargon_html = ""
        jargon = ch.get("jargon", [])
        if jargon:
            jargon_html = '<div class="glossary"><div class="glossary-title"><span data-lang="zh">📖 术语白话</span><span data-lang="en">📖 Plain Language</span></div>'
            for j in jargon:
                term_en = j.get("term_en", j["term"])
                explain_en = j.get("explain_en", j["explain"])
                jargon_html += f'''<div class="glossary-item"><span class="glossary-term"><span data-lang="zh">{j["term"]}</span><span data-lang="en">{term_en}</span></span>：<span data-lang="zh">{j["explain"]}</span><span data-lang="en">{explain_en}</span></div>\n'''
            jargon_html += '</div>'

        html += f'''    <div class="chain-card">
      <div class="chain-header">
        <div class="chain-title"><span data-lang="zh">🔗 因果链 {idx+1}：{ch["title"]}</span><span data-lang="en">🔗 Chain {idx+1}: {title_en}</span></div>
        <div class="chain-badge {status_class}"><span data-lang="zh">{status_zh}</span><span data-lang="en">{status_en}</span></div>
      </div>
      <div class="flow-diagram"><div class="flow-nodes">{nodes_html}</div></div>
      {jargon_html}
    </div>\n'''

    html += '  </div>\n'
    return html


def render_verifications(verifications):
    if not verifications:
        return ""

    html = f'''<div class="section">
    <div class="section-title"><span data-lang="zh">三、待验证清单（{len(verifications)}项）</span><span data-lang="en">3. Watchlist ({len(verifications)} items)</span></div>\n'''

    for idx, v in enumerate(verifications):
        title_en = v.get("title_en", v.get("title", ""))

        # Layer 1: core question
        layer1_zh = v.get("layer1", v.get("question", ""))
        layer1_en = v.get("layer1_en", v.get("question_en", layer1_zh))

        # Layer 2: variables to watch
        vars_zh = v.get("vars", v.get("layer2", []))
        vars_en = v.get("vars_en", vars_zh)

        vars_html = ""
        if isinstance(vars_zh, list):
            for i, var in enumerate(vars_zh):
                var_en = vars_en[i] if i < len(vars_en) else var
                vars_html += f"<li><span data-lang=\"zh\">{var}</span><span data-lang=\"en\">{var_en}</span></li>\n"
        elif isinstance(vars_zh, str):
            vars_html = f"<li><span data-lang=\"zh\">{vars_zh}</span><span data-lang=\"en\">{vars_en}</span></li>\n"

        html += f'''    <div class="verify-card">
      <div class="verify-title"><span data-lang="zh">🔍 待验证 {idx+1}：{v.get("title","")}</span><span data-lang="en">🔍 Watch {idx+1}: {title_en}</span></div>
      <div class="verify-layer">
        <div class="verify-layer-title"><span data-lang="zh">第一层：核心问题</span><span data-lang="en">Layer 1: Core Question</span></div>
        <ul class="verify-detail"><li><span data-lang="zh">{layer1_zh}</span><span data-lang="en">{layer1_en}</span></li></ul>
      </div>
      <div class="verify-layer">
        <div class="verify-layer-title"><span data-lang="zh">第二层：具体盯哪3-4个变量</span><span data-lang="en">Layer 2: Variables to Watch</span></div>
        <ul class="verify-detail">{vars_html}</ul>
      </div>
    </div>\n'''

    html += '  </div>\n'
    return html


def render_analogies(analogies):
    if not analogies:
        return ""

    html = f'''<div class="section">
    <div class="section-title"><span data-lang="zh">四、金融历史类比（{len(analogies)}个）</span><span data-lang="en">4. Historical Analogies ({len(analogies)})</span></div>\n'''

    for idx, a in enumerate(analogies):
        event_en = a.get("event_en", a.get("event", ""))
        lesson_en = a.get("lesson_en", a.get("lesson", ""))
        diff_en = a.get("diff_en", a.get("diff", ""))

        html += f'''    <div class="history-card">
      <div class="history-event"><span data-lang="zh">📜 类比 {idx+1}：{a.get("event","")}</span><span data-lang="en">📜 Analogy {idx+1}: {event_en}</span></div>
      <div class="history-lesson"><span data-lang="zh">{a.get("lesson","")}</span><span data-lang="en">{lesson_en}</span></div>
      <div class="history-diff"><span data-lang="zh">{a.get("diff","")}</span><span data-lang="en">{diff_en}</span></div>
    </div>\n'''

    html += '  </div>\n'
    return html


def build_page(data, base=""):
    tpl = HTML_TEMPLATE
    weekday_zh = data.get("weekday", "")
    weekday_en = translate_weekday(weekday_zh)

    events = data.get("events", [])
    chains = data.get("chains", [])
    verifications = data.get("verifications", [])
    analogies = data.get("historical_analogies", [])

    replacements = {
        "{{ date }}": data.get("date", ""),
        "{{ weekday_zh }}": weekday_zh,
        "{{ weekday_en }}": weekday_en,
        "{{ crawl_time }}": data.get("crawl_time", ""),
        "{{ source }}": data.get("source", ""),
        "{{ events_count }}": str(len(events)),
        "{{ chains_count }}": str(len(chains)),
        "{{ verifications_count }}": str(len(verifications)),
        "{{ stats_html }}": render_stats(data.get("stats", [])),
        "{{ four_column_html }}": render_four_column_table(data),
        "{{ chains_html }}": render_chains(chains),
        "{{ verifications_html }}": render_verifications(verifications),
        "{{ analogies_html }}": render_analogies(analogies),
        "{{ base }}": base,
    }
    for k, v in replacements.items():
        tpl = tpl.replace(k, v)
    return tpl


def build_history(dates):
    items = ""
    for d in dates:
        items += f'<li><a href="date/{d}.html">📅 {d}</a></li>\n'

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>历史归档 · Archive · 市场地图</title>
<style>
  :root {{ --bg:#0a0e17; --card:#131826; --border:#2a3344; --text:#e8ecf1; --text-dim:#8b95a7; --accent:#d4af37; }}
  [data-theme="light"] {{ --bg:#f5f7fa; --card:#fff; --border:#dde3ed; --text:#1a2030; --text-dim:#5a6478; --accent:#b8860b; }}
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
</style></head><body data-theme="dark" class="lang-zh"><div class="container">
<div class="nav">
  <a href="index.html"><span data-lang="zh">← 返回今日</span><span data-lang="en">← Back to Today</span></a>
  <button class="lang-toggle" onclick="toggleLang()">EN</button>
  <button class="lang-toggle" onclick="toggleTheme()">🌙/☀️</button>
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
function toggleTheme() {{
  var b = document.body;
  var c = b.getAttribute('data-theme');
  b.setAttribute('data-theme', c === 'dark' ? 'light' : 'dark');
  localStorage.setItem('theme', b.getAttribute('data-theme'));
}}
(function() {{
  if (localStorage.getItem('lang') === 'en') {{
    document.body.className = 'lang-en';
    document.querySelector('.lang-toggle').textContent = '中';
  }}
  var t = localStorage.getItem('theme');
  if (t) document.body.setAttribute('data-theme', t);
}})();
</script>
</div></body></html>'''


def build_rss(dates, all_data):
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
  <description>华尔街见闻要闻三层漏斗筛选 → 四列表 → 因果链 → 待验证 → 历史类比</description>
  <language>zh-CN</language>
  <lastBuildDate>{datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0800')}</lastBuildDate>
{items_xml}
</channel>
</rss>"""


def build_all():
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR)
    os.makedirs(os.path.join(OUTPUT_DIR, "date"))
    os.makedirs(os.path.join(OUTPUT_DIR, "api"))

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

    # 1. 首页
    latest_date = dates[0]
    latest_data = all_data[latest_date]
    index_html = build_page(latest_data, base="")
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"✅ 首页 → index.html ({latest_date})")

    # 2. 每日页面
    for d, data in all_data.items():
        page_html = build_page(data, base="../")
        with open(os.path.join(OUTPUT_DIR, "date", f"{d}.html"), "w", encoding="utf-8") as f:
            f.write(page_html)
        print(f"✅ 日期页 → date/{d}.html")

    # 3. 历史归档
    history_html = build_history(dates)
    with open(os.path.join(OUTPUT_DIR, "history.html"), "w", encoding="utf-8") as f:
        f.write(history_html)
    print("✅ 历史归档 → history.html")

    # 4. RSS
    rss_xml = build_rss(dates, all_data)
    with open(os.path.join(OUTPUT_DIR, "rss.xml"), "w", encoding="utf-8") as f:
        f.write(rss_xml)
    print("✅ RSS → rss.xml")

    # 5. JSON API
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


if __name__ == "__main__":
    build_all()
