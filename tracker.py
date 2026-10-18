"""Portable account publication reports. Python 3.9+, standard library only."""

import argparse
import calendar
import csv
import html
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


def read_csv(path, required):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not set(required).issubset(reader.fieldnames):
            raise ValueError(f"{path}: required columns: {', '.join(required)}")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"{path}: duplicate column names")
        rows = []
        for number, row in enumerate(reader, 2):
            if None in row or any(row.get(key) is None for key in required):
                raise ValueError(f"{path}:{number}: malformed CSV row")
            values = {key: row[key].strip() for key in required}
            if any(not value for value in values.values()):
                raise ValueError(f"{path}:{number}: required values cannot be blank")
            rows.append(values)
        return rows


def parse_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"Invalid ISO date: {value}")
    return date.fromisoformat(value)


def load_inputs(directory):
    accounts = read_csv(Path(directory) / "accounts.csv", ("account_id", "account_name", "group"))
    ids = [account["account_id"] for account in accounts]
    if not accounts or len(ids) != len(set(ids)):
        raise ValueError("Account roster must be nonempty with unique account_id values")
    rows = read_csv(Path(directory) / "observations.csv", ("date", "account_id", "platform", "posts"))
    observations = {}
    for row in rows:
        day = parse_date(row["date"])
        if not re.fullmatch(r"[0-9]+", row["posts"]):
            raise ValueError("posts must be a nonnegative integer")
        key = (row["account_id"], row["platform"], day)
        if key in observations:
            raise ValueError(f"Duplicate account/platform/day: {key}")
        observations[key] = int(row["posts"])
    return accounts, observations


def summarize_period(observations, account_id, platform, start, end):
    expected = (end - start).days + 1
    values = [observations[(account_id, platform, start + timedelta(days=offset))]
              for offset in range(expected)
              if (account_id, platform, start + timedelta(days=offset)) in observations]
    count = len(values)
    return {"posts": sum(values) if values else None,
            "observed_days": count, "expected_days": expected,
            "status": "complete" if count == expected else "partial" if count else "missing"}


def build_report(accounts, observations, report_date, platforms):
    if not platforms or len(set(platforms)) != len(platforms) or any(not p for p in platforms):
        raise ValueError("Select unique, nonempty platform names")
    current_start = report_date.replace(day=1)
    previous_last = current_start - timedelta(days=1)
    previous_start = previous_last.replace(day=1)
    previous_end = previous_start.replace(day=min(report_date.day, calendar.monthrange(
        previous_start.year, previous_start.month)[1]))
    daily, monthly, rankings = [], [], []
    grouped = defaultdict(lambda: {"observed_posts": 0, "observed_account_days": 0,
                                  "expected_account_days": 0})
    for account in accounts:
        for platform in platforms:
            identity = dict(account, platform=platform)
            value = observations.get((account["account_id"], platform, report_date))
            daily.append(dict(identity, date=report_date.isoformat(), posts=value,
                              status="observed" if value is not None else "missing"))
            current = summarize_period(observations, account["account_id"], platform, current_start, report_date)
            previous = summarize_period(observations, account["account_id"], platform, previous_start, previous_end)
            comparable = current["status"] == previous["status"] == "complete"
            row = dict(identity)
            for prefix, period in (("current", current), ("previous", previous)):
                row.update({f"{prefix}_{key}": value for key, value in period.items()})
            row["change_posts"] = current["posts"] - previous["posts"] if comparable else None
            monthly.append(row)
            group = grouped[(account["group"], platform)]
            group["observed_posts"] += current["posts"] or 0
            group["observed_account_days"] += current["observed_days"]
            group["expected_account_days"] += current["expected_days"]
    for platform in platforms:
        eligible = sorted((row for row in monthly if row["platform"] == platform
                           and row["current_status"] == "complete"),
                          key=lambda row: (-row["current_posts"], row["account_id"]))
        last_total, rank = None, 0
        for position, row in enumerate(eligible, 1):
            if row["current_posts"] != last_total:
                rank = position
            last_total = row["current_posts"]
            rankings.append({key: row[key] for key in ("account_id", "account_name", "group", "platform", "current_posts")})
            rankings[-1]["rank"] = rank
    groups = [dict(group=group, platform=platform, **values)
              for (group, platform), values in sorted(grouped.items())]
    ids = {account["account_id"] for account in accounts}
    selected = {key: value for key, value in observations.items() if key[0] in ids and key[1] in platforms}
    summary = {
        "report_date": report_date.isoformat(), "accounts": len(accounts), "platforms": platforms,
        "current_window": [current_start.isoformat(), report_date.isoformat()],
        "previous_window": [previous_start.isoformat(), previous_end.isoformat()],
        "input_observations": len(observations), "excluded_scope_rows": len(observations) - len(selected),
        "outside_window_rows": sum(not (current_start <= key[2] <= report_date or previous_start <= key[2] <= previous_end) for key in selected),
        "daily_observed_posts": sum(row["posts"] for row in daily if row["posts"] is not None),
        "daily_observed_account_platforms": sum(row["posts"] is not None for row in daily),
        "daily_expected_account_platforms": len(daily),
        "current_observed_posts": sum(row["current_posts"] or 0 for row in monthly),
        "current_observed_account_days": sum(row["current_observed_days"] for row in monthly),
        "current_expected_account_days": sum(row["current_expected_days"] for row in monthly),
    }
    return {"daily": daily, "monthly": monthly, "rankings": rankings, "groups": groups, "summary": summary}


def html_report(report):
    summary = report["summary"]
    def display(value):
        return "—" if value is None else html.escape(str(value))
    def table(headers, rows):
        return '<div class="table-wrap"><table><thead><tr>' + ''.join(f"<th>{html.escape(h)}</th>" for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f"<td>{display(cell)}</td>" for cell in row) + '</tr>' for row in rows) + '</tbody></table></div>'
    comparison = table(["Account", "Platform", "Current posts", "Coverage", "Previous posts", "Coverage", "Change"],
        [(r["account_name"], r["platform"], r["current_posts"], f'{r["current_observed_days"]}/{r["current_expected_days"]}', r["previous_posts"], f'{r["previous_observed_days"]}/{r["previous_expected_days"]}', r["change_posts"]) for r in report["monthly"]])
    groups = table(["Group", "Platform", "Observed posts", "Account-day coverage"],
        [(r["group"], r["platform"], r["observed_posts"], f'{r["observed_account_days"]}/{r["expected_account_days"]}') for r in report["groups"]])
    cards = [("ACCOUNTS", summary["accounts"]), ("DAILY OBSERVED POSTS", summary["daily_observed_posts"]),
             ("MONTH-TO-DATE OBSERVED POSTS", summary["current_observed_posts"]),
             ("ACCOUNT-DAY COVERAGE", f'{summary["current_observed_account_days"]}/{summary["current_expected_account_days"]}')]
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Account Tracker · Report</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f5f7f9;color:#172d3a;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1120px;margin:auto;padding:54px 28px}header{border-top:5px solid #157d78;padding-top:28px}small{font-size:11px;font-weight:700;letter-spacing:.13em;color:#42716e}h1{font-size:34px;letter-spacing:-1px;line-height:1.2;margin:10px 0 12px}h2{font-size:20px;margin:30px 0 12px}.subtitle{color:#657582;margin:0 0 24px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card{background:white;border:1px solid #dce4e8;border-radius:10px;padding:18px}.card strong{display:block;font-size:32px;margin-top:5px}.card span{font-size:10px;letter-spacing:.07em;color:#657582;font-weight:600}.table-wrap{overflow-x:auto;background:white;border:1px solid #dce4e8;border-radius:10px}table{border-collapse:collapse;width:100%;text-align:left;font-size:13px;white-space:nowrap}th{background:#edf4f4;color:#365f5c;font-size:11px}th,td{padding:11px 14px;border-bottom:1px solid #edf0f2}tr:last-child td{border:0}.note{color:#5a6f7a;font-size:12px;margin:12px 0 24px}footer{margin-top:30px;color:#6c7b86;font-size:12px}@media(max-width:650px){main{padding:25px 16px}.cards{grid-template-columns:repeat(2,1fr)}h1{font-size:28px}}</style>
<main><header><small>WORKFLOW AUTOMATION / ACCOUNT ANALYTICS</small><h1>Cross-platform Account Tracker</h1>''' + f'<p class="subtitle">Report date: {summary["report_date"]} · Prepared from local CSV exports</p></header><div class="cards">' + ''.join(f'<div class="card"><span>{label}</span><strong>{value}</strong></div>' for label, value in cards) + '</div><h2>Publishing activity</h2><p class="note">' + html.escape('Current: ' + ' → '.join(summary["current_window"]) + ' · Previous: ' + ' → '.join(summary["previous_window"])) + '</p>' + comparison + '<p class="note">Totals reflect available observations. A dash means unknown, not zero. Changes require complete coverage in both windows. Comparison windows may differ in length at month end.</p><h2>Group overview</h2>' + groups + '<footer>Generated locally · Standard-library Python · No external services</footer></main></html>'


def csv_cell(value):
    # Prevent spreadsheet software from interpreting untrusted text as a formula.
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def write_reports(report, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    columns = {
        "daily": ["account_id", "account_name", "group", "platform", "date", "posts", "status"],
        "monthly": ["account_id", "account_name", "group", "platform", "current_posts", "current_observed_days", "current_expected_days", "current_status", "previous_posts", "previous_observed_days", "previous_expected_days", "previous_status", "change_posts"],
        "rankings": ["account_id", "account_name", "group", "platform", "current_posts", "rank"],
        "groups": ["group", "platform", "observed_posts", "observed_account_days", "expected_account_days"],
    }
    for name, fields in columns.items():
        with (destination / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows({key: csv_cell(value) for key, value in row.items()} for row in report[name])
    (destination / "summary.json").write_text(json.dumps(report["summary"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (destination / "report.html").write_text(html_report(report), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("examples"))
    parser.add_argument("--date", required=True, help="Report date, YYYY-MM-DD")
    parser.add_argument("--output", type=Path, default=Path("reports"))
    parser.add_argument("--platforms", default="weibo,douyin,xiaohongshu")
    args = parser.parse_args()
    try:
        accounts, observations = load_inputs(args.input)
        report = build_report(accounts, observations, parse_date(args.date), [p.strip() for p in args.platforms.split(",")])
        write_reports(report, args.output)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Error: {error}\n")
    print(f"Report ready: {args.output / 'report.html'}")


if __name__ == "__main__":
    main()
