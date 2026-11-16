#!/usr/bin/env python3
"""
静态构建脚本 - 将 data/*.json 渲染为静态 HTML
用于 Cloudflare Pages 部署（无需后端服务器）
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
<title>每日市场地图 · {{ date }}</title>
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
  .theme-toggle {
    background: var(--card-2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 12px;
    cursor: pointer;
    font-size: 14px;
    color: var(--text);
    transition: all 0.2s;
  }
  .theme-toggle:hover { border-color: var(--accent); }

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
    content: "☐";
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
<body data-theme="dark">

<div class="topbar">
  <div class="topbar-left">
    <div class="topbar-logo">📊 Macro Market Map</div>
    <div class="topbar-date">{{ date }} {{ weekday }}</div>
  </div>
  <div class="topbar-nav">
    <a href="/">今日</a>
    <a href="/history.html">历史归档</a>
    <a href="/rss.xml">RSS订阅</a>
    <a href="/api/latest.json">JSON API</a>
    <button class="theme-toggle" onclick="toggleTheme()">🌙/☀️</button>
  </div>
</div>

<div class="container">

  <div class="share-bar">
    <a class="share-btn" href="https://twitter.com/intent/tweet?text=每日市场地图 {{ date }}" target="_blank">🐦 Twitter</a>
    <a class="share-btn" href="https://service.weibo.com/share/share.php?title=每日市场地图 {{ date }}" target="_blank">📷 微博</a>
    <button class="share-btn" onclick="copyLink()">🔗 复制链接</button>
  </div>

  <!-- Stats -->
  <div class="stats-grid">
    {{ stats_html }}
  </div>

  <!-- Events -->
  <div class="section">
    <div class="section-title">📌 核心要闻（{{ events_count }}条）</div>
    {{ events_html }}
  </div>

  <!-- Chains -->
  <div class="section">
    <div class="section-title">🔗 因果链逐条拆解（{{ chains_count }}条）</div>
    {{ chains_html }}
  </div>

  <!-- Verifications -->
  <div class="section">
    <div class="section-title">🔍 待验证清单（{{ verifications_count }}条）</div>
    {{ verifications_html }}
  </div>

  <footer>
    <p>📊 本市场地图基于华尔街见闻快讯（{{ source }}）{{ date }} {{ crawl_time }}抓取内容生成</p>
    <p>三层漏斗：① 价格变动/新信息/宏观/资产相关 → ② 去重去噪 → ③ 保留{{ events_count }}条核心，{{ chains_count }}条因果链，{{ verifications_count }}条待验证</p>
    <p style="margin-top:8px; color: var(--text-dim);">⚠️ 仅供研究参考，不构成投资建议</p>
    <p style="margin-top:8px;">🤖 自动更新：GitHub Actions 每日13:00(UTC+8)自动抓取 → 构建 → 部署</p>
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

// Copy link
function copyLink() {
  navigator.clipboard.writeText(window.location.href).then(function() {
    alert('链接已复制！');
  });
}

// Auto refresh every 5 minutes
setTimeout(function() { location.reload(); }, 5 * 60 * 1000);
</script>
</body>
</html>'''


def render_stats(stats):
    html = ""
    for s in stats:
        dir_class = f"stat-{s.get('dir', 'neutral')}"
        html += f'''<div class="stat-card">
      <div class="stat-label">{s.get('label','')}</div>
      <div class="stat-value {dir_class}">{s.get('value','')}</div>
      <div class="stat-change">{s.get('change','')}</div>
    </div>\n'''
    return html


def render_events(events):
    html = ""
    for ev in events:
        tags_html = ""
        for tag in ev.get("tags", []):
            tags_html += f'<span class="tag tag-{tag["type"]}">{tag["text"]}</span>'

        dir = ev.get("dir", "neutral")
        dir_class = f"dir-{dir}"
        arrow = {"up": "📈", "down": "📉", "split": "⚖️", "neutral": "➡️"}.get(dir, "➡️")

        html += f'''<div class="event-card">
      <div class="event-tags">{tags_html}</div>
      <div class="event-text"><span class="dir-arrow {dir_class}">{arrow}</span> {ev.get("event","")}</div>
      <div class="event-assets"><strong>影响资产：</strong>{ev.get("assets","")}</div>
      <div class="event-logic">{ev.get("logic","")}</div>
    </div>\n'''
    return html


def render_chains(chains):
    html = ""
    for ch in chains:
        status = ch.get("status", "unverified")
        status_class = f"status-{status}"
        status_text = "市场共识" if status == "consensus" else "待验证"

        nodes_html = ""
        for i, node in enumerate(ch.get("nodes", [])):
            node_type = node.get("type", "normal")
            node_class = f"flow-node {node_type}"
            nodes_html += f'<div class="{node_class}">{node["text"]}</div>'
            if i < len(ch["nodes"]) - 1:
                nodes_html += '<div class="flow-arrow">→</div>'

        jargon_html = ""
        for j in ch.get("jargon", []):
            jargon_html += f'<div class="jargon-item"><span class="jargon-term">{j["term"]}</span>：<span class="jargon-explain">{j["explain"]}</span></div>\n'

        html += f'''<div class="chain-card">
      <div class="chain-title">{ch["title"]} <span class="chain-status {status_class}">{status_text}</span></div>
      <div class="flow-nodes">{nodes_html}</div>
      <div class="jargon-list">{jargon_html}</div>
    </div>\n'''
    return html


def render_verifications(verifications):
    html = ""
    for v in verifications:
        vars_html = ""
        for var in v.get("vars", []):
            vars_html += f"<li>{var}</li>\n"

        html += f'''<div class="verify-card">
      <div class="verify-title">{v["title"]}</div>
      <ul class="verify-list">{vars_html}</ul>
      <div class="analogy"><strong>📖 历史类比：</strong>{v.get("analogy_title","")} — {v.get("analogy_text","")}</div>
      <div class="lesson">💡 <strong>教训：</strong>{v.get("lesson","")}</div>
      <div class="diff">⚡ <strong>关键区别：</strong>{v.get("diff","")}</div>
    </div>\n'''
    return html


def build_page(data):
    """渲染单日数据为 HTML"""
    tpl = HTML_TEMPLATE
    replacements = {
        "{{ date }}": data.get("date", ""),
        "{{ weekday }}": data.get("weekday", ""),
        "{{ crawl_time }}": data.get("crawl_time", ""),
        "{{ source }}": data.get("source", ""),
        "{{ events_count }}": str(len(data.get("events", []))),
        "{{ chains_count }}": str(len(data.get("chains", []))),
        "{{ verifications_count }}": str(len(data.get("verifications", []))),
        "{{ stats_html }}": render_stats(data.get("stats", [])),
        "{{ events_html }}": render_events(data.get("events", [])),
        "{{ chains_html }}": render_chains(data.get("chains", [])),
        "{{ verifications_html }}": render_verifications(data.get("verifications", [])),
    }
    for k, v in replacements.items():
        tpl = tpl.replace(k, v)
    return tpl


def build_history(dates):
    """构建历史归档页"""
    items = ""
    for d in dates:
        items += f'<li><a href="/date/{d}.html">📅 {d}</a></li>\n'

    return f'''<!DOCTYPE html>
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
  <link>https://market-map.pages.dev/date/{d}.html</link>
  <description><![CDATA[{description}]]></description>
  <pubDate>{d}T13:00:00+08:00</pubDate>
  <guid>https://market-map.pages.dev/date/{d}.html</guid>
</item>
"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>每日市场地图 · Macro Market Map</title>
  <link>https://market-map.pages.dev</link>
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
    index_html = build_page(latest_data)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"✅ 首页 → index.html ({latest_date})")

    # 2. 构建每日页面
    for d, data in all_data.items():
        page_html = build_page(data)
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
