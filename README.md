# 🛰️ AI 项目信息收集平台

每天自动抓取**国内外最新的大模型与 AI 项目**，自动分类、评分，并生成一份精美的 **HTML 每日精选报告**。

纯 Python 标准库 + `requests` 实现，无需任何 API Key，开箱即用。

## 功能一览

| 能力 | 说明 |
|---|---|
| 自动抓取 | GitHub 热门新仓库、HuggingFace 热门模型/Spaces、arXiv 最新论文、AI Hot 每日精选（含中文提炼摘要）、IT之家、爱范儿、TechCrunch AI、The Verge、Hacker News |
| 自动分类 | 中英文关键词规则，分为 7 类：大模型发布 / 智能体与应用 / 多模态生成 / 开源项目与工具 / 研究前沿 / 政策与安全 / 行业动态 |
| 英文自动翻译 | 英文标题/摘要自动译为中文（配置 LLM 用 LLM 批量翻译，否则走 Google 免费接口，失败保留原文） |
| 事件合并 | 标题相似度聚类，同一事件的多家报道合并为一张卡片，折叠展示「相关报道」 |
| 热度评分 | 综合 Star/下载量/点赞/站点评分（对数刻度）+ 新鲜度 + 来源权重 + 日增星加成，归一化为 20~100 分 |
| 增量洞察 | 每日记录 GitHub star 快照，计算日增星排行；自动生成滚动 7 天周报（收录趋势 / 本周热门 / 周增星榜 / 分类分布） |
| 源健康监控 | 记录每个数据源的成功/失败状态，连续失败 ≥3 天在报告页脚红色告警 |
| URL 去重 | SQLite 存储，重复运行不会产生重复条目，指标会自动更新 |
| 每日摘要 | 独立单文件 HTML（今日综述或热词、「今日精选 TOP8」、分类板块、信源下拉筛选、关键词搜索、深色模式），零外部依赖可直接分享 |
| 定时任务 | 内置每日定时循环，或用 Windows 计划任务 |

## 快速开始

```bash
# 立即执行一次并生成今日报告
python main.py --once

# 执行完成后自动用浏览器打开
python main.py --once --open

# 常驻模式：启动时先跑一次，之后每天 08:30 自动执行（时间可在 config.py 修改）
python main.py --loop
```

报告输出在 `reports/` 目录：

- `daily_YYYY-MM-DD.html` — 当日精选日报
- `weekly.html` — 近 7 天周报（收录趋势 / 本周热门 / GitHub 周增星榜）
- `index.html` — 历史报告列表

> 说明：GitHub 日增星/周增星统计从第二次运行开始生效——首次运行只记录基线快照。

## 设置每天自动运行

### 方式一：Windows 计划任务（推荐，关机后次日自动补跑）

在命令行执行一次即可注册每天 08:30 的任务：

```bat
schtasks /Create /TN "AI每日情报" /TR "\"H:\AI project\demo3\run_daily.bat\"" /SC DAILY /ST 08:30
```

删除任务：`schtasks /Delete /TN "AI每日情报" /F`

### 方式二：内置定时循环

保持一个终端窗口常驻运行 `python main.py --loop`。

## 可选增强：接入大模型

编辑 `config.py`，填入任意 OpenAI 兼容接口：

```python
LLM_API_BASE = "https://api.openai.com/v1"
LLM_API_KEY  = "sk-xxx"
LLM_MODEL    = "gpt-4o-mini"
```

配置后自动启用三项能力（未配置时分别回退为本地方案，完全离线可用）：

1. **今日综述**：每天基于热度 TOP20 生成一段编辑视角的中文导读，展示在日报头部
2. **摘要润色**：热度最高的条目改写为更精炼的中文一句话摘要
3. **英文翻译**：英文标题/摘要批量翻译为中文（质量优于 Google 兜底）

## 自定义

- **增删数据源**：编辑 `config.py` 中的 `SOURCES` 列表（支持 RSS/Atom 通用格式）
- **调整分类**：修改 `CATEGORIES` 与 `KEYWORDS`
- **GitHub 配额**：未认证限流较严，可在 `config.GITHUB_TOKEN` 填入个人 Token 提升配额
- **HuggingFace 直连失败**：程序会自动切换到 `hf-mirror.com` 镜像，无需配置
- **AI Hot 精选源**：抓取 aihot.virxact.com 的精选条目（含中文提炼摘要、原始信源与站点评分），同一文章若与其它源的 URL 重复，会自动以该源的精炼版本覆盖

## 目录结构

```
demo3/
├── main.py          # 入口：--once / --loop，串联全流程
├── config.py        # 数据源、关键词、阈值等全部配置
├── collector.py     # 抓取模块（GitHub/HF/arXiv/RSS/AI Hot），逐源上报健康状态
├── classifier.py    # 分类、评分、摘要、LLM 综述与润色、热词
├── translator.py    # 英文自动翻译（LLM 优先 / Google 兜底）
├── cluster.py       # 标题相似度事件聚类（相关报道合并）
├── storage.py       # SQLite：条目去重、star 快照、源健康、周查询
├── report.py        # HTML 日报 + 周报 + 索引页生成
├── run_daily.bat    # 计划任务入口
├── data/            # ai_news.db 数据库（自动生成）
├── reports/         # HTML 报告输出
└── logs/            # 运行日志
```

## 常见问题

- **某几个源抓取失败？** 正常现象——部分站点有反爬或网络波动，程序会对每个数据源独立容错，其余源不受影响。
- **想看某天的历史数据？** 直接打开 `reports/daily_日期.html`，所有已抓取内容都在 SQLite 中永久保留。

## 🚀 部署到 GitHub Pages（云端全自动）

仓库已内置 GitHub Actions 工作流（`.github/workflows/daily.yml`）：**每天北京时间 08:00** 自动抓取 → 翻译 → 生成报告 → 发布网站，不依赖本机开机。

### 首次部署步骤

1. 在 GitHub 上新建一个**公开**空仓库（不要勾选 README / .gitignore）。
2. 本地推送：
   ```bash
   git init -b main
   git add .
   git commit -m "init: AI 项目情报站"
   git remote add origin https://github.com/<用户名>/<仓库名>.git
   git push -u origin main
   ```
3. 开启 Pages：仓库 **Settings → Pages → Build and deployment → Source 选择「GitHub Actions」**。
4. 到 **Actions** 页手动跑一次「daily-report」（Run workflow），之后每天自动更新。
   - 首次运行如果 deploy 步骤报错，通常是第 3 步还没设置，设置后重跑即可。

网站地址：`https://<用户名>.github.io/<仓库名>/`

### 可选：云端启用 LLM 翻译

仓库 **Settings → Secrets and variables → Actions → New repository secret** 添加：

| Secret | 说明 |
|---|---|
| `LLM_API_BASE` | OpenAI 兼容接口地址，如 `https://api.openai.com/v1` |
| `LLM_API_KEY` | 对应 API Key |
| `LLM_MODEL` | 模型名，如 `gpt-4o-mini` |

不配置也能运行——自动走免密钥翻译兜底，失败保留原文。

### 说明

- `data/ai_news.db` 随仓库提交：跨天的周报趋势、数据源健康状态在云端也能延续。
- 手动改代码推送不会触发抓取（工作流只按定时/手动触发），不会死循环。
- 想改运行时间：改 `daily.yml` 里的 `cron`（注意是 UTC 时间，北京时间 = UTC + 8）。
