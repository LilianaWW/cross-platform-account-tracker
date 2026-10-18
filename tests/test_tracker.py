import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tracker import build_report, load_inputs, parse_date, write_reports


FIXTURES = Path(__file__).resolve().parents[1] / "examples"


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.accounts = [{"account_id": "001", "account_name": "Example", "group": "A"}]
        self.obs = {("001", "p", date(2026, 9, 1)): 0,
                    ("001", "p", date(2026, 9, 2)): 3,
                    ("001", "p", date(2026, 8, 1)): 1,
                    ("001", "p", date(2026, 8, 2)): 1}

    def report(self, day=date(2026, 9, 2), platforms=None):
        return build_report(self.accounts, self.obs, day, platforms or ["p"])

    def test_zero_is_observed_and_missing_is_unknown(self):
        report = self.report(date(2026, 9, 1), ["p", "absent"])
        self.assertEqual(report["daily"][0]["posts"], 0)
        self.assertEqual(report["daily"][0]["status"], "observed")
        self.assertIsNone(report["daily"][1]["posts"])
        self.assertEqual(report["monthly"][1]["current_status"], "missing")
        self.assertEqual(report["summary"]["daily_observed_account_platforms"], 1)

    def test_complete_period_change_and_cutoff(self):
        self.obs[("001", "p", date(2026, 9, 3))] = 999
        report = self.report()
        self.assertEqual(report["monthly"][0]["current_posts"], 3)
        self.assertEqual(report["monthly"][0]["change_posts"], 1)
        self.assertEqual(report["summary"]["outside_window_rows"], 1)

    def test_incomplete_current_has_no_change_or_rank(self):
        del self.obs[("001", "p", date(2026, 9, 1))]
        report = self.report()
        self.assertEqual(report["monthly"][0]["current_status"], "partial")
        self.assertIsNone(report["monthly"][0]["change_posts"])
        self.assertEqual(report["rankings"], [])
        self.assertEqual(report["groups"][0]["observed_account_days"], 1)

    def test_incomplete_previous_still_allows_current_rank(self):
        del self.obs[("001", "p", date(2026, 8, 2))]
        report = self.report()
        self.assertIsNone(report["monthly"][0]["change_posts"])
        self.assertEqual(report["rankings"][0]["rank"], 1)

    def test_unlisted_account_and_platform_are_excluded(self):
        self.obs[("unknown", "p", date(2026, 9, 2))] = 1000
        self.obs[("001", "other", date(2026, 9, 2))] = 1000
        report = self.report()
        self.assertEqual(report["summary"]["excluded_scope_rows"], 2)
        self.assertEqual(report["summary"]["current_observed_posts"], 3)

    def test_year_and_leap_month_boundaries(self):
        january = self.report(date(2026, 1, 1))["summary"]
        self.assertEqual(january["previous_window"], ["2025-12-01", "2025-12-01"])
        leap = self.report(date(2024, 3, 31))
        self.assertEqual(leap["summary"]["previous_window"], ["2024-02-01", "2024-02-29"])
        self.assertEqual(leap["monthly"][0]["previous_expected_days"], 29)

    def test_rank_ties_share_rank(self):
        self.accounts.append({"account_id": "002", "account_name": "Second", "group": "B"})
        self.obs[("002", "p", date(2026, 9, 1))] = 2
        self.obs[("002", "p", date(2026, 9, 2))] = 1
        self.assertEqual([row["rank"] for row in self.report()["rankings"]], [1, 1])

    def test_fixture_totals_and_export(self):
        accounts, observations = load_inputs(FIXTURES)
        report = build_report(accounts, observations, date(2026, 9, 5), ["weibo", "douyin", "xiaohongshu"])
        self.assertEqual(accounts[0]["account_id"], "001")
        self.assertEqual(report["summary"]["current_observed_account_days"], 58)
        self.assertEqual(report["summary"]["current_expected_account_days"], 60)
        self.assertEqual(report["summary"]["daily_observed_account_platforms"], 11)
        self.assertEqual(report["summary"]["excluded_scope_rows"], 2)
        self.assertEqual(len(report["rankings"]), 11)
        expected = sum(value for (account, platform, day), value in observations.items()
                       if account in {"001", "002", "003", "004"}
                       and platform in {"weibo", "douyin", "xiaohongshu"}
                       and date(2026, 9, 1) <= day <= date(2026, 9, 5))
        self.assertEqual(report["summary"]["current_observed_posts"], expected)
        with tempfile.TemporaryDirectory() as folder:
            write_reports(report, folder)
            self.assertEqual(len(list(Path(folder).iterdir())), 6)
            with (Path(folder) / "daily.csv").open(encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream))
            missing = next(r for r in rows if r["account_id"] == "003" and r["platform"] == "xiaohongshu")
            self.assertEqual(missing["posts"], "")
            self.assertEqual(json.loads((Path(folder) / "summary.json").read_text())["accounts"], 4)

    def test_html_escapes_names_and_csv_neutralizes_formulas(self):
        self.accounts[0]["account_name"] = '=HYPERLINK("x")<script>'
        with tempfile.TemporaryDirectory() as folder:
            write_reports(self.report(), folder)
            self.assertNotIn("<script>", (Path(folder) / "report.html").read_text())
            with (Path(folder) / "daily.csv").open(encoding="utf-8-sig") as stream:
                self.assertTrue(next(csv.DictReader(stream))["account_name"].startswith("'="))

    def test_invalid_dates_and_platform_selection(self):
        for value in ("2026-9-1", "2026-02-30", "hello"):
            with self.assertRaises(ValueError):
                parse_date(value)
        with self.assertRaises(ValueError):
            self.report(platforms=["p", "p"])


class InputTests(unittest.TestCase):
    def load(self, accounts, observations):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "accounts.csv").write_text(accounts)
            (Path(folder) / "observations.csv").write_text(observations)
            return load_inputs(folder)

    def test_reject_duplicate_account_and_observation_keys(self):
        roster = "account_id,account_name,group\n001,A,G\n"
        header = "date,account_id,platform,posts\n"
        with self.assertRaisesRegex(ValueError, "unique"):
            self.load(roster + "001,B,G\n", header)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.load(roster, header + "2026-09-01,001,p,1\n2026-09-01,001,p,2\n")

    def test_reject_invalid_counts_and_malformed_rows(self):
        roster = "account_id,account_name,group\n001,A,G\n"
        header = "date,account_id,platform,posts\n"
        for count in ("-1", "1.5", "", "NaN"):
            with self.assertRaises(ValueError):
                self.load(roster, header + f"2026-09-01,001,p,{count}\n")
        with self.assertRaises(ValueError):
            self.load(roster, header + "2026-09-01,001,p,1,extra\n")


if __name__ == "__main__":
    unittest.main()
