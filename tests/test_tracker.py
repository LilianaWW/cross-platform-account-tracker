import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tracker import (ALL_METRICS, GROUP_BY, METRICS, RANK_BY, build_report,
                     html_report, load_inputs, main, parse_date, write_reports)

FIXTURES = Path(__file__).resolve().parents[1] / "examples"
DAY = date(2026, 9, 2)


def counts(posts=2, reposts=3, likes=4, comments=5):
    return dict(zip(METRICS, (posts, reposts, likes, comments)))


class InputTests(unittest.TestCase):
    def load(self, observations, accounts="account_id,account_name,group\n001,A,G\n"):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "accounts.csv").write_text(accounts)
            (Path(folder) / "observations.csv").write_text(observations)
            return load_inputs(folder)

    def test_legacy_columns_and_default_metadata(self):
        accounts, obs = self.load("date,account_id,platform,posts\n2026-09-02,001,p,0\n")
        self.assertEqual(accounts[0]["account_id"], "001")
        self.assertEqual(accounts[0]["tracking_tier"], "standard")
        self.assertTrue(accounts[0]["active"])
        self.assertEqual(accounts[0]["group"], "G")
        self.assertEqual(obs[("001", "p", DAY)], counts(0, None, None, None))

    def test_missing_columns_blank_and_zero(self):
        _, obs = self.load("date,account_id,platform,posts_published,likes_gained\n2026-09-02,001,p,,0\n")
        self.assertEqual(obs[("001", "p", DAY)], counts(None, None, 0, None))
        _, obs = self.load("date,account_id,platform\n2026-09-02,001,p\n")
        self.assertTrue(all(value is None for value in obs[("001", "p", DAY)].values()))

    def test_new_posts_column_takes_precedence_even_when_blank(self):
        _, obs = self.load("date,account_id,platform,posts,posts_published\n2026-09-02,001,p,99,\n")
        self.assertIsNone(obs[("001", "p", DAY)]["posts_published"])

    def test_optional_account_columns_and_active(self):
        accounts, _ = self.load("date,account_id,platform\n", "account_id,account_name,tracking_tier,account_type,active\n001,A,priority,competitor,false\n")
        self.assertEqual(accounts[0]["group"], "")
        self.assertFalse(accounts[0]["active"])
        self.assertEqual(accounts[0]["account_type"], "competitor")

    def test_reject_invalid_metadata(self):
        for column, value in (("tracking_tier", "vip"), ("account_type", "brand"), ("active", "maybe")):
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.load("date,account_id,platform\n", f"account_id,account_name,{column}\n001,A,{value}\n")

    def test_reject_duplicates_and_invalid_counts(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            self.load("date,account_id,platform\n", "account_id,account_name\n001,A\n001,B\n")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.load("date,account_id,platform,posts\n2026-09-02,001,p,1\n2026-09-02,001,p,2\n")
        for metric in METRICS:
            for value in ("-1", "1.5", "NaN"):
                with self.subTest(metric=metric, value=value), self.assertRaises(ValueError):
                    self.load(f"date,account_id,platform,{metric}\n2026-09-02,001,p,{value}\n")
        with self.assertRaises(ValueError):
            self.load("date,account_id,platform,posts\n2026-09-02,001,p,1,extra\n")
        with self.assertRaises(ValueError):
            self.load("date,account_id,platform,posts,posts\n")


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.accounts = [{"account_id": "001", "account_name": "Example", "group": "A",
                          "business_group": "Editorial", "tracking_tier": "priority",
                          "account_type": "owned", "market": "APAC"}]
        self.obs = {("001", "p", date(2026, 9, 1)): counts(),
                    ("001", "p", DAY): counts(),
                    ("001", "p", date(2026, 8, 1)): counts(1, 1, 1, 1),
                    ("001", "p", date(2026, 8, 2)): counts(1, 1, 1, 1)}

    def report(self, day=DAY, platforms=None, **kwargs):
        return build_report(self.accounts, self.obs, day, platforms or ["p"], **kwargs)

    def test_independent_coverage_and_conservative_engagement(self):
        self.obs[("001", "p", DAY)] = counts(0, None, 0, 0)
        row = self.report()["monthly"][0]
        self.assertEqual(row["current_posts_published"], 2)
        self.assertEqual(row["current_likes_gained_status"], "complete")
        self.assertEqual(row["current_reposts_gained_status"], "partial")
        self.assertEqual(row["current_reposts_gained_coverage"], 0.5)
        self.assertIsNone(row["current_engagement"])
        self.assertEqual(row["current_engagement_observed_days"], 1)
        self.assertIsNone(row["current_engagement_per_post"])
        self.assertIsNone(row["change_reposts_gained"])
        self.assertEqual(row["change_posts_published"], 0)
        self.assertEqual(len(self.report()["rankings"]), 1)
        self.assertEqual(self.report(rank_by="engagement")["rankings"], [])

    def test_engagement_and_weighted_period_ratio(self):
        self.obs[("001", "p", DAY)] = counts(4, 2, 6, 4)
        report = self.report()
        self.assertEqual(report["daily"][0]["engagement"], 12)
        self.assertEqual(report["daily"][0]["engagement_per_post"], 3)
        row = report["monthly"][0]
        self.assertEqual(row["current_engagement"], 24)
        self.assertEqual(row["current_engagement_per_post"], 4)
        self.assertEqual(row["change_engagement"], 18)
        self.assertEqual(report["groups"][0]["engagement_per_post"], 4)

    def test_zero_posts_and_unknown_posts(self):
        for value in (0, None):
            self.obs[("001", "p", DAY)] = counts(value, 1, 2, 3)
            row = self.report()["daily"][0]
            self.assertEqual(row["engagement"], 6)
            self.assertIsNone(row["engagement_per_post"])
            self.assertEqual(row["posts_published_status"], "complete" if value == 0 else "missing")
        self.obs[("001", "p", DAY)] = counts(0, 0, 0, 0)
        self.assertEqual(self.report()["daily"][0]["engagement"], 0)
        self.assertIsNone(self.report()["daily"][0]["engagement_per_post"])

    def test_missing_rows_and_groups_remain_unknown(self):
        report = self.report(platforms=["absent"])
        for metric in ALL_METRICS:
            self.assertIsNone(report["daily"][0][metric])
            self.assertIsNone(report["groups"][0][metric])
            self.assertEqual(report["groups"][0][metric + "_status"], "missing")
            self.assertIsNone(report["summary"]["current_metrics"][metric]["value"])

    def test_no_engagement_from_disjoint_component_days(self):
        self.obs[("001", "p", date(2026, 9, 1))] = counts(1, 2, None, 3)
        self.obs[("001", "p", DAY)] = counts(1, None, 4, 3)
        row = self.report()["monthly"][0]
        self.assertIsNone(row["current_engagement"])
        self.assertEqual(row["current_engagement_status"], "missing")

    def test_dynamic_groups_priority_and_inactive(self):
        for dimension in GROUP_BY:
            report = self.report(group_by=dimension)
            self.assertEqual(report["groups"][0]["group_value"], self.accounts[0][dimension])
            self.assertEqual(report["groups"][0]["group_by"], dimension)
            self.assertEqual(report["priority"], report["monthly"])
        self.accounts.append({"account_id": "002", "account_name": "Inactive", "active": False, "tracking_tier": "priority"})
        self.obs[("002", "p", DAY)] = counts(999, 999, 999, 999)
        report = self.report()
        self.assertEqual(report["summary"]["accounts"], 1)
        self.assertEqual(len(report["priority"]), 1)
        self.assertEqual(report["summary"]["excluded_scope_rows"], 1)
        self.accounts[0]["tracking_tier"] = "standard"
        self.assertEqual(self.report()["priority"], [])

    def test_rankings_are_platform_local_with_ties_and_selected_coverage(self):
        self.accounts += [{"account_id": "002", "account_name": "Second"},
                          {"account_id": "003", "account_name": "Third"}]
        for day in (date(2026, 9, 1), DAY):
            self.obs[("002", "p", day)] = counts(None, 3, 4, 5)
            self.obs[("003", "p", day)] = counts(9, 1, 1, 1)
            self.obs[("003", "q", day)] = counts(1, 0, 0, 0)
        report = self.report(platforms=["p", "q"], rank_by="engagement")
        self.assertEqual([(r["platform"], r["account_id"], r["rank"]) for r in report["rankings"]],
                         [("p", "001", 1), ("p", "002", 1), ("p", "003", 3), ("q", "003", 1)])
        for metric in RANK_BY:
            rows = self.report(rank_by=metric)["rankings"]
            self.assertTrue(all(r["rank_by"] == metric for r in rows))
        rows = self.report()["rankings"]
        self.assertEqual([r["account_id"] for r in rows], ["003", "001"])

    def test_group_coverage_counts_account_days(self):
        self.accounts.append({"account_id": "002", "account_name": "Missing", "group": "A"})
        row = self.report()["groups"][0]
        self.assertEqual(row["posts_published"], 4)
        self.assertEqual(row["posts_published_coverage"], 0.5)
        self.assertEqual(row["posts_published_expected_days"], 4)
        self.assertIsNone(row["engagement"])

    def test_legacy_integer_observations(self):
        self.obs = {("001", "p", date(2026, 9, 1)): 0, ("001", "p", DAY): 3}
        row = self.report()["monthly"][0]
        self.assertEqual(row["current_posts_published"], 3)
        self.assertEqual(row["current_posts_published_status"], "complete")
        self.assertIsNone(row["current_engagement"])

    def test_cutoff_scope_and_month_boundaries(self):
        self.obs[("001", "p", date(2026, 9, 3))] = counts(999)
        self.obs[("unknown", "p", DAY)] = counts(999)
        self.obs[("001", "other", DAY)] = counts(999)
        summary = self.report()["summary"]
        self.assertEqual(summary["outside_window_rows"], 1)
        self.assertEqual(summary["excluded_scope_rows"], 2)
        self.assertEqual(summary["current_metrics"]["posts_published"]["value"], 4)
        self.assertEqual(self.report(date(2026, 1, 1))["summary"]["previous_window"], ["2025-12-01", "2025-12-01"])
        self.assertEqual(self.report(date(2024, 3, 31))["summary"]["previous_window"], ["2024-02-01", "2024-02-29"])

    def test_incomplete_previous_has_no_change_but_can_rank(self):
        del self.obs[("001", "p", date(2026, 8, 2))]
        report = self.report()
        self.assertIsNone(report["monthly"][0]["change_engagement"])
        self.assertEqual(report["rankings"][0]["rank"], 1)

    def test_html_csv_json_and_empty_exports(self):
        self.accounts[0]["account_name"] = '=HYPERLINK("x")<script>'
        report = self.report(platforms=["p", "missing"], group_by="market", rank_by="likes_gained")
        with tempfile.TemporaryDirectory() as folder:
            write_reports(report, folder)
            rendered = (Path(folder) / "report.html").read_text()
            self.assertNotIn("<script>", rendered)
            self.assertIn("Priority accounts", rendered)
            self.assertIn("Groups · market", rendered)
            self.assertIn("Within-platform rankings · likes_gained", rendered)
            self.assertTrue(all(metric in rendered for metric in ALL_METRICS))
            for name in ("daily", "monthly", "priority", "rankings", "groups"):
                with (Path(folder) / f"{name}.csv").open(encoding="utf-8-sig") as stream:
                    self.assertEqual(len(list(csv.DictReader(stream))), len(report[name]))
            with (Path(folder) / "daily.csv").open(encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream))
                self.assertTrue(rows[0]["account_name"].startswith("'="))
                self.assertEqual(rows[1]["engagement"], "")
            self.assertEqual(json.loads((Path(folder) / "report.json").read_text()), report)
            self.assertEqual(json.loads((Path(folder) / "summary.json").read_text()), report["summary"])
            self.accounts[0]["active"] = False
            write_reports(self.report(), folder)
            with (Path(folder) / "priority.csv").open(encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                self.assertIn("current_engagement", reader.fieldnames)
                self.assertEqual(list(reader), [])

    def test_invalid_arguments(self):
        for value in ("2026-9-1", "2026-02-30", "hello"):
            with self.assertRaises(ValueError):
                parse_date(value)
        for kwargs in ({"platforms": ["p", "p"]}, {"group_by": "owner"}, {"rank_by": "unknown"}):
            with self.assertRaises(ValueError):
                self.report(**kwargs)

    def test_examples_and_cli_parameters(self):
        accounts, obs = load_inputs(FIXTURES)
        self.assertEqual(accounts[0]["account_id"], "001")
        report = build_report(accounts, obs, date(2026, 9, 5), ["weibo", "douyin", "xiaohongshu"])
        self.assertEqual(report["summary"]["current_metrics"]["posts_published"]["observed_days"], 58)
        self.assertEqual(report["summary"]["current_metrics"]["posts_published"]["expected_days"], 60)
        self.assertTrue(report["priority"])
        with tempfile.TemporaryDirectory() as folder:
            with patch("sys.argv", ["tracker.py", "--input", str(FIXTURES), "--date", "2026-09-05",
                                    "--output", folder, "--group-by", "business_group", "--rank-by", "engagement"]), redirect_stdout(io.StringIO()):
                main()
            summary = json.loads((Path(folder) / "summary.json").read_text())
            self.assertEqual(summary["group_by"], "business_group")
            self.assertEqual(summary["rank_by"], "engagement")


if __name__ == "__main__":
    unittest.main()
