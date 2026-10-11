"""Generate a public static news snapshot from first-party RSS feeds."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import collect_news

result = collect_news()
if not result["items"]:
    raise SystemExit("No official news could be collected; preserving prior snapshot")
output = {
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "items": result["items"],
    "errors": result["errors"],
    "provider": "official-rss",
}
target = ROOT / "data" / "news.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {len(output['items'])} news items to {target}")
