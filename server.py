"""AI 活动雷达：静态页面、SQLite API 和定时抓取服务。

这个服务不把数据库凭据放到浏览器端。抓取器对公开页面做低频访问，保存
结构化活动和同步状态；页面只读取本服务的 API。
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("AI_EVENTS_DB", ROOT / "data" / "events.sqlite3"))
PORT = int(os.environ.get("AI_EVENTS_PORT", "8787"))
SYNC_INTERVAL = int(os.environ.get("AI_EVENTS_SYNC_INTERVAL", "3600"))
USER_AGENT = "AI-Event-Radar/0.1 (+public-event-indexer)"

SOURCES = [
    {"name": "活动行 · AI 搜索", "url": "https://www.huodongxing.com/search?keyword=AI", "kind": "html"},
    {"name": "活动行 · 人工智能搜索", "url": "https://www.huodongxing.com/search?keyword=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD", "kind": "html"},
    {"name": "Meetup · Shanghai AI", "url": "https://www.meetup.com/find/?keywords=AI&location=cn--Shanghai", "kind": "html"},
    {"name": "Meetup · Hangzhou AI", "url": "https://www.meetup.com/find/?keywords=AI&location=cn--Hangzhou", "kind": "html"},
]

WEEKDAYS = "一二三四五六日"
CITY_NAMES = ("上海", "杭州", "长沙", "北京", "深圳", "广州", "成都", "南京", "武汉", "苏州", "重庆", "西安")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                city TEXT NOT NULL,
                title TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT '其他',
                start_date TEXT NOT NULL,
                end_date TEXT,
                day TEXT NOT NULL,
                weekday TEXT NOT NULL,
                place TEXT NOT NULL DEFAULT '线上 / 以报名页为准',
                source TEXT NOT NULL,
                source_url TEXT NOT NULL,
                registration_url TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL,
                is_seed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                sources_checked INTEGER NOT NULL DEFAULT 0,
                events_added INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT ''
            );
            """
        )
        if conn.execute("SELECT 1 FROM events WHERE is_seed = 1 LIMIT 1").fetchone() is None:
            for event in load_seed_events():
                upsert_event(conn, event, is_seed=True)


def fingerprint(event: dict[str, Any]) -> str:
    key = "|".join(str(event.get(k, "")).strip().lower() for k in ("title", "city", "start_date", "source_url"))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def upsert_event(conn: sqlite3.Connection, event: dict[str, Any], is_seed: bool = False) -> bool:
    event = dict(event)
    event["fingerprint"] = fingerprint(event)
    event.setdefault("fetched_at", now_iso())
    event.setdefault("end_date", event.get("start_date"))
    event.setdefault("description", "公开页面活动信息，报名前请以主办方最终通知为准。")
    event.setdefault("registration_url", event.get("source_url", ""))
    event.setdefault("type", "其他")
    event.setdefault("place", "线上 / 以报名页为准")
    try:
        conn.execute(
            """INSERT INTO events (fingerprint,city,title,type,start_date,end_date,day,weekday,place,source,source_url,registration_url,description,fetched_at,is_seed)
               VALUES (:fingerprint,:city,:title,:type,:start_date,:end_date,:day,:weekday,:place,:source,:source_url,:registration_url,:description,:fetched_at,:is_seed)
               ON CONFLICT(fingerprint) DO UPDATE SET title=excluded.title,type=excluded.type,end_date=excluded.end_date,day=excluded.day,weekday=excluded.weekday,place=excluded.place,registration_url=excluded.registration_url,description=excluded.description,fetched_at=excluded.fetched_at""",
            {**event, "is_seed": int(is_seed)},
        )
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.IntegrityError:
        return False


def parse_seed_object(raw: str) -> dict[str, str] | None:
    fields = ("city", "day", "date", "weekday", "title", "type", "place", "source", "url", "desc")
    values: dict[str, str] = {}
    for field in fields:
        match = re.search(rf"{field}:'((?:\\.|[^'])*)'", raw)
        if not match:
            return None
        values[field] = bytes(match.group(1), "utf-8").decode("unicode_escape") if "\\" in match.group(1) else match.group(1)
    return {
        "city": values["city"], "title": values["title"], "type": values["type"],
        "start_date": values["date"], "end_date": values["date"], "day": values["day"],
        "weekday": values["weekday"], "place": values["place"], "source": values["source"],
        "source_url": values["url"], "registration_url": values["url"], "description": values["desc"],
    }


def load_seed_events() -> list[dict[str, Any]]:
    text = (ROOT / "index.html").read_text(encoding="utf-8")
    start = text.find("const demoEvents=[")
    end = text.find("];", start)
    if start < 0 or end < 0:
        return []
    return [event for raw in re.findall(r"\{id:\d+,[^}]+\}", text[start:end]) if (event := parse_seed_object(raw))]


def fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    with urlopen(request, timeout=18) as response:
        data = response.read(2_000_000)
        charset = response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace")


def infer_type(text: str) -> str:
    for keyword, kind in (("黑客松", "黑客松"), ("hackathon", "黑客松"), ("工作坊", "工作坊"), ("论坛", "会议"), ("大会", "会议"), ("讲座", "讲座"), ("沙龙", "沙龙"), ("聚会", "聚会")):
        if keyword.lower() in text.lower():
            return kind
    return "其他"


def infer_date(title: str, fallback: date) -> date:
    month_names = {name: number for number, name in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
    match = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})\b", title, re.I)
    if match:
        try:
            candidate = date(fallback.year, month_names[match.group(1).lower()[:3]], int(match.group(2)))
            return candidate if candidate >= fallback else date(fallback.year + 1, candidate.month, candidate.day)
        except ValueError:
            pass
    match = re.search(r"(\d{1,2})月(\d{1,2})日", title)
    if match:
        try:
            candidate = date(fallback.year, int(match.group(1)), int(match.group(2)))
            return candidate if candidate >= fallback else date(fallback.year + 1, candidate.month, candidate.day)
        except ValueError:
            pass
    return fallback


def discover_events(source: dict[str, str]) -> list[dict[str, Any]]:
    """从公开列表页提取明显的活动链接；不绕过登录、验证码或访问限制。"""
    body = fetch_html(source["url"])
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(body))).strip()
    links = re.findall(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", body, flags=re.I | re.S)
    found: list[dict[str, Any]] = []
    today = date.today()
    for href, label in links:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(label))).strip()
        if len(title) < 5 or len(title) > 160 or not re.search(r"\bAI\b|\bAgent\b|人工智能|智能体|大模型|机器学习|黑客松|hackathon", title, re.I):
            continue
        absolute = urljoin(source["url"], href)
        if urlparse(absolute).scheme not in {"http", "https"}:
            continue
        city = next((name for name in CITY_NAMES if name in title or name in plain[max(0, plain.find(title) - 100):plain.find(title) + 200]), "全国")
        event_date = infer_date(title, today)
        item = {"city": city, "title": title, "type": infer_type(title), "start_date": event_date.isoformat(), "end_date": event_date.isoformat(),
                "day": f"{event_date.day:02d}", "weekday": f"周{WEEKDAYS[event_date.weekday()]}", "place": f"{city} · 以详情页为准",
                "source": source["name"], "source_url": source["url"], "registration_url": absolute,
                "description": "由公开活动列表页发现，具体日期、地点和报名条件请打开来源页面确认。"}
        found.append(item)
        if len(found) >= 20:
            break
    return found


def sync_sources() -> dict[str, Any]:
    started = now_iso()
    run_id: int
    with get_db() as conn:
        run_id = conn.execute("INSERT INTO sync_runs (started_at,status) VALUES (?,?)", (started, "running")).lastrowid
    total_added = 0
    messages: list[str] = []
    for source in SOURCES:
        try:
            discovered = discover_events(source)
            with get_db() as conn:
                for event in discovered:
                    total_added += int(upsert_event(conn, event))
            messages.append(f"{source['name']}：发现 {len(discovered)} 条")
        except Exception as exc:
            messages.append(f"{source['name']}：暂不可用（{type(exc).__name__}）")
    status = "ok" if any("发现" in message for message in messages) else "partial"
    with get_db() as conn:
        conn.execute("UPDATE sync_runs SET finished_at=?,status=?,sources_checked=?,events_added=?,message=? WHERE id=?", (now_iso(), status, len(SOURCES), total_added, "；".join(messages), run_id))
    return {"status": status, "started_at": started, "finished_at": now_iso(), "sources_checked": len(SOURCES), "events_added": total_added, "message": "；".join(messages)}


def list_events(query: dict[str, list[str]]) -> list[dict[str, Any]]:
    limit = min(max(int(query.get("limit", ["100"])[0]), 1), 500)
    params: list[Any] = []
    clauses = []
    if query.get("city") and query["city"][0] != "全部":
        clauses.append("city = ?"); params.append(query["city"][0])
    if query.get("from"):
        clauses.append("start_date >= ?"); params.append(query["from"][0])
    if query.get("to"):
        clauses.append("start_date <= ?"); params.append(query["to"][0])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_db() as conn:
        rows = conn.execute(f"SELECT * FROM events {where} ORDER BY start_date, city, id LIMIT ?", [*params, limit]).fetchall()
        return [dict(row) for row in rows]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: Any, content_type: str = "application/json; charset=utf-8") -> None:
        body = payload if isinstance(payload, bytes) else (json.dumps(payload, ensure_ascii=False).encode("utf-8") if content_type.startswith("application/json") else str(payload).encode("utf-8"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        action = query.get("action", [""])[0]
        if parsed.path == "/api/events" or (parsed.path == "/api" and action == "events"):
            self._send(200, {"events": list_events(query), "last_sync": last_sync()}); return
        if parsed.path == "/api/health" or (parsed.path == "/api" and action == "health"):
            self._send(200, {"ok": True, "database": str(DB_PATH), "last_sync": last_sync(), "sources": len(SOURCES)}); return
        if parsed.path == "/api/sources" or (parsed.path == "/api" and action == "sources"):
            self._send(200, {"sources": SOURCES}); return
        path = ROOT / ("index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/"))
        if path.exists() and path.is_file() and ROOT in path.resolve().parents:
            self._send(200, path.read_bytes(), "text/html; charset=utf-8" if path.suffix == ".html" else "application/octet-stream"); return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/sync" or (parsed.path == "/api" and parse_qs(parsed.query).get("action", [""])[0] == "sync"):
            self._send(200, sync_sources()); return
        self._send(404, {"error": "not_found"})

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")


def last_sync() -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT started_at,finished_at,status,sources_checked,events_added,message FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def scheduler() -> None:
    while True:
        time.sleep(SYNC_INTERVAL)
        try:
            print("scheduled sync", sync_sources())
        except Exception as exc:
            print("scheduled sync failed", repr(exc))


if __name__ == "__main__":
    init_db()
    threading.Thread(target=scheduler, daemon=True).start()
    print(f"AI 活动雷达 running at http://127.0.0.1:{PORT} (sync every {SYNC_INTERVAL}s)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
