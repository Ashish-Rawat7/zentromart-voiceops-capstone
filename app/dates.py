from __future__ import annotations
from datetime import date, timedelta
import re
from app.config import settings

REFERENCE_DATE = date.fromisoformat(settings.reference_date)
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

def parse_date(text: str) -> date | None:
    s = (text or "").casefold()
    m = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", s)
    if m:
        try: return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError: return None
    m = re.search(r"\b(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*(20\d{2})?\b", s)
    if not m:
        m = re.search(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:,?\s*(20\d{2}))?\b", s)
        if m:
            month = MONTHS[m.group(1)[:3]]
            day = int(m.group(2)); year = int(m.group(3) or REFERENCE_DATE.year)
        else:
            return None
    else:
        day = int(m.group(1)); month = MONTHS[m.group(2)[:3]]; year = int(m.group(3) or REFERENCE_DATE.year)
    try: return date(year, month, day)
    except ValueError: return None

def is_business_day(day: date, holidays: set[str]) -> bool:
    return day.weekday() != 6 and day.isoformat() not in holidays

def add_business_days(start: date, count: int, holidays: set[str]) -> date:
    """Count business days strictly after start (Mon-Sat except supplied holidays)."""
    current = start
    added = 0
    while added < count:
        current += timedelta(days=1)
        if is_business_day(current, holidays):
            added += 1
    return current

def fmt(day: date) -> str:
    return f"{day.day} {day.strftime('%B %Y')}"
