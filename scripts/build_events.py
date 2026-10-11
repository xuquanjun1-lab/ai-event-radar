"""Refresh a small fallback snapshot from verified registration pages."""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import fetch_html

MEETUP_URLS = [
    "https://www.meetup.com/tech-entrepreneurship-ai-venture-capital-prc/events/316536398/",
    "https://www.meetup.com/tech-entrepreneurship-ai-venture-capital-prc/events/316510494/",
]
MEETUP_TITLES = {
    "316536398": "2 小时用 Claude 构建求职 AI 智能体",
    "316510494": "3 小时构建首个研究型 AI 智能体",
}
CHANGSHA_URL = "https://cs.huodongxing.com/event/4878904065200"


def meetup_event(url: str) -> dict | None:
    body = fetch_html(url)
    scripts = re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', body, re.S | re.I)
    event = next((entry for text in scripts if (entry := json.loads(html.unescape(text))).get("@type") == "Event"), None)
    if not event or event.get("eventStatus") != "https://schema.org/EventScheduled":
        return None
    start = datetime.fromisoformat(event["startDate"])
    if not datetime.now(timezone.utc) <= start.astimezone(timezone.utc) <= datetime.now(timezone.utc) + timedelta(days=30):
        return None
    online = event.get("eventAttendanceMode") == "https://schema.org/OnlineEventAttendanceMode"
    return {
        "title": next((title for event_id, title in MEETUP_TITLES.items() if event_id in url), event["name"].strip()),
        "city": "线上" if online else "待核实", "type": "工作坊",
        "start_date": start.date().isoformat(), "end_date": start.date().isoformat(),
        "day": start.strftime("%d"), "weekday": "周" + "一二三四五六日"[start.weekday()],
        "place": "线上 · 以报名页为准" if online else event.get("location", {}).get("name", "待核实"),
        "source": "Meetup 官方活动页（已核验）", "source_url": url, "registration_url": url,
        "description": "报名方式、名额和具体安排请查看主办方活动页。",
    }


def changsha_event() -> dict | None:
    body = fetch_html(CHANGSHA_URL)
    match = re.search(r'"Id":4878904065200,.*?"Start":"\\/Date\((\d+)\)\\/".*?"StartShort":"([^"]+)".*?"City":"([^"]+)".*?"Address":"([^"]+)"', body, re.S)
    if not match or '"StatusStr":"报名中"' not in body:
        return None
    start = datetime.fromtimestamp(int(match.group(1)) / 1000, timezone.utc).astimezone(timezone(timedelta(hours=8)))
    if not datetime.now(timezone.utc) <= start.astimezone(timezone.utc) <= datetime.now(timezone.utc) + timedelta(days=30):
        return None
    return {
        "title": "火山引擎开发者社区技术日・NVIDIA 独家赞助-长沙站", "city": match.group(3),
        "type": "会议", "start_date": start.date().isoformat(), "end_date": start.date().isoformat(),
        "day": start.strftime("%d"), "weekday": "周" + "一二三四五六日"[start.weekday()],
        "place": match.group(4), "source": "活动行报名页（已核验）", "source_url": CHANGSHA_URL,
        "registration_url": CHANGSHA_URL,
        "description": "视频生成模型、多模态大模型与 NVIDIA 算力加速技术日；报名中，截止时间以原页为准。",
    }


items = []
errors = []
for url in MEETUP_URLS:
    try:
        if event := meetup_event(url):
            items.append(event)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"{url}: {type(exc).__name__}")
try:
    if event := changsha_event():
        items.append(event)
except (OSError, ValueError, KeyError, TypeError) as exc:
    errors.append(f"{CHANGSHA_URL}: {type(exc).__name__}")
if not items and errors:
    raise SystemExit(f"No verified future events; preserving prior snapshot. Errors: {errors}")
items.sort(key=lambda item: item["start_date"])
target = ROOT / "data" / "verified-events.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "events": items, "errors": errors}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {len(items)} verified events to {target}")
