"""
每日市场地图 - 数据驱动渲染引擎
从 data/ 目录读取 JSON 数据，渲染为完整 HTML 页面
"""

import json
import os
import glob
from datetime import datetime, date
from flask import Flask, render_template_string, jsonify, send_from_directory

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日市场地图 · {{ data.date }}</title>
<style>
  :root {
    --bg: #0a0e17;
    --card: #131826;
    --card-2: #1a2030;
    --border: #2a3344;
    --text: #e8ecf1;
    --text-dim: #8b95a7;
    --accent: #d4af37;
    --red: #e74c3c;
    --green: #2ecc71;
    --neutral: #95a5a6;
    --split: #f39c12;
    --blue: #3498db;
    --purple: #9b59b6;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 0;
  }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px 20px 60px; }

  /* Top bar */
  .topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    flex-wrap: wrap;
    gap: 12px;
  }
  .topbar-left {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .topbar-logo {
    font-size: 22px;
    font-weight: 700;
    color: var(--accent);
  }
  .topbar-date {
    color: var(--text-dim);
    font-size: 14px;
  }
  .topbar-nav {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }
  .topbar-nav a {
    color: var(--text-dim);
    text-decoration: none;
    font-size: 13px;
    padding: 5px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    transition: all 0.2s;
  }
  .topbar-nav a:hover {
    color: var(--accent);
    border-color: var(--accent);
  }
  .topbar-nav a.active {
    color: var(--accent);
    border-color: var(--accent);
    background: rgba(212,175,55,0.1);
  }

  /* Header */
  .header {
    background: linear-gradient(135deg, #1a1f2e 0%, #0d1117 100%);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 28px 32px;
    margin-bottom: 28px;
    position: relative;
    overflow: hidden;
  }
  .header::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--accent), var(--red), var(--green), var(--blue));
  }
  .header h1 { font-size: 26px; font-weight: 700; margin-bottom: 6px; letter-spacing: 0.5px; }
  .header .subtitle { color: var(--text-dim); font-size: 14px; }
  .header .meta { display: flex; gap: 20px; margin-top: 14px; flex-wrap: wrap; }
  .meta-item {
    background: var(--card-2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 12px;
    font-size: 12px;
    color: var(--text-dim);
  }
  .meta-item strong { color: var(--accent); }

  /* Section titles */
  .section-title {
    font-size: 20px;
    font-weight: 700;
    margin: 36px 0 16px;
    padding-left: 14px;
    border-left: 4px solid var(--accent);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .section-title .badge {
    font-size: 11px;
    background: var(--card-2);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 8px;
    color: var(--text-dim);
    font-weight: 400;
  }

  /* Four-column table */
  .table-wrap { overflow-x: auto; border-radius: 10px; border: 1px solid var(--border); }
  table.market-table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 800px; }
  .market-table th {
    background: var(--card-2); color: var(--accent);
    padding: 12px 14px; text-align: left; font-weight: 600;
    border-bottom: 2px solid var(--border); white-space: nowrap;
  }
  .market-table td { padding: 12px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
  .market-table tr:last-child td { border-bottom: none; }
  .market-table tr:hover { background: var(--card-2); }
  .market-table .col-event { width: 32%; }
  .market-table .col-asset { width: 20%; }
  .market-table .col-dir { width: 12%; }
  .market-table .col-logic { width: 36%; }

  .dir-up { color: var(--red); font-weight: 600; }
  .dir-down { color: var(--green); font-weight: 600; }
  .dir-neutral { color: var(--neutral); font-weight: 600; }
  .dir-split { color: var(--split); font-weight: 600; }

  .tag {
    display: inline-block; font-size: 11px;
    padding: 1px 7px; border-radius: 3px;
    margin-right: 4px; margin-bottom: 2px;
  }
  .tag-macro { background: rgba(52,152,219,0.15); color: var(--blue); border: 1px solid rgba(52,152,219,0.3); }
  .tag-ai { background: rgba(155,89,182,0.15); color: var(--purple); border: 1px solid rgba(155,89,182,0.3); }
  .tag-energy { background: rgba(243,156,18,0.15); color: var(--split); border: 1px solid rgba(243,156,18,0.3); }
  .tag-fed { background: rgba(212,175,55,0.15); color: var(--accent); border: 1px solid rgba(212,175,55,0.3); }
  .tag-china { background: rgba(231,76,60,0.15); color: var(--red); border: 1px solid rgba(231,76,60,0.3); }
  .tag-bio { background: rgba(46,204,113,0.15); color: var(--green); border: 1px solid rgba(46,204,113,0.3); }

  /* Causal chains */
  .chain-card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 0; margin-bottom: 22px; overflow: hidden;
  }
  .chain-header {
    padding: 14px 20px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 8px;
  }
  .chain-title { font-size: 15px; font-weight: 600; color: var(--text); }
  .chain-status { font-size: 11px; padding: 3px 10px; border-radius: 4px; font-weight: 600; }
  .status-consensus { background: rgba(46,204,113,0.15); color: var(--green); border: 1px solid rgba(46,204,113,0.3); }
  .status-unverified { background: rgba(243,156,18,0.15); color: var(--split); border: 1px solid rgba(243,156,18,0.3); }
  .chain-body { padding: 18px 20px; }

  /* Flow diagram */
  .flow {
    display: flex; align-items: flex-start; flex-wrap: wrap;
    gap: 0; padding: 8px 0 16px; overflow-x: auto;
  }
  .flow-node {
    background: var(--card-2); border: 1px solid var(--border);
    border-radius: 8px; padding: 10px 14px; font-size: 12.5px;
    min-width: 120px; max-width: 200px; text-align: center;
    flex-shrink: 0; line-height: 1.4;
  }
  .flow-node.trigger { border-color: var(--accent); border-width: 2px; }
  .flow-node.result-up { border-color: var(--red); border-width: 2px; }
  .flow-node.result-down { border-color: var(--green); border-width: 2px; }
  .flow-arrow {
    display: flex; align-items: center; color: var(--text-dim);
    font-size: 20px; padding: 0 6px; flex-shrink: 0; align-self: center;
  }

  /* Jargon */
  .jargon-box {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px 18px; margin-top: 10px;
  }
  .jargon-title {
    font-size: 12px; color: var(--accent); font-weight: 600;
    margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px;
  }
  .jargon-item { margin-bottom: 8px; font-size: 13px; padding-left: 18px; position: relative; }
  .jargon-item::before { content: '\\25B8'; position: absolute; left: 0; color: var(--accent); }
  .jargon-term { color: var(--blue); font-weight: 600; }
  .jargon-item:last-child { margin-bottom: 0; }

  /* Verification */
  .verify-card {
    background: var(--card); border: 1px solid var(--border);
    border-left: 4px solid var(--split); border-radius: 8px;
    padding: 16px 20px; margin-bottom: 16px;
  }
  .verify-title { font-size: 14px; font-weight: 600; margin-bottom: 10px; color: var(--text); }
  .verify-section { margin-bottom: 12px; }
  .verify-section:last-child { margin-bottom: 0; }
  .verify-label {
    font-size: 11px; color: var(--split); font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;
  }
  .verify-vars { display: flex; gap: 8px; flex-wrap: wrap; }
  .verify-var {
    background: var(--card-2); border: 1px solid var(--border);
    border-radius: 4px; padding: 4px 10px; font-size: 12px; color: var(--text-dim);
  }
  .verify-analogy { font-size: 13px; color: var(--text-dim); padding-left: 18px; position: relative; line-height: 1.5; }
  .verify-analogy::before { content: '\\1F4DC'; position: absolute; left: 0; top: 0; }
  .analogy-lesson { color: var(--red); font-weight: 600; }
  .analogy-diff { color: var(--green); }

  /* Stats */
  .stats-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px; margin-bottom: 24px;
  }
  .stat-card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px 16px;
  }
  .stat-label { font-size: 11px; color: var(--text-dim); margin-bottom: 4px; }
  .stat-value { font-size: 18px; font-weight: 700; }
  .stat-change { font-size: 12px; margin-top: 2px; }

  /* History list */
  .history-list {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 20px 24px; margin-bottom: 28px;
  }
  .history-list h3 { font-size: 16px; margin-bottom: 14px; color: var(--accent); }
  .history-list ul { list-style: none; }
  .history-list li { margin-bottom: 8px; }
  .history-list a {
    color: var(--text-dim); text-decoration: none; font-size: 14px;
    transition: color 0.2s;
  }
  .history-list a:hover { color: var(--accent); }

  /* Live indicator */
  .live-dot {
    display: inline-block; width: 8px; height: 8px;
    background: var(--green); border-radius: 50%;
    margin-right: 6px; animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  /* Auto-refresh banner */
  .refresh-banner {
    background: rgba(46,204,113,0.1);
    border: 1px solid rgba(46,204,113,0.3);
    border-radius: 8px;
    padding: 10px 16px;
    margin-bottom: 20px;
    font-size: 13px;
    color: var(--green);
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
  }

  footer {
    margin-top: 40px; padding-top: 20px;
    border-top: 1px solid var(--border);
    text-align: center; color: var(--text-dim); font-size: 12px;
  }

  /* Light theme overrides */
  body.light {
    --bg: #f5f6f8;
    --card: #ffffff;
    --card-2: #eef1f5;
    --border: #d4d9e0;
    --text: #1a1f2e;
    --text-dim: #5a6478;
  }

  /* Theme toggle button */
  .theme-toggle {
    background: var(--card-2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 6px 14px;
    cursor: pointer;
    font-size: 14px;
    color: var(--text);
    transition: all 0.2s;
  }
  .theme-toggle:hover { border-color: var(--accent); color: var(--accent); }

  /* Share buttons */
  .share-bar {
    display: flex;
    gap: 10px;
    margin-top: 16px;
    flex-wrap: wrap;
  }
  .share-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 6px 14px;
    border: 1px solid var(--border);
    border-radius: 8px;
    font-size: 12px;
    color: var(--text-dim);
    text-decoration: none;
    cursor: pointer;
    transition: all 0.2s;
  }
  .share-btn:hover { border-color: var(--accent); color: var(--accent); }

  /* Mobile responsive */
  @media (max-width: 768px) {
    .container { padding: 12px 12px 40px; }
    .header { padding: 20px 18px; border-radius: 10px; margin-bottom: 18px; }
    .header h1 { font-size: 20px; }
    .header .subtitle { font-size: 12px; }
    .meta-item { font-size: 11px; padding: 3px 8px; }
    .section-title { font-size: 17px; margin: 24px 0 12px; padding-left: 10px; border-left-width: 3px; }
    .section-title .badge { font-size: 10px; }
    .stats-row { grid-template-columns: repeat(2, 1fr); gap: 8px; }
    .stat-card { padding: 10px 12px; }
    .stat-label { font-size: 10px; }
    .stat-value { font-size: 16px; }
    .stat-change { font-size: 10px; }
    .market-table { min-width: 600px; font-size: 12px; }
    .market-table th, .market-table td { padding: 8px 10px; }
    .chain-header { padding: 10px 14px; }
    .chain-title { font-size: 14px; }
    .chain-body { padding: 12px 14px; }
    .flow-node { min-width: 90px; max-width: 140px; font-size: 11px; padding: 8px 10px; }
    .flow-arrow { font-size: 16px; padding: 0 3px; }
    .jargon-box { padding: 10px 14px; }
    .jargon-item { font-size: 12px; padding-left: 14px; }
    .verify-card { padding: 12px 14px; }
    .verify-title { font-size: 13px; }
    .verify-var { font-size: 11px; padding: 3px 8px; }
    .verify-analogy { font-size: 12px; }
    .topbar { flex-direction: column; align-items: flex-start; }
    .topbar-nav { width: 100%; }
    .topbar-nav a { flex: 1; text-align: center; font-size: 12px; }
    .refresh-banner { font-size: 11px; }
    footer p { font-size: 11px; }
  }
</style>
</head>
<body>
<div class="container">

  <!-- Top bar -->
  <div class="topbar">
    <div class="topbar-left">
      <div class="topbar-logo">📊 Macro Market Map</div>
      <div class="topbar-date">{{ today }}</div>
    </div>
    <div class="topbar-nav">
      <a href="/">今日</a>
      <a href="/history">历史归档</a>
      <a href="/rss">RSS</a>
      <a href="/api/latest">API</a>
      <button class="theme-toggle" onclick="toggleTheme()">🌙/☀️</button>
    </div>
  </div>

  {% if data %}
  <!-- Auto-refresh banner -->
  <div class="refresh-banner">
    <span><span class="live-dot"></span> 自动更新已启用 · 数据日期：<strong>{{ data.date }}</strong> · 下次刷新：<span id="next-refresh">--:--:--</span></span>
    <span style="color: var(--text-dim);">数据源：{{ data.source }}</span>
  </div>

  <!-- Header -->
  <div class="header">
    <h1>📊 每日市场地图 · Macro Market Map</h1>
    <div class="subtitle">华尔街见闻要闻三层漏斗筛选 → 四列表骨架 → 因果链拆解 → 待验证清单</div>
    <div class="meta">
      <div class="meta-item">📅 <strong>{{ data.date }} {{ data.weekday }}</strong></div>
      <div class="meta-item">📡 数据源：<strong>{{ data.source }}</strong></div>
      <div class="meta-item">🕐 抓取时间：{{ data.crawl_time }}</div>
      <div class="meta-item">🎯 筛选结果：<strong>{{ data.filter_result }}</strong></div>
    </div>
  </div>

  <!-- Summary Stats -->
  <div class="stats-row">
    {% for stat in data.stats %}
    <div class="stat-card">
      <div class="stat-label">{{ stat.label }}</div>
      <div class="stat-value dir-{{ stat.dir }}">{{ stat.value }}</div>
      <div class="stat-change dir-{{ stat.dir }}">{{ stat.change }}</div>
    </div>
    {% endfor %}
  </div>

  <!-- Four-column table -->
  <div class="section-title">
    一、四列表：事件 × 资产 × 方向 × 传导逻辑
    <span class="badge">三层漏斗后保留{{ data.events | length }}条核心</span>
  </div>

  <div class="table-wrap">
    <table class="market-table">
      <thead>
        <tr>
          <th class="col-event">事件</th>
          <th class="col-asset">影响资产</th>
          <th class="col-dir">方向</th>
          <th class="col-logic">传导逻辑</th>
        </tr>
      </thead>
      <tbody>
        {% for ev in data.events %}
        <tr>
          <td class="col-event">
            {% for tag in ev.tags %}
            <span class="tag tag-{{ tag.type }}">{{ tag.text }}</span>
            {% endfor %}
            <br>{{ ev.event }}
          </td>
          <td class="col-asset">{{ ev.assets }}</td>
          <td class="col-dir"><span class="dir-{{ ev.dir }}">{{ {'up':'涨','down':'跌','neutral':'中性','split':'分化'}[ev.dir] }}</span></td>
          <td class="col-logic">{{ ev.logic }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Causal Chains -->
  <div class="section-title">
    二、因果链逐条拆解
    <span class="badge">{{ data.chains | length }}条 · 按当日实际重要性排序</span>
  </div>

  {% for chain in data.chains %}
  <div class="chain-card">
    <div class="chain-header">
      <div class="chain-title">{{ chain.title }}</div>
      <span class="chain-status status-{{ chain.status }}">{{ {'consensus':'市场共识','unverified':'待验证'}[chain.status] }}</span>
    </div>
    <div class="chain-body">
      <div class="flow">
        {% for node in chain.nodes %}
        {% if not loop.first %}
        <div class="flow-arrow">→</div>
        {% endif %}
        <div class="flow-node {{ node.type }}">{{ node.text | safe }}</div>
        {% endfor %}
      </div>
      <div class="jargon-box">
        <div class="jargon-title">术语白话</div>
        {% for item in chain.jargon %}
        <div class="jargon-item"><span class="jargon-term">{{ item.term }}</span>：{{ item.explain }}</div>
        {% endfor %}
      </div>
    </div>
  </div>
  {% endfor %}

  <!-- Verification List -->
  <div class="section-title">
    三、待验证清单
    <span class="badge">每条含：盯什么变量 + 历史类比</span>
  </div>

  {% for v in data.verifications %}
  <div class="verify-card">
    <div class="verify-title">{{ v.title }}</div>
    <div class="verify-section">
      <div class="verify-label">需盯变量（{{ v.vars | length }}个）</div>
      <div class="verify-vars">
        {% for var in v.vars %}
        <div class="verify-var">{{ var }}</div>
        {% endfor %}
      </div>
    </div>
    <div class="verify-section">
      <div class="verify-label">金融历史类比</div>
      <div class="verify-analogy">
        📜 <strong>{{ v.analogy_title }}</strong>：{{ v.analogy_text }}
        <span class="analogy-lesson">{{ v.lesson }}</span>
        <span class="analogy-diff">{{ v.diff }}</span>
      </div>
    </div>
  </div>
  {% endfor %}

  <footer>
    <p>📊 本市场地图基于华尔街见闻快讯（{{ data.source }}）{{ data.date }} {{ data.crawl_time }}抓取内容生成</p>
    <p>三层漏斗：① 价格变动/新信息/宏观/资产相关 → ② 去重去噪 → ③ 保留{{ data.events | length }}条核心，{{ data.chains | length }}条因果链，{{ data.verifications | length }}条待验证</p>
    <p style="margin-top:8px; color: var(--text-dim);">⚠️ 仅供研究参考，不构成投资建议。因果链标注[市场共识]或[待验证]供独立判断。</p>
    <div class="share-bar">
      <a class="share-btn" href="https://twitter.com/intent/tweet?text=每日市场地图 {{ data.date }}&url={{ request.url }}" target="_blank">🐦 分享</a>
      <a class="share-btn" href="https://service.weibo.com/share/share.php?title=每日市场地图 {{ data.date }}" target="_blank">📱 微博</a>
      <a class="share-btn" onclick="copyLink('{{ request.url }}')" href="javascript:void(0)">📋 复制链接</a>
      <a class="share-btn" href="/rss">📡 RSS订阅</a>
    </div>
  </footer>
  {% else %}
  <div class="header">
    <h1>📊 每日市场地图</h1>
    <div class="subtitle">今日数据尚未生成，请稍后再来</div>
  </div>
  {% endif %}

</div>

<script>
// Auto-refresh: every 5 minutes reload the page
var REFRESH_INTERVAL = 5 * 60 * 1000;
var nextRefreshTime = Date.now() + REFRESH_INTERVAL;

function updateCountdown() {
  var remaining = nextRefreshTime - Date.now();
  if (remaining <= 0) { location.reload(); return; }
  var h = String(Math.floor(remaining / 3600000)).padStart(2, '0');
  var m = String(Math.floor((remaining % 3600000) / 60000)).padStart(2, '0');
  var s = String(Math.floor((remaining % 60000) / 1000)).padStart(2, '0');
  var el = document.getElementById('next-refresh');
  if (el) el.textContent = h + ':' + m + ':' + s;
}
setInterval(updateCountdown, 1000);
updateCountdown();

// Theme toggle
function toggleTheme() {
  document.body.classList.toggle('light');
  var isLight = document.body.classList.contains('light');
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
}
(function() {
  var saved = localStorage.getItem('theme');
  if (saved === 'light') document.body.classList.add('light');
})();

// Copy link
function copyLink(url) {
  navigator.clipboard.writeText(url).then(function() {
    alert('链接已复制: ' + url);
  });
}
</script>
</body>
</html>'''


def get_available_dates():
    """获取所有可用日期列表，按日期倒序排列"""
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    dates = []
    for f in files:
        basename = os.path.basename(f)
        date_str = basename.replace(".json", "")
        if len(date_str) == 10 and date_str[4] == '-' and date_str[7] == '-':
            dates.append(date_str)
    dates.sort(reverse=True)
    return dates


def get_latest_data():
    """获取最新日期的数据"""
    dates = get_available_dates()
    if not dates:
        return None
    latest = dates[0]
    filepath = os.path.join(DATA_DIR, latest + ".json")
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_data_by_date(date_str):
    """获取指定日期的数据"""
    filepath = os.path.join(DATA_DIR, date_str + ".json")
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


@app.route('/')
def index():
    """首页：显示最新一期市场地图"""
    data = get_latest_data()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template_string(TEMPLATE, data=data, today=today)


@app.route('/date/<date_str>')
def view_by_date(date_str):
    """查看指定日期的数据"""
    data = get_data_by_date(date_str)
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template_string(TEMPLATE, data=data, today=today)


@app.route('/history')
def history():
    """历史归档列表"""
    dates = get_available_dates()
    today = datetime.now().strftime('%Y-%m-%d')
    items = ""
    for d in dates:
        items += f'<li><a href="/date/{d}">📅 {d}</a></li>'
    html = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>历史归档 · 市场地图</title>
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
</style></head><body><div class="container">
<div class="nav"><a href="/">← 返回今日</a></div>
<h1>📅 历史归档</h1>
<div class="card"><ul>{items}</ul></div>
</div></body></html>'''
    return html


@app.route('/api/latest')
def api_latest():
    """JSON API：获取最新数据"""
    data = get_latest_data()
    if data is None:
        return jsonify({"error": "No data available"}), 404
    return jsonify(data)


@app.route('/api/date/<date_str>')
def api_by_date(date_str):
    """JSON API：获取指定日期数据"""
    data = get_data_by_date(date_str)
    if data is None:
        return jsonify({"error": f"No data for {date_str}"}), 404
    return jsonify(data)


@app.route('/api/dates')
def api_dates():
    """JSON API：获取所有可用日期列表"""
    dates = get_available_dates()
    return jsonify({"dates": dates})


@app.route('/rss')
def rss_feed():
    """RSS 订阅源"""
    dates = get_available_dates()
    items_xml = ""
    for d in dates[:30]:
        data = get_data_by_date(d)
        if not data:
            continue
        title = f"每日市场地图 · {data.get('date', d)}"
        desc_parts = []
        for ev in data.get("events", [])[:5]:
            desc_parts.append(ev.get("event", ""))
        description = " | ".join(desc_parts)[:300]
        link = f"https://your-domain.com/date/{d}"
        items_xml += f"""<item>
  <title>{title}</title>
  <link>{link}</link>
  <description><![CDATA[{description}]]></description>
  <pubDate>{d}T13:00:00+08:00</pubDate>
  <guid>{link}</guid>
</item>
"""

    rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>每日市场地图 · Macro Market Map</title>
  <link>https://your-domain.com</link>
  <description>华尔街见闻要闻三层漏斗筛选 → 四列表 → 因果链 → 待验证</description>
  <language>zh-CN</language>
  <lastBuildDate>{datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0800')}</lastBuildDate>
{items_xml}
</channel>
</rss>"""
    return rss_xml, 200, {'Content-Type': 'application/xml; charset=utf-8'}


if __name__ == '__main__':
    os.makedirs(DATA_DIR, exist_ok=True)
    print("=" * 50)
    print("  每日市场地图 - Web 服务启动")
    print(f"  数据目录: {DATA_DIR}")
    print(f"  可用日期: {get_available_dates()}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)
