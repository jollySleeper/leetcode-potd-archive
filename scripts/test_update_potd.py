"""Unit tests for update_potd. Fixture-based; never touches the network."""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import update_potd as up


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def api_item(day: str, qid: str, title: str | None = None, slug: str | None = None,
             difficulty: str = "Medium", paid: bool = False) -> dict:
    """One API list item, shaped like the LeetCode response."""
    slug = slug or f"problem-{qid}"
    return {
        "date": day,
        "link": f"/problems/{slug}/",
        "question": {
            "questionFrontendId": qid,
            "title": title or f"Problem {qid}",
            "titleSlug": slug,
            "difficulty": difficulty,
            "isPaidOnly": paid,
        },
    }


def daily_items(year: int, month: int, days=None) -> list[dict]:
    """Dailies for the given days (default: every day of the month) with unique ids."""
    if days is None:
        days = range(1, up.days_in_month(year, month) + 1)
    return [api_item(f"{year:04d}-{month:02d}-{d:02d}", f"{year}{month:02d}{d:02d}") for d in days]


def api_payload(year: int, month: int, days=None, weeklies=None) -> dict:
    return {
        "data": {
            "dailyCodingChallengeV2": {
                "challenges": daily_items(year, month, days),
                "weeklyChallenges": list(weeklies or []),
            }
        }
    }


class MonthArithmeticTests(unittest.TestCase):
    def test_previous_month_mid_year(self):
        self.assertEqual(up.previous_month(utc(2026, 10, 1)), (2026, 9))

    def test_previous_month_wraps_january(self):
        self.assertEqual(up.previous_month(utc(2026, 1, 1)), (2025, 12))

    def test_previous_month_uses_utc(self):
        # 2026-10-01 03:00 in UTC+05:30 is still 2026-09-30 in UTC.
        ist = timezone(timedelta(hours=5, minutes=30))
        self.assertEqual(up.previous_month(datetime(2026, 10, 1, 3, 0, tzinfo=ist)), (2026, 8))

    def test_iter_months_crosses_year(self):
        self.assertEqual(
            list(up.iter_months((2025, 11), (2026, 2))),
            [(2025, 11), (2025, 12), (2026, 1), (2026, 2)],
        )

    def test_days_in_month(self):
        self.assertEqual(up.days_in_month(2024, 2), 29)
        self.assertEqual(up.days_in_month(2026, 2), 28)
        self.assertEqual(up.days_in_month(2026, 9), 30)

    def test_labels(self):
        self.assertEqual(up.month_label(2026, 9), "September 2026")
        self.assertEqual(up.month_key(2020, 4), "2020-04")


class ClassificationTests(unittest.TestCase):
    def kind(self, payload, year, month):
        return up.classify_response(payload, year, month)[0]

    def test_full_january_is_complete(self):
        self.assertEqual(self.kind(api_payload(2026, 1), 2026, 1), up.COMPLETE)

    def test_zero_weeklies_is_still_complete(self):
        self.assertEqual(self.kind(api_payload(2020, 4, weeklies=[]), 2020, 4), up.COMPLETE)

    def test_prefix_of_september_is_partial(self):
        self.assertEqual(self.kind(api_payload(2026, 9, days=range(1, 29)), 2026, 9), up.PARTIAL)

    def test_empty_challenges(self):
        self.assertEqual(self.kind(api_payload(2026, 10, days=[]), 2026, 10), up.EMPTY)

    def test_graphql_errors_are_unavailable(self):
        payload = {
            "errors": [{"message": "'list' object has no attribute 'none'"}],
            "data": {"dailyCodingChallengeV2": None},
        }
        self.assertEqual(self.kind(payload, 2026, 10), up.UNAVAILABLE)

    def test_null_record_without_errors_is_unavailable(self):
        self.assertEqual(self.kind({"data": {"dailyCodingChallengeV2": None}}, 2020, 1), up.UNAVAILABLE)

    def test_duplicate_date_is_invalid(self):
        payload = api_payload(2026, 1)
        dailies = payload["data"]["dailyCodingChallengeV2"]["challenges"]
        dailies[1]["date"] = dailies[0]["date"]
        self.assertEqual(self.kind(payload, 2026, 1), up.INVALID)

    def test_date_in_another_month_is_invalid(self):
        payload = api_payload(2026, 1)
        payload["data"]["dailyCodingChallengeV2"]["challenges"][30]["date"] = "2026-02-01"
        self.assertEqual(self.kind(payload, 2026, 1), up.INVALID)

    def test_gap_that_is_not_a_prefix_is_invalid(self):
        days = list(range(1, 11)) + [12]
        self.assertEqual(self.kind(api_payload(2026, 1, days=days), 2026, 1), up.INVALID)

    def test_non_list_challenges_is_invalid(self):
        payload = {"data": {"dailyCodingChallengeV2": {"challenges": {}, "weeklyChallenges": []}}}
        self.assertEqual(self.kind(payload, 2026, 1), up.INVALID)
        payload = api_payload(2026, 1)
        payload["data"]["dailyCodingChallengeV2"]["weeklyChallenges"] = None
        self.assertEqual(self.kind(payload, 2026, 1), up.INVALID)


class FieldRuleTests(unittest.TestCase):
    def setUp(self):
        weeklies = [
            api_item("2026-01-01", "1426", slug="counting-elements", paid=True),
            api_item("2026-01-29", "1088", slug="confusing-number-ii", difficulty="Hard", paid=True),
        ]
        self.payload = api_payload(2026, 1, weeklies=weeklies)
        record = self.payload["data"]["dailyCodingChallengeV2"]
        self.daily = record["challenges"][4]
        self.weekly = record["weeklyChallenges"][1]

    def assertInvalid(self):
        kind, detail = up.classify_response(self.payload, 2026, 1)
        self.assertEqual(kind, up.INVALID, detail)

    def test_baseline_is_complete(self):
        self.assertEqual(up.classify_response(self.payload, 2026, 1)[0], up.COMPLETE)

    def test_rule_1_missing_title(self):
        del self.daily["question"]["title"]
        self.assertInvalid()

    def test_rule_2_bad_weekly_date(self):
        self.weekly["date"] = "2026-02-30"
        self.assertInvalid()

    def test_rule_3_non_digit_id(self):
        self.daily["question"]["questionFrontendId"] = "LCP 01"
        self.assertInvalid()

    def test_rule_4_unknown_difficulty(self):
        self.weekly["question"]["difficulty"] = "Unknown"
        self.assertInvalid()

    def test_rule_5_uppercase_slug(self):
        self.daily["question"]["titleSlug"] = "Two-sum"
        self.daily["link"] = "/problems/Two-sum/"
        self.assertInvalid()

    def test_rule_6_is_paid_only_missing_on_daily(self):
        del self.daily["question"]["isPaidOnly"]
        self.assertInvalid()

    def test_rule_7_link_for_different_slug(self):
        self.daily["link"] = "/problems/some-other-problem/"
        self.assertInvalid()

    def test_rule_7_allows_query_string(self):
        self.daily["link"] = self.daily["link"] + "?envType=daily-question"
        self.assertEqual(up.classify_response(self.payload, 2026, 1)[0], up.COMPLETE)

    def test_rule_8_weekly_two_months_away(self):
        self.weekly["date"] = "2026-03-01"
        self.assertInvalid()

    def test_rule_8_allows_adjacent_months(self):
        self.weekly["date"] = "2026-02-05"
        self.payload["data"]["dailyCodingChallengeV2"]["weeklyChallenges"][0]["date"] = "2025-12-29"
        self.assertEqual(up.classify_response(self.payload, 2026, 1)[0], up.COMPLETE)


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        weeklies = [api_item("2026-05-29", "1088", title="Confusing Number II", slug="confusing-number-ii",
                             difficulty="Hard", paid=True)]
        payload = api_payload(2026, 5, weeklies=weeklies)
        record = payload["data"]["dailyCodingChallengeV2"]
        record["challenges"][0] = api_item("2026-05-01", "396", title="N × 3", slug="n-x-3", paid=True)
        record["challenges"][0]["userStatus"] = "NotStart"
        record["challenges"][0]["question"]["extra"] = "dropped"
        self.snapshot = up.normalize_response(payload, 2026, 5)

    def test_key_order(self):
        self.assertEqual(list(self.snapshot), ["year", "month", "challenges", "weeklyChallenges"])
        for item in self.snapshot["challenges"] + self.snapshot["weeklyChallenges"]:
            self.assertEqual(list(item), ["date", "id", "title", "slug", "difficulty", "isPaidOnly", "link"])

    def test_values(self):
        first = self.snapshot["challenges"][0]
        self.assertEqual(first["id"], "396")
        self.assertIs(first["isPaidOnly"], True)
        self.assertIs(self.snapshot["challenges"][1]["isPaidOnly"], False)
        self.assertEqual(first["link"], "/problems/n-x-3/")
        self.assertEqual(self.snapshot["weeklyChallenges"][0]["slug"], "confusing-number-ii")

    def test_rendered_json(self):
        text = up.render_json(self.snapshot).decode("utf-8")
        self.assertIn('"title": "N × 3"', text)
        self.assertNotIn("\\u00d7", text)
        self.assertNotIn("userStatus", text)
        self.assertTrue(text.startswith('{\n  "year": 2026,\n  "month": 5,\n'))
        self.assertTrue(text.endswith("}\n"))
        self.assertFalse(text.endswith("\n\n"))

    def test_rejects_non_complete(self):
        with self.assertRaises(up.ArchiveError):
            up.normalize_response(api_payload(2026, 9, days=range(1, 29)), 2026, 9)

    def test_write_if_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertTrue(up.save_snapshot(root, self.snapshot))
            path = root / "archive" / "2026" / "2026-05.json"
            self.assertTrue(path.is_file())
            before = path.stat().st_mtime_ns
            self.assertFalse(up.save_snapshot(root, self.snapshot))
            self.assertEqual(path.stat().st_mtime_ns, before)


class FakeTransport:
    """Returns queued (status, body) pairs or raises queued exceptions."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append({"url": url, "body": json.loads(body), "headers": headers, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def ok_body(payload) -> tuple[int, bytes]:
    return 200, json.dumps(payload).encode("utf-8")


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []

    def client(self, transport):
        return up.LeetCodeClient(transport=transport, sleep=self.sleeps.append)

    def test_request_shape(self):
        transport = FakeTransport(ok_body({"data": {"dailyCodingChallengeV2": None}}))
        self.client(transport).fetch_month(2026, 1)
        call = transport.calls[0]
        self.assertEqual(call["url"], "https://leetcode.com/graphql/")
        self.assertEqual(call["timeout"], 30)
        self.assertEqual(call["body"]["operationName"], "dailyCodingQuestionRecords")
        self.assertEqual(call["body"]["variables"], {"year": 2026, "month": 1})
        self.assertEqual(call["body"]["query"], up.QUERY)
        self.assertEqual(call["headers"]["User-Agent"], "Mozilla/5.0 (compatible; leetcode-potd-archive/1.0)")
        self.assertNotIn("Cookie", call["headers"])

    def test_503_then_200_succeeds_on_second_attempt(self):
        payload = {"data": {"dailyCodingChallengeV2": None}}
        transport = FakeTransport((503, b"busy"), ok_body(payload))
        self.assertEqual(self.client(transport).fetch_month(2026, 9), payload)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(self.sleeps, [2])

    def test_403_fails_without_retry(self):
        transport = FakeTransport((403, b"forbidden"), ok_body({}))
        with self.assertRaises(up.FetchError) as ctx:
            self.client(transport).fetch_month(2026, 9)
        self.assertIn("403", str(ctx.exception))
        self.assertIn("2026-09", str(ctx.exception))
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(self.sleeps, [])

    def test_gives_up_after_three_attempts(self):
        transport = FakeTransport(
            urllib.error.URLError("down"), TimeoutError("slow"), (429, b"")
        )
        with self.assertRaises(up.FetchError) as ctx:
            self.client(transport).fetch_month(2026, 9)
        self.assertIn("HTTP 429", str(ctx.exception))
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(self.sleeps, [2, 4])

    def test_non_json_body_fails_after_retries(self):
        transport = FakeTransport((200, b"<html>"), (200, b"<html>"), (200, b"<html>"))
        with self.assertRaises(up.FetchError) as ctx:
            self.client(transport).fetch_month(2026, 9)
        self.assertIn("not JSON", str(ctx.exception))
        self.assertEqual(len(transport.calls), 3)


if __name__ == "__main__":
    unittest.main()
