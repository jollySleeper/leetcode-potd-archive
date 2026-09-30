"""Unit tests for update_potd. Fixture-based; never touches the network."""

from __future__ import annotations

import json
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone

import update_potd as up


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


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
