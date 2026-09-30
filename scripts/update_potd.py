#!/usr/bin/env python3
"""Archive LeetCode's daily and weekly challenges as monthly snapshots.

Canonical data lives in archive/YYYY/YYYY-MM.json. The build step turns those
snapshots into monthly Markdown pages, archive/README.md, and
docs/challenges.json for the static site.
"""

from __future__ import annotations

import calendar
import json
import time
import urllib.error
import urllib.request
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

GRAPHQL_URL = "https://leetcode.com/graphql/"
OPERATION_NAME = "dailyCodingQuestionRecords"
QUERY = """query dailyCodingQuestionRecords($year: Int!, $month: Int!) {
  dailyCodingChallengeV2(year: $year, month: $month) {
    challenges {
      date
      link
      question {
        questionFrontendId
        title
        titleSlug
        difficulty
        isPaidOnly
      }
    }
    weeklyChallenges {
      date
      link
      question {
        questionFrontendId
        title
        titleSlug
        difficulty
        isPaidOnly
      }
    }
  }
}"""
REQUEST_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; leetcode-potd-archive/1.0)",
    "Origin": "https://leetcode.com",
    "Referer": "https://leetcode.com/problemset/",
}
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
RETRY_SLEEPS = (2, 4)
BACKFILL_DELAY_SECONDS = 0.2


class ArchiveError(Exception):
    """Any failure that should end the command with exit code 1."""


class FetchError(ArchiveError):
    """The LeetCode request failed."""


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


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


def urllib_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    """POST `body` and return (status, response bytes). HTTP errors are returned, not raised."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


class LeetCodeClient:
    """Fetches one month of challenges. `transport` and `sleep` are injectable for tests."""

    def __init__(self, transport=urllib_transport, sleep=time.sleep):
        self.transport = transport
        self.sleep = sleep

    def fetch_month(self, year: int, month: int) -> object:
        """Return the decoded GraphQL response body for one month."""
        label = month_key(year, month)
        body = json.dumps(
            {
                "query": QUERY,
                "variables": {"year": year, "month": month},
                "operationName": OPERATION_NAME,
            }
        ).encode("utf-8")
        last_error = "no attempt made"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if attempt > 1:
                self.sleep(RETRY_SLEEPS[attempt - 2])
            try:
                status, raw = self.transport(GRAPHQL_URL, body, dict(REQUEST_HEADERS), TIMEOUT_SECONDS)
            except urllib.error.HTTPError as err:
                status, raw = err.code, b""
            except (urllib.error.URLError, TimeoutError) as err:
                last_error = f"network error: {getattr(err, 'reason', err)}"
                continue
            except OSError as err:
                raise FetchError(f"{label}: network error: {err}") from err
            if status == 403:
                raise FetchError(
                    f"{label}: HTTP 403 from LeetCode. LeetCode may be blocking this client "
                    "(bot protection); this is not retried."
                )
            if status != 200:
                last_error = f"HTTP {status}"
                continue
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                last_error = "response body is not JSON"
                continue
        raise FetchError(f"{label}: {last_error} after {MAX_ATTEMPTS} attempts")
