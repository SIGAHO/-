from __future__ import annotations
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re


class TimeEngine:
    def __init__(self, tz: str = "Asia/Tokyo"):
        self.tz = ZoneInfo(tz)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def runtime_facts(self) -> dict[str, str | int]:
        n = self.now()
        return {
            "time.iso": n.isoformat(timespec="seconds"),
            "time.year": n.year,
            "time.month": n.month,
            "time.day": n.day,
            "time.hour": n.hour,
            "time.minute": n.minute,
            "time.weekday": n.strftime("%A"),
        }

    def resolve_simple_relative_date(self, text: str):
        n = self.now().date()
        if "今日" in text:
            return n
        if "明日" in text:
            return n + timedelta(days=1)
        if "昨日" in text:
            return n - timedelta(days=1)
        m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
        if m:
            return n.replace(month=int(m.group(1)), day=int(m.group(2)))
        return None
