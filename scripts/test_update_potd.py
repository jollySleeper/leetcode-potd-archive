"""Unit tests for update_potd. Fixture-based; never touches the network."""

from __future__ import annotations

import unittest
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


if __name__ == "__main__":
    unittest.main()
