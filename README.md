# AI 活动雷达

这是一个“网页 + 后端 API + SQLite + 定时抓取”的最小可运行版本。

## 在线访问

公网网页：<https://xuquanjun1-lab.github.io/ai-event-radar/>

页面会从腾讯 CloudBase 的公开 API 读取活动数据，因此在手机或电脑上打开同一链接均可查看最新同步结果。

## 本地启动

在当前目录执行：

```powershell
python server.py
```

然后访问 <http://127.0.0.1:8787/>。

API：

- `GET /api/health`：服务、数据库和最近同步状态
- `GET /api/events`：活动列表
- `GET /api/sources`：当前公开来源
- `POST /api/sync`：手动执行一次抓取
- `GET /api/news`：读取最近 7 天的 AI 资讯；配置 `AIHOT_BASE_URL` 时优先读取自建 AIHOT，否则读取 OpenAI、Google DeepMind、Hugging Face、GitHub 的公开 RSS

本地服务默认每小时检查一次来源，可通过 `AI_EVENTS_SYNC_INTERVAL` 调整秒数。腾讯 CloudBase 的公网数据源已配置为每天北京时间 09:00 自动同步。数据库文件位于 `data/events.sqlite3`，不应提交到 Git；首次启动会自动建表并写入基础活动数据，后续抓取结果会持久化到同一数据库。

页面新增了“AI 资讯精选”栏目和 PDF 导出：活动 PDF、资讯 PDF、活动与资讯合并 PDF 均在浏览器本地生成，文档会保留活动报名链接和资讯原文链接。本地由 `/api/news` 提供资讯；GitHub Pages 读取 `data/news.json`，通过 `.github/workflows/refresh-news.yml` 每天 09:15 北京时间从官方 RSS 刷新。该工作流也核对指定报名页并刷新 `data/verified-events.json`；云端活动数据库不可用时页面展示这份快照。GitHub Actions 的定时执行可能延迟，页面会显示快照时间。配置 `AIHOT_BASE_URL=http://127.0.0.1:3000` 后，本地后端会优先读取你自建的 AIHOT 公开 API。

## 当前抓取边界

抓取器只访问公开列表页，优先使用 HTTP 解析；遇到 JavaScript 渲染、登录、验证码或反爬时会记录为部分可用，并保留上一次数据。它不依赖 Edge 浏览器 API，也不会把数据库凭据放到前端。

## 腾讯云现状

仓库中的 `cloudbaserc.json` 指向已配置的 CloudBase 环境；云函数会将活动记录写入 CloudBase 数据库集合。静态托管适合发布 `index.html`，但不能承载本 Python 进程；要让公网访客实时看到同步数据，需要把 `server.py` 部署到云托管，或启用云函数的定时触发器并以 CloudBase 数据库作为唯一数据源。当前本地服务先用 SQLite 验证完整数据链路，避免把本机数据库误当作云端数据库。
