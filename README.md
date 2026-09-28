# AI 活动雷达

这是一个“网页 + 后端 API + SQLite + 定时抓取”的最小可运行版本。

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

默认每小时检查一次来源，可通过 `AI_EVENTS_SYNC_INTERVAL` 调整秒数。数据库文件位于 `data/events.sqlite3`，不应提交到 Git；首次启动会自动建表并写入基础活动数据，后续抓取结果会持久化到同一数据库。

## 当前抓取边界

抓取器只访问公开列表页，优先使用 HTTP 解析；遇到 JavaScript 渲染、登录、验证码或反爬时会记录为部分可用，并保留上一次数据。它不依赖 Edge 浏览器 API，也不会把数据库凭据放到前端。

## 腾讯云现状

仓库中的 `cloudbaserc.json` 指向已配置的 CloudBase 环境；云函数会将活动记录写入 CloudBase 数据库集合。静态托管适合发布 `index.html`，但不能承载本 Python 进程；要让公网访客实时看到同步数据，需要把 `server.py` 部署到云托管，或启用云函数的定时触发器并以 CloudBase 数据库作为唯一数据源。当前本地服务先用 SQLite 验证完整数据链路，避免把本机数据库误当作云端数据库。
