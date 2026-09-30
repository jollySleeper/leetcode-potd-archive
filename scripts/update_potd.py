#!/usr/bin/env python3
"""Archive LeetCode's daily and weekly challenges as monthly snapshots.

Canonical data lives in archive/YYYY/YYYY-MM.json. The build step turns those
snapshots into monthly Markdown pages, archive/README.md, and
docs/challenges.json for the static site.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from pathlib import Path

FIRST_MONTH = (2020, 4)

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = Path("archive")
INDEX_PATH = ARCHIVE_DIR / "README.md"
SITE_JSON_PATH = Path("docs") / "challenges.json"

MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


# ---------------------------------------------------------------------------
# Month arithmetic
# ---------------------------------------------------------------------------


def to_utc(now: datetime) -> datetime:
    """Return `now` in UTC. A naive datetime is taken to already be UTC."""
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def current_month(now: datetime) -> tuple[int, int]:
    utc = to_utc(now)
    return utc.year, utc.month


def previous_month(now: datetime) -> tuple[int, int]:
    """The calendar month before the current UTC month."""
    return month_before(current_month(now))


def month_before(month: tuple[int, int]) -> tuple[int, int]:
    year, mon = month
    return (year - 1, 12) if mon == 1 else (year, mon - 1)


def month_after(month: tuple[int, int]) -> tuple[int, int]:
    year, mon = month
    return (year + 1, 1) if mon == 12 else (year, mon + 1)


def iter_months(start: tuple[int, int], end: tuple[int, int]):
    """Yield every (year, month) from start through end inclusive."""
    month = start
    while month <= end:
        yield month
        month = month_after(month)


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def month_label(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"
