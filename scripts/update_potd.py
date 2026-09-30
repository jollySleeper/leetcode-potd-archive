#!/usr/bin/env python3
"""Archive LeetCode's daily and weekly challenges as monthly snapshots.

Canonical data lives in archive/YYYY/YYYY-MM.json. The build step turns those
snapshots into monthly Markdown pages, archive/README.md, and
docs/challenges.json for the static site.
"""

from __future__ import annotations

import calendar
import json
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
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

UNAVAILABLE = "unavailable"
EMPTY = "empty"
PARTIAL = "partial"
COMPLETE = "complete"
INVALID = "invalid"

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
ID_RE = re.compile(r"\d+", re.ASCII)
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DIFFICULTIES = ("Easy", "Medium", "Hard")


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


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def parse_date(value: object) -> date | None:
    """Parse a YYYY-MM-DD string that is a real calendar date, else None."""
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def api_item_fields(item: object) -> dict:
    """Map one API list item onto snapshot field names. Missing values become None."""
    if not isinstance(item, dict):
        return {}
    question = item.get("question")
    if not isinstance(question, dict):
        question = {}
    return {
        "date": item.get("date"),
        "id": question.get("questionFrontendId"),
        "title": question.get("title"),
        "slug": question.get("titleSlug"),
        "difficulty": question.get("difficulty"),
        "isPaidOnly": question.get("isPaidOnly"),
        "link": item.get("link"),
    }


def classify_items(dailies: list, weeklies: list, year: int, month: int) -> tuple[str, str]:
    """Classify daily/weekly items that already use snapshot field names."""
    label = month_key(year, month)
    days = []
    for item in dailies:
        value = item.get("date") if isinstance(item, dict) else None
        parsed = parse_date(value)
        if parsed is None or (parsed.year, parsed.month) != (year, month):
            return INVALID, f"daily date {value!r} is not a date in {label}"
        days.append(parsed.day)
    if len(set(days)) != len(days):
        return INVALID, f"duplicate daily dates in {label}"
    if sorted(days) != list(range(1, len(days) + 1)):
        return INVALID, f"daily dates in {label} are not days 1..N"
    if len(days) < days_in_month(year, month):
        return PARTIAL, f"{label} has {len(days)} of {days_in_month(year, month)} dailies"
    problems = field_errors(dailies, weeklies, year, month)
    if problems:
        return INVALID, f"{label}: " + "; ".join(problems)
    return COMPLETE, f"{label} has all {len(days)} dailies"


def field_errors(dailies: list, weeklies: list, year: int, month: int) -> list[str]:
    """Apply field rules 1-8 to every daily and weekly item."""
    nearby = {month_before((year, month)), (year, month), month_after((year, month))}
    problems = []
    for kind, items in (("daily", dailies), ("weekly", weeklies)):
        for index, item in enumerate(items, start=1):
            where = f"{kind} #{index}"
            if not isinstance(item, dict):
                problems.append(f"{where}: not an object")
                continue
            missing = [
                name
                for name in ("date", "id", "title", "slug", "difficulty")
                if not isinstance(item.get(name), str) or item.get(name) == ""
            ]
            if missing:
                problems.append(f"{where}: missing or empty {', '.join(missing)}")
                continue
            parsed = parse_date(item["date"])
            if parsed is None:
                problems.append(f"{where}: date {item['date']!r} is not a real YYYY-MM-DD date")
            elif kind == "weekly" and (parsed.year, parsed.month) not in nearby:
                problems.append(f"{where}: weekly date {item['date']} is too far from {month_key(year, month)}")
            if not ID_RE.fullmatch(item["id"]):
                problems.append(f"{where}: id {item['id']!r} is not digits")
            if item["difficulty"] not in DIFFICULTIES:
                problems.append(f"{where}: difficulty {item['difficulty']!r} is not Easy, Medium, or Hard")
            if not SLUG_RE.fullmatch(item["slug"]):
                problems.append(f"{where}: slug {item['slug']!r} is not a valid slug")
            if not isinstance(item.get("isPaidOnly"), bool):
                problems.append(f"{where}: isPaidOnly is not a boolean")
            link = item.get("link")
            if not isinstance(link, str) or not link.startswith(f"/problems/{item['slug']}/"):
                problems.append(f"{where}: link {link!r} does not start with /problems/{item['slug']}/")
    return problems


def classify_response(payload: object, year: int, month: int) -> tuple[str, str]:
    """Classify one GraphQL response as (class, human-readable detail)."""
    if not isinstance(payload, dict):
        return INVALID, "response is not a JSON object"
    errors = payload.get("errors")
    if errors:
        message = errors[0].get("message") if isinstance(errors, list) and isinstance(errors[0], dict) else errors
        return UNAVAILABLE, f"GraphQL error: {message}"
    data = payload.get("data")
    record = data.get("dailyCodingChallengeV2") if isinstance(data, dict) else None
    if record is None:
        return UNAVAILABLE, "dailyCodingChallengeV2 is null"
    if not isinstance(record, dict):
        return INVALID, "dailyCodingChallengeV2 is not an object"
    challenges = record.get("challenges")
    weeklies = record.get("weeklyChallenges")
    if challenges == []:
        return EMPTY, "challenges is empty"
    if not isinstance(challenges, list) or not isinstance(weeklies, list):
        return INVALID, "challenges and weeklyChallenges must be lists"
    return classify_items(
        [api_item_fields(item) for item in challenges],
        [api_item_fields(item) for item in weeklies],
        year,
        month,
    )
