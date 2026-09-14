"""Due-date resolution relative to evidence.occurred_at (docs/04 §2).

Uses dateparser with RELATIVE_BASE = the evidence timestamp in the user's
timezone (``SALESOS_TIMEZONE``), not wall-clock now. Unresolvable phrases
leave ``due_date`` null and keep ``due_text``.
"""

from __future__ import annotations

import os
import re
from calendar import monthrange
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import dateparser
from dateparser.search import search_dates

DEFAULT_TIMEZONE = "Europe/London"

_DATE_HINT = re.compile(
    r"\b("
    r"today|tomorrow|yesterday|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?|"
    r"\d{1,2}(?:st|nd|rd|th)?|"
    r"end of (?:the )?month|next week|this week|next month"
    r")\b",
    re.IGNORECASE,
)

_END_OF_MONTH = re.compile(r"\bend of (?:the )?month\b", re.IGNORECASE)


def user_timezone(name: str | None = None) -> ZoneInfo:
    raw = name or os.environ.get("SALESOS_TIMEZONE") or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(raw)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def parse_occurred_at(occurred_at: str) -> datetime:
    text = occurred_at.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def local_base(occurred_at: str, tz: ZoneInfo) -> datetime:
    return parse_occurred_at(occurred_at).astimezone(tz).replace(tzinfo=None)


def _parser_settings(base: datetime) -> dict:
    return {
        "RELATIVE_BASE": base,
        "PREFER_DATES_FROM": "future",
        "RETURN_AS_TIMEZONE_AWARE": False,
        "STRICT_PARSING": False,
    }


def _end_of_month(base: datetime) -> date:
    last = monthrange(base.year, base.month)[1]
    return date(base.year, base.month, last)


def looks_like_date_phrase(text: str) -> bool:
    return bool(_DATE_HINT.search(text))


def resolve_due_date(
    due_text: str | None,
    occurred_at: str,
    *,
    timezone_name: str | None = None,
) -> str | None:
    """Return an ISO date (user-local) or None if ``due_text`` cannot be parsed."""
    if not due_text or not due_text.strip():
        return None
    tz = user_timezone(timezone_name)
    base = local_base(occurred_at, tz)
    phrase = due_text.strip()
    if _END_OF_MONTH.search(phrase) and "next" not in phrase.lower():
        return _end_of_month(base).isoformat()
    parsed = dateparser.parse(phrase, settings=_parser_settings(base))
    if parsed is None:
        return None
    return parsed.date().isoformat()


def find_due_in_text(
    text: str,
    occurred_at: str,
    *,
    timezone_name: str | None = None,
) -> tuple[str | None, str | None]:
    """Return ``(due_text, due_date)`` from date phrases in ``text``.

    search_dates is noisy (it treats 'We' as Wednesday); only phrases that
    look like dates are kept.
    """
    if not text:
        return None, None
    tz = user_timezone(timezone_name)
    base = local_base(occurred_at, tz)
    if _END_OF_MONTH.search(text):
        match = _END_OF_MONTH.search(text)
        phrase = match.group(0) if match else "end of month"
        return phrase, _end_of_month(base).isoformat()
    found = search_dates(text, settings=_parser_settings(base))
    if not found:
        return None, None
    for phrase, parsed in found:
        if not looks_like_date_phrase(phrase):
            continue
        if parsed is None:
            continue
        return phrase.strip(), parsed.date().isoformat()
    return None, None
