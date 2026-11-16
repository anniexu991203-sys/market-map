# 每日市场地图 · Macro Market Map

> 数据驱动的每日市场要闻可视化网站，支持自动更新、历史归档、JSON API、RSS 订阅

## 📁 项目结构

```
market-map-site/
├── app.py                    # Flask Web 服务（本地开发用）
├── data/                     # 每日数据（JSON 格式）
│   └── 2026-11-16.json       # 示例数据
├── scripts/
│   ├── update_daily.py       # 自动抓取+三层漏斗筛选脚本
│   └── build_static.py       # 静态构建脚本（生成 public/ 目录）
├── public/                   # 静态网站输出（构建后生成）
│   ├── index.html            # 首页
│   ├── date/                 # 按日期归档
│   ├── history.html          # 历史列表
│   ├── rss.xml               # RSS 订阅
│   └── api/                  # JSON API（静态文件）
├── .github/workflows/
│   └── daily-update.yml      # GitHub Actions 每日自动部署
├── Dockerfile                # Docker 部署
└── README.md
```

## 🚀 部署方式

### 方式一：Cloudflare Pages（推荐，免费永久）

1. 注册 Cloudflare 账号
2. 获取 API Token：https://dash.cloudflare.com/profile/api-tokens
3. 创建 GitHub 仓库并推送代码
4. 在 GitHub 仓库 Settings → Secrets 添加：
   - `CLOUDFLARE_API_TOKEN` = 你的 Cloudflare API Token
   - `CLOUDFLARE_ACCOUNT_ID` = 你的 Cloudflare Account ID
5. GitHub Actions 会自动在每日 13:00（北京时间）抓取数据 → 构建静态网站 → 部署到 Cloudflare Pages
6. 访问 `https://market-map.pages.dev` 即可

### 方式二：本地运行

```bash
cd market-map-site
pip3 install -r requirements.txt
python3 app.py    # → http://localhost:5000
```

### 方式三：Docker

```bash
docker build -t market-map .
docker run -d -p 5000:5000 market-map
```

## 📡 端点列表

| 路由 | 说明 |
|------|------|
| `GET /` | 首页（最新一期市场地图） |
| `GET /date/YYYY-MM-DD.html` | 指定日期查看 |
| `GET /history.html` | 历史归档列表 |
| `GET /rss.xml` | RSS 2.0 订阅源 |
| `GET /api/latest.json` | 最新数据 JSON |
| `GET /api/dates.json` | 所有可用日期列表 |
| `GET /api/YYYY-MM-DD.json` | 指定日期 JSON |

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| **数据驱动渲染** | HTML 从 JSON 读取数据，更新 JSON 即更新页面 |
| **三层漏斗筛选** | 200+ 关键词过滤 → MD5 去重 → 重要性打分排序 |
| **LLM 智能结构化** | 设置 `LLM_API_KEY` 后自动提取因果链/术语白话/待验证清单 |
| **暗/亮色切换** | 右上角按钮一键切换，localStorage 记忆偏好 |
| **RSS 订阅** | 标准 RSS 2.0，可用 Feedly 等订阅 |
| **分享按钮** | Twitter、微博、复制链接 |
| **手机适配** | 全组件响应式布局 |
| **自动刷新** | 页面每 5 分钟自动重载 |
| **GitHub Actions** | 每日自动抓取 → 构建 → 部署 |

## 🔄 每日自动更新流程

```
GitHub Actions (UTC 05:00 = 北京时间 13:00)
        │
        ▼
  scripts/update_daily.py
  ├── 1. 抓取华尔街见闻快讯（API → RSS → 页面 三路兜底）
  ├── 2. 三层漏斗筛选
  │     ├── 200+ 市场关键词过滤
  │     ├── MD5 去重去噪
  │     └── 重要性打分排序（含数字+5分，涨跌词+3分）
  ├── 3. LLM 结构化（可选，设置 LLM_API_KEY）
  │     ├── 提取事件/因果链/术语白话
  │     └── 待验证清单+历史类比
  └── 4. 保存 JSON 到 data/
        │
        ▼
  scripts/build_static.py
  ├── 读取 data/*.json
  ├── 渲染静态 HTML
  └── 输出到 public/
        │
        ▼
  Cloudflare Pages 部署
  → https://market-map.pages.dev
```

## ⚙️ 配置说明

### 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `LLM_API_KEY` | 否 | LLM API 密钥（用于智能结构化，不设则用规则兜底） |
| `CLOUDFLARE_API_TOKEN` | 仅 CF Pages 部署 | Cloudflare API Token |
| `CLOUDFLARE_ACCOUNT_ID` | 仅 CF Pages 部署 | Cloudflare Account ID |

### Cron 定时（本地服务器）

```cron
# 每个交易日13:00自动抓取+构建
0 13 * * 1-5 cd /path/to/market-map-site && python3 scripts/update_daily.py && python3 scripts/build_static.py >> logs/update.log 2>&1
```

## ⚠️ 注意事项

1. **抓取脚本需适配**：`update_daily.py` 的 CSS 选择器需要根据华尔街见闻实际页面结构调整
2. **LLM 可选**：不设 `LLM_API_KEY` 时自动降级为规则兜底方案
3. **仅供研究参考，不构成投资建议**
