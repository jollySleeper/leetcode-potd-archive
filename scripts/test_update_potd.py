"""Unit tests for update_potd. Fixture-based; never touches the network."""

from __future__ import annotations

import json
import re
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


def own_weeklies(year: int, month: int) -> list[dict]:
    """Weekly items on days 1, 8, 15, 22, 29 that exist in the month."""
    return [
        api_item(f"{year:04d}-{month:02d}-{d:02d}", f"9{year}{month:02d}{d:02d}",
                 slug=f"weekly-{year}-{month:02d}-{d:02d}", paid=True)
        for d in (1, 8, 15, 22, 29)
        if d <= up.days_in_month(year, month)
    ]


def confusing_number_ii(day: str = "2026-06-05") -> dict:
    return api_item(day, "1088", title="Confusing Number II", slug="confusing-number-ii",
                    difficulty="Hard", paid=True)


def counting_elements(day: str = "2026-09-05") -> dict:
    return api_item(day, "1426", title="Counting Elements", slug="counting-elements",
                    difficulty="Easy", paid=True)


def write_archive(root: Path, through: tuple[int, int], weeklies=None, start=up.FIRST_MONTH) -> None:
    """Save complete snapshots from `start` through `through`.

    `weeklies` maps (year, month) of the queried month to that response's API weekly items.
    """
    weeklies = weeklies or {}
    for year, month in up.iter_months(start, through):
        payload = api_payload(year, month, weeklies=weeklies.get((year, month), []))
        up.save_snapshot(root, up.normalize_response(payload, year, month))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(up.render_json(value))


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


class ArchiveTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def snap(self, year: int, month: int) -> Path:
        return self.root / "archive" / f"{year:04d}" / f"{year:04d}-{month:02d}.json"


class SnapshotLoadingTests(ArchiveTestCase):
    def test_loads_contiguous_snapshots(self):
        write_archive(self.root, (2020, 6))
        loaded = up.load_snapshots(self.root)
        self.assertEqual(list(loaded), [(2020, 4), (2020, 5), (2020, 6)])
        self.assertEqual(loaded[(2020, 5)][0], "archive/2020/2020-05.json")

    def test_gap_fails(self):
        write_archive(self.root, (2020, 6))
        self.snap(2020, 5).unlink()
        with self.assertRaisesRegex(up.ArchiveError, "2020-05"):
            up.load_snapshots(self.root)

    def test_zero_snapshots_fail(self):
        with self.assertRaisesRegex(up.ArchiveError, "no snapshots"):
            up.load_snapshots(self.root)

    def test_filename_must_match_year_and_month(self):
        write_archive(self.root, (2020, 5))
        write_json(self.snap(2020, 5), read_json(self.snap(2020, 4)))
        with self.assertRaisesRegex(up.ArchiveError, "archive/2020/2020-05.json"):
            up.load_snapshots(self.root)

    def test_folder_must_match_year(self):
        write_archive(self.root, (2020, 4))
        wrong = self.root / "archive" / "2021" / "2020-05.json"
        write_json(wrong, up.normalize_response(api_payload(2020, 5), 2020, 5))
        with self.assertRaisesRegex(up.ArchiveError, "folder"):
            up.load_snapshots(self.root)

    def test_hand_edited_partial_snapshot_fails(self):
        write_archive(self.root, (2020, 5))
        data = read_json(self.snap(2020, 5))
        data["challenges"].pop()
        write_json(self.snap(2020, 5), data)
        with self.assertRaisesRegex(up.ArchiveError, "partial"):
            up.load_snapshots(self.root)

    def test_snapshot_field_rules_apply(self):
        write_archive(self.root, (2020, 4))
        data = read_json(self.snap(2020, 4))
        data["challenges"][3]["difficulty"] = "Unknown"
        write_json(self.snap(2020, 4), data)
        with self.assertRaisesRegex(up.ArchiveError, "invalid"):
            up.load_snapshots(self.root)

    def test_snapshot_before_first_month_fails(self):
        write_archive(self.root, (2020, 4))
        write_json(self.snap(2020, 3), up.normalize_response(api_payload(2020, 3), 2020, 3))
        with self.assertRaisesRegex(up.ArchiveError, "2020-03"):
            up.load_snapshots(self.root)


def weekly_rows(rows, prefix=""):
    return [r for r in rows if r["type"] == "weekly" and r["date"].startswith(prefix)]


def table_rows(markdown: str, heading: str) -> list[str]:
    """Data rows of the table under `heading`, without the header and alignment lines."""
    if heading not in markdown:
        return []
    section = markdown.split(heading + "\n\n", 1)[1].split("\n\n", 1)[0]
    return section.strip("\n").split("\n")[2:]


def cells(row: str) -> list[str]:
    """Split a Markdown table row on unescaped pipes."""
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)[1:-1]]


class SpilloverTests(ArchiveTestCase):
    def setUp(self):
        super().setUp()
        write_archive(self.root, (2026, 6), weeklies={
            (2026, 5): own_weeklies(2026, 5) + [confusing_number_ii()],
            (2026, 6): own_weeklies(2026, 6),
        })

    def test_spilled_weekly_is_grouped_by_its_own_date(self):
        rows = up.merge_snapshots(up.load_snapshots(self.root))
        june = weekly_rows(rows, "2026-06")
        self.assertEqual(len(june), 6)
        self.assertEqual([r["slug"] for r in june].count("confusing-number-ii"), 1)
        self.assertEqual(len(weekly_rows(rows, "2026-05")), 5)
        self.assertEqual([r["date"] for r in june][:2], ["2026-06-01", "2026-06-05"])

    def test_site_json_holds_spilled_weekly_once(self):
        up.build(self.root)
        site = read_json(self.root / "docs" / "challenges.json")
        matches = [r for r in site["challenges"] if r["slug"] == "confusing-number-ii"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["date"], "2026-06-05")
        self.assertEqual(matches[0]["type"], "weekly")

    def test_june_page_lists_spilled_weekly_and_may_page_does_not(self):
        up.build(self.root)
        june = (self.root / "archive" / "2026" / "2026-06.md").read_text(encoding="utf-8")
        may = (self.root / "archive" / "2026" / "2026-05.md").read_text(encoding="utf-8")
        self.assertEqual(june.count("Confusing Number II"), 1)
        self.assertIn("| 2026-06-05 | 1088 | [Confusing Number II]"
                      "(https://leetcode.com/problems/confusing-number-ii/) | Hard | Yes |", june)
        self.assertNotIn("Confusing Number II", may)
        self.assertEqual(len(table_rows(june, "## Weekly challenges")), 6)
        self.assertEqual(len(table_rows(may, "## Weekly challenges")), 5)

    def test_build_leaves_snapshots_byte_identical(self):
        before = {p: p.read_bytes() for p in (self.snap(2026, 5), self.snap(2026, 6))}
        up.build(self.root)
        up.build(self.root)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)


class HoldBackTests(ArchiveTestCase):
    def setUp(self):
        super().setUp()
        self.weeklies = {
            (2026, 8): own_weeklies(2026, 8) + [counting_elements()],
            (2026, 9): own_weeklies(2026, 9),
        }
        write_archive(self.root, (2026, 8), weeklies=self.weeklies)

    def test_weekly_after_latest_snapshot_is_held_back(self):
        rows = up.merge_snapshots(up.load_snapshots(self.root))
        self.assertEqual(weekly_rows(rows, "2026-09"), [])
        self.assertTrue(all(r["date"] <= "2026-08-31" for r in rows))

    def test_site_json_excludes_held_back_weekly(self):
        up.build(self.root)
        site = read_json(self.root / "docs" / "challenges.json")
        self.assertEqual(site["to"], "2026-08-31")
        self.assertNotIn("counting-elements", [r["slug"] for r in site["challenges"]])
        self.assertNotIn("2026-09-05", [r["date"] for r in site["challenges"]])
        self.assertTrue(all(site["from"] <= r["date"] <= site["to"] for r in site["challenges"]))
        self.assertIn("counting-elements", self.snap(2026, 8).read_text(encoding="utf-8"))

    def test_no_page_for_held_back_month(self):
        up.build(self.root)
        self.assertFalse((self.root / "archive" / "2026" / "2026-09.md").exists())
        august = (self.root / "archive" / "2026" / "2026-08.md").read_text(encoding="utf-8")
        self.assertNotIn("Counting Elements", august)
        self.assertEqual(len(table_rows(august, "## Weekly challenges")), 5)

    def test_held_back_weekly_appears_once_september_is_saved(self):
        write_archive(self.root, (2026, 9), weeklies=self.weeklies, start=(2026, 9))
        rows = up.merge_snapshots(up.load_snapshots(self.root))
        september = weekly_rows(rows, "2026-09")
        self.assertEqual(len(september), 6)
        self.assertEqual([r["date"] for r in september].count("2026-09-05"), 1)
        up.build(self.root)
        site = read_json(self.root / "docs" / "challenges.json")
        self.assertEqual([r["date"] for r in weekly_rows(site["challenges"])].count("2026-09-05"), 1)


class SiteJsonTests(ArchiveTestCase):
    def setUp(self):
        super().setUp()
        april = api_payload(2020, 4)
        record = april["data"]["dailyCodingChallengeV2"]
        record["challenges"][0] = api_item("2020-04-01", "1000", title="N × 3", slug="n-times-3")
        record["challenges"][1] = api_item("2020-04-02", "999", slug="nine-nine-nine", paid=True)
        up.save_snapshot(self.root, up.normalize_response(april, 2020, 4))
        write_archive(self.root, (2020, 8), start=(2020, 5), weeklies={
            (2020, 8): [api_item("2020-08-01", "5", slug="weekly-five", paid=True),
                        api_item("2020-08-08", "10", slug="weekly-ten", paid=False)],
        })
        self.site_path = self.root / "docs" / "challenges.json"

    def test_shape_and_counts(self):
        up.build(self.root)
        site = read_json(self.site_path)
        self.assertEqual(list(site), ["source", "from", "to", "dailyCount", "weeklyCount", "challenges"])
        self.assertEqual(site["source"], "https://leetcode.com/graphql/ dailyCodingChallengeV2")
        self.assertEqual(site["from"], "2020-04-01")
        self.assertEqual(site["to"], "2020-08-31")
        self.assertEqual(site["dailyCount"], 30 + 31 + 30 + 31 + 31)
        self.assertEqual(site["weeklyCount"], 2)
        self.assertEqual(len(site["challenges"]), site["dailyCount"] + site["weeklyCount"])
        first = site["challenges"][0]
        self.assertEqual(list(first), ["date", "type", "id", "title", "slug", "difficulty", "isPaidOnly", "url"])
        self.assertEqual(first["title"], "N × 3")
        self.assertEqual(first["url"], "https://leetcode.com/problems/n-times-3/")
        self.assertIs(site["challenges"][1]["isPaidOnly"], True)
        self.assertIn("N × 3", self.site_path.read_text(encoding="utf-8"))

    def test_sorted_by_date_then_daily_first_then_numeric_id(self):
        up.build(self.root)
        rows = read_json(self.site_path)["challenges"]
        self.assertEqual(rows, sorted(rows, key=lambda r: (r["date"], r["type"] != "daily", int(r["id"]))))
        on_first = [(r["type"], r["id"]) for r in rows if r["date"] == "2020-08-01"]
        self.assertEqual(on_first, [("daily", "20200801"), ("weekly", "5")])

    def test_site_json_is_byte_stable(self):
        first = up.build(self.root)
        self.assertIn("docs/challenges.json", first["written"])
        data = self.site_path.read_bytes()
        mtime = self.site_path.stat().st_mtime_ns
        second = up.build(self.root)
        self.assertEqual(second["written"], [])
        self.assertEqual(self.site_path.read_bytes(), data)
        self.assertEqual(self.site_path.stat().st_mtime_ns, mtime)
        self.assertTrue(data.endswith(b"}\n") and not data.endswith(b"\n\n"))


class ConflictTests(ArchiveTestCase):
    def merge(self):
        return up.merge_snapshots(up.load_snapshots(self.root))

    def test_same_weekly_with_two_titles_fails_naming_both_files(self):
        renamed = confusing_number_ii("2026-06-08")
        renamed["question"]["title"] = "Confusing Number 2"
        write_archive(self.root, (2026, 6), weeklies={
            (2026, 5): [confusing_number_ii("2026-06-08")],
            (2026, 6): [renamed],
        })
        with self.assertRaises(up.ArchiveError) as ctx:
            self.merge()
        self.assertIn("archive/2026/2026-05.json", str(ctx.exception))
        self.assertIn("archive/2026/2026-06.json", str(ctx.exception))

    def test_identical_weekly_in_two_snapshots_is_kept_once(self):
        write_archive(self.root, (2026, 6), weeklies={
            (2026, 5): [confusing_number_ii("2026-06-08")],
            (2026, 6): [confusing_number_ii("2026-06-08")],
        })
        self.assertEqual(len(weekly_rows(self.merge(), "2026-06-08")), 1)

    def test_two_slugs_on_one_weekly_date_fail(self):
        write_archive(self.root, (2026, 6), weeklies={
            (2026, 5): [confusing_number_ii("2026-06-08")],
            (2026, 6): [counting_elements("2026-06-08")],
        })
        with self.assertRaisesRegex(up.ArchiveError, "two weeklies on 2026-06-08"):
            self.merge()

    def test_two_dailies_on_one_date_fail(self):
        write_archive(self.root, (2020, 5))
        snapshots = up.load_snapshots(self.root)
        name, data = snapshots[(2020, 5)]
        data["challenges"].append(dict(data["challenges"][0], id="1", slug="another"))
        with self.assertRaisesRegex(up.ArchiveError, "two dailies on 2020-05-01"):
            up.merge_snapshots(snapshots)

    def test_duplicate_daily_in_stored_snapshot_fails_the_build(self):
        write_archive(self.root, (2020, 5))
        data = read_json(self.snap(2020, 5))
        data["challenges"][1]["date"] = data["challenges"][0]["date"]
        write_json(self.snap(2020, 5), data)
        with self.assertRaisesRegex(up.ArchiveError, "invalid"):
            self.merge()

    def test_weekly_before_first_snapshot_month_fails(self):
        write_archive(self.root, (2020, 5), weeklies={(2020, 4): [confusing_number_ii("2020-03-29")]})
        with self.assertRaisesRegex(up.ArchiveError, "before the first snapshot month"):
            self.merge()


class MarkdownPageTests(ArchiveTestCase):
    def page(self, year: int, month: int) -> str:
        return (self.root / "archive" / f"{year:04d}" / f"{year:04d}-{month:02d}.md").read_text(encoding="utf-8")

    def test_first_page_layout_without_weeklies(self):
        write_archive(self.root, (2020, 5))
        up.build(self.root)
        text = self.page(2020, 4)
        self.assertTrue(text.startswith(
            "<!-- Generated by scripts/update_potd.py. Do not edit. -->\n"
            "\n"
            "# April 2020\n"
            "\n"
            "[All months](../README.md) · [May 2020 →](../2020/2020-05.md)\n"
            "\n"
            "## Daily challenges\n"
            "\n"
            "| Date | # | Title | Difficulty | Premium |\n"
            "| :--- | ---: | :--- | :--- | :---: |\n"
            "| 2020-04-01 | 20200401 | [Problem 20200401](https://leetcode.com/problems/problem-20200401/)"
            " | Medium | No |\n"
        ))
        self.assertTrue(text.endswith("| 2020-04-30 | 20200430 | [Problem 20200430]"
                                      "(https://leetcode.com/problems/problem-20200430/) | Medium | No |\n"))
        self.assertNotIn("## Weekly challenges", text)
        self.assertNotIn("\n\n\n", text)
        self.assertEqual(len(table_rows(text, "## Daily challenges")), 30)

    def test_title_escaping_keeps_five_cells(self):
        april = api_payload(2020, 4)
        record = april["data"]["dailyCodingChallengeV2"]
        record["challenges"][0] = api_item("2020-04-01", "432", title="All O`one Data Structure",
                                           slug="all-oone-data-structure")
        record["challenges"][1] = api_item("2020-04-02", "7", title="a|b \\ *x* _y_ [z] <w> N × 3", slug="odd-title")
        up.save_snapshot(self.root, up.normalize_response(april, 2020, 4))
        up.build(self.root)
        rows = table_rows(self.page(2020, 4), "## Daily challenges")
        self.assertIn("[All O\\`one Data Structure](", rows[0])
        self.assertIn("[a\\|b \\\\ \\*x\\* \\_y\\_ \\[z\\] \\<w\\> N × 3](", rows[1])
        for row in rows:
            self.assertEqual(len(cells(row)), 5, row)

    def test_premium_column_in_both_tables(self):
        april = api_payload(2020, 4, weeklies=[
            api_item("2020-04-01", "1", slug="free-weekly", paid=False),
            api_item("2020-04-08", "2", slug="paid-weekly", paid=True),
        ])
        april["data"]["dailyCodingChallengeV2"]["challenges"][6]["question"]["isPaidOnly"] = True
        up.save_snapshot(self.root, up.normalize_response(april, 2020, 4))
        up.build(self.root)
        text = self.page(2020, 4)
        daily = {cells(r)[0]: cells(r)[4] for r in table_rows(text, "## Daily challenges")}
        weekly = {cells(r)[0]: cells(r)[4] for r in table_rows(text, "## Weekly challenges")}
        self.assertEqual(daily["2020-04-07"], "Yes")
        self.assertEqual(daily["2020-04-06"], "No")
        self.assertEqual(weekly, {"2020-04-01": "No", "2020-04-08": "Yes"})

    def test_navigation(self):
        write_archive(self.root, (2026, 2))
        up.build(self.root)
        first = self.page(2020, 4).splitlines()[4]
        latest = self.page(2026, 2).splitlines()[4]
        january = self.page(2026, 1).splitlines()[4]
        self.assertNotIn("←", first)
        self.assertTrue(first.startswith("[All months](../README.md) · "))
        self.assertEqual(latest, "[← January 2026](../2026/2026-01.md) · [All months](../README.md)")
        self.assertEqual(
            january,
            "[← December 2025](../2025/2025-12.md) · [All months](../README.md) · "
            "[February 2026 →](../2026/2026-02.md)",
        )


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
