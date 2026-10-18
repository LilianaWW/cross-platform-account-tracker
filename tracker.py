"""Offline multi-metric account tracking. Python 3.9+, standard library only."""

import argparse
import calendar
import csv
import html
import json
import re
from datetime import date, timedelta
from pathlib import Path

METRICS = ("posts_published", "reposts_gained", "likes_gained", "comments_gained")
ALL_METRICS = METRICS + ("engagement", "engagement_per_post")
GROUP_BY = ("group", "business_group", "tracking_tier", "account_type", "market")
RANK_BY = METRICS + ("engagement",)
ACCOUNT_FIELDS = ("account_id", "account_name", "group", "business_group", "tracking_tier",
                  "account_type", "market", "owner", "tags", "active")


def read_csv(path, required):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not set(required).issubset(reader.fieldnames):
            raise ValueError(f"{path}: required columns: {', '.join(required)}")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"{path}: duplicate column names")
        rows = []
        for number, row in enumerate(reader, 2):
            if None in row:
                raise ValueError(f"{path}:{number}: malformed CSV row")
            values = {key: (value or "").strip() for key, value in row.items()}
            if any(not values.get(key) for key in required):
                raise ValueError(f"{path}:{number}: required values cannot be blank")
            rows.append(values)
        return rows


def parse_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"Invalid ISO date: {value}")
    return date.fromisoformat(value)


def normalize_account(row):
    account = {key: row.get(key, "") for key in ACCOUNT_FIELDS}
    account["tracking_tier"] = account["tracking_tier"] or "standard"
    if account["tracking_tier"] not in ("priority", "standard", "watchlist"):
        raise ValueError("tracking_tier must be priority, standard, or watchlist")
    if account["account_type"] not in ("", "owned", "competitor", "benchmark", "creator"):
        raise ValueError("account_type must be owned, competitor, benchmark, or creator")
    active = str(account["active"]).lower()
    if active not in ("", "true", "false", "1", "0"):
        raise ValueError("active must be true/false or 1/0")
    account["active"] = active not in ("false", "0")
    return account


def load_inputs(directory):
    accounts = [normalize_account(row) for row in read_csv(
        Path(directory) / "accounts.csv", ("account_id", "account_name"))]
    ids = [account["account_id"] for account in accounts]
    if not accounts or len(ids) != len(set(ids)):
        raise ValueError("Account roster must be nonempty with unique account_id values")
    observations = {}
    for row in read_csv(Path(directory) / "observations.csv", ("date", "account_id", "platform")):
        day = parse_date(row["date"])
        values = {}
        for metric in METRICS:
            # A present new column takes precedence, even when its value is blank.
            raw = row.get(metric, row.get("posts", "") if metric == "posts_published" else "")
            if raw and not re.fullmatch(r"[0-9]+", raw):
                raise ValueError(f"{metric} must be a nonnegative integer or blank")
            values[metric] = int(raw) if raw else None
        key = (row["account_id"], row["platform"], day)
        if key in observations:
            raise ValueError(f"Duplicate account/platform/day: {key}")
        observations[key] = values
    return accounts, observations


def metric_values(value):
    # Also accept the original in-memory integer observations.
    if isinstance(value, int):
        value = {"posts_published": value}
    value = value or {}
    return {metric: value.get(metric) for metric in METRICS}


def coverage(count, expected):
    return {"observed_days": count, "expected_days": expected,
            "coverage": count / expected if expected else None,
            "status": "complete" if expected and count == expected else "partial" if count else "missing"}


def aggregate(values):
    """Base totals are observed sums; derived totals require full paired coverage."""
    result = {}
    expected = len(values)
    for metric in METRICS:
        known = [row[metric] for row in values if row[metric] is not None]
        result[metric] = dict(value=sum(known) if known else None, **coverage(len(known), expected))
    paired = [row for row in values if all(row[m] is not None for m in METRICS[1:])]
    reliable = bool(expected) and len(paired) == expected
    engagement = sum(sum(row[m] for m in METRICS[1:]) for row in paired) if reliable else None
    result["engagement"] = dict(value=engagement, **coverage(len(paired), expected))
    ratio_days = sum(all(row[m] is not None for m in METRICS) for row in values)
    posts = result["posts_published"]
    ratio = engagement / posts["value"] if reliable and posts["status"] == "complete" and posts["value"] else None
    result["engagement_per_post"] = dict(value=ratio, **coverage(ratio_days, expected))
    return result


def period_values(observations, account_id, platform, start, end):
    return [metric_values(observations.get((account_id, platform, start + timedelta(days=i))))
            for i in range((end - start).days + 1)]


def summarize_period(observations, account_id, platform, start, end):
    return aggregate(period_values(observations, account_id, platform, start, end))


def flatten(metrics, prefix=""):
    result = {}
    for metric, details in metrics.items():
        result[prefix + metric] = details["value"]
        result.update({f"{prefix}{metric}_{key}": value for key, value in details.items() if key != "value"})
    return result


def build_report(accounts, observations, report_date, platforms, group_by="group", rank_by="posts_published"):
    if not platforms or len(set(platforms)) != len(platforms) or any(not p for p in platforms):
        raise ValueError("Select unique, nonempty platform names")
    if group_by not in GROUP_BY or rank_by not in RANK_BY:
        raise ValueError("Invalid group_by or rank_by")
    accounts = [normalize_account(account) for account in accounts]
    accounts = [account for account in accounts if account["active"]]
    current_start = report_date.replace(day=1)
    previous_start = (current_start - timedelta(days=1)).replace(day=1)
    previous_end = previous_start.replace(day=min(report_date.day, calendar.monthrange(
        previous_start.year, previous_start.month)[1]))
    daily, monthly, rankings, groups = [], [], [], []
    grouped, daily_values, current_values = {}, [], []
    for account in accounts:
        for platform in platforms:
            identity = dict(account, platform=platform)
            today = metric_values(observations.get((account["account_id"], platform, report_date)))
            daily_values.append(today)
            daily.append(dict(identity, date=report_date.isoformat(), **flatten(aggregate([today]))))
            values = period_values(observations, account["account_id"], platform, current_start, report_date)
            current_values.extend(values)
            grouped.setdefault((account[group_by], platform), []).extend(values)
            current = aggregate(values)
            previous = summarize_period(observations, account["account_id"], platform, previous_start, previous_end)
            row = dict(identity, **flatten(current, "current_"), **flatten(previous, "previous_"))
            for metric in ALL_METRICS:
                a, b = current[metric], previous[metric]
                row["change_" + metric] = a["value"] - b["value"] if (
                    a["status"] == b["status"] == "complete" and a["value"] is not None and b["value"] is not None) else None
            monthly.append(row)
    for platform in platforms:
        eligible = sorted((row for row in monthly if row["platform"] == platform
                           and row[f"current_{rank_by}_status"] == "complete"
                           and row[f"current_{rank_by}"] is not None),
                          key=lambda row: (-row[f"current_{rank_by}"], row["account_id"]))
        last_total, rank = None, 0
        for position, row in enumerate(eligible, 1):
            total = row[f"current_{rank_by}"]
            if total != last_total:
                rank = position
            last_total = total
            rankings.append(dict(row, rank=rank, rank_by=rank_by, rank_value=total))
    for (group, platform), values in sorted(grouped.items()):
        groups.append(dict(group_by=group_by, group_value=group, platform=platform, **flatten(aggregate(values))))
    ids = {account["account_id"] for account in accounts}
    selected = {key: value for key, value in observations.items() if key[0] in ids and key[1] in platforms}
    summary = {
        "report_date": report_date.isoformat(), "accounts": len(accounts), "platforms": platforms,
        "group_by": group_by, "rank_by": rank_by,
        "current_window": [current_start.isoformat(), report_date.isoformat()],
        "previous_window": [previous_start.isoformat(), previous_end.isoformat()],
        "input_observations": len(observations), "excluded_scope_rows": len(observations) - len(selected),
        "outside_window_rows": sum(not (current_start <= key[2] <= report_date or previous_start <= key[2] <= previous_end) for key in selected),
        "daily_metrics": aggregate(daily_values), "current_metrics": aggregate(current_values),
    }
    return {"daily": daily, "monthly": monthly, "rankings": rankings, "groups": groups,
            "priority": [row for row in monthly if row["tracking_tier"] == "priority"], "summary": summary}


def html_report(report):
    def display(value):
        return "—" if value is None else html.escape(str(round(value, 4) if isinstance(value, float) else value))

    def table(rows, prefix="", grouping=False, ranking=False):
        headers = ["Group" if grouping else "Account", "Platform"]
        if ranking:
            headers += ["Rank"]
        headers += [label for metric in ALL_METRICS for label in (metric, metric + " coverage")]
        rendered = []
        for row in rows:
            cells = [row["group_value"] if grouping else row["account_name"], row["platform"]]
            if ranking:
                cells.append(row["rank"])
            for metric in ALL_METRICS:
                key = prefix + metric
                cells += [row[key], f'{row[key + "_observed_days"]}/{row[key + "_expected_days"]} ({row[key + "_status"]})']
            rendered.append("<tr>" + "".join(f"<td>{display(cell)}</td>" for cell in cells) + "</tr>")
        return '<div class="table-wrap"><table><thead><tr>' + "".join(f"<th>{display(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(rendered) + "</tbody></table></div>"

    summary = report["summary"]
    sections = [("Daily activity", table(report["daily"])),
                ("Priority accounts · month to date", table(report["priority"], "current_")),
                ("Month to date", table(report["monthly"], "current_")),
                ("Previous comparison window", table(report["monthly"], "previous_")),
                ("Groups · " + summary["group_by"], table(report["groups"], grouping=True)),
                ("Within-platform rankings · " + summary["rank_by"], table(report["rankings"], "current_", ranking=True))]
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Account Tracker</title>
<style>body{margin:32px;background:#f5f7f9;color:#172d3a;font:15px/1.6 system-ui}h1{border-top:5px solid #157d78;padding-top:20px}h2{margin-top:32px}.table-wrap{overflow:auto;background:white}table{border-collapse:collapse;white-space:nowrap}td,th{padding:10px;border:1px solid #dce4e8;text-align:left}th{background:#edf4f4}p{max-width:1000px}</style><main><h1>Cross-platform Account Tracker</h1>''' + f'<p>Report date: {display(summary["report_date"])} · Active accounts: {summary["accounts"]}</p>' + '<p>Current: ' + display(' → '.join(summary["current_window"])) + ' · Previous: ' + display(' → '.join(summary["previous_window"])) + '</p><p>Local CSV inputs only. Counts are daily increments, not cumulative snapshots. A dash means unknown or an undefined ratio; zero is confirmed inactivity. Base totals sum known values. Coverage is independent for each metric (account-days for groups). Engagement requires all three components on every expected day; ratios also require complete posts and a positive denominator. Rankings require complete coverage of the selected metric within each platform. Month-end comparison windows may differ in length.</p>' + ''.join(f'<h2>{display(title)}</h2>{content}' for title, content in sections) + '<footer>Generated offline · Standard-library Python · No scraping or platform APIs</footer></main></html>'


def csv_cell(value):
    # Prevent spreadsheet software from interpreting untrusted text as a formula.
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def write_reports(report, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    metric_fields = list(flatten(aggregate([])))
    monthly_fields = [prefix + key for prefix in ("current_", "previous_") for key in metric_fields]
    monthly_fields += ["change_" + metric for metric in ALL_METRICS]
    identity = list(ACCOUNT_FIELDS) + ["platform"]
    columns = {"daily": identity + ["date"] + metric_fields,
               "monthly": identity + monthly_fields,
               "priority": identity + monthly_fields,
               "rankings": identity + monthly_fields + ["rank", "rank_by", "rank_value"],
               "groups": ["group_by", "group_value", "platform"] + metric_fields}
    for name, fields in columns.items():
        with (destination / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows({key: csv_cell(value) for key, value in row.items()} for row in report[name])
    (destination / "summary.json").write_text(json.dumps(report["summary"], indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    (destination / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    (destination / "report.html").write_text(html_report(report), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("examples"))
    parser.add_argument("--date", required=True, help="Report date, YYYY-MM-DD")
    parser.add_argument("--output", type=Path, default=Path("reports"))
    parser.add_argument("--platforms", default="weibo,douyin,xiaohongshu")
    parser.add_argument("--group-by", choices=GROUP_BY, default="group")
    parser.add_argument("--rank-by", choices=RANK_BY, default="posts_published")
    args = parser.parse_args()
    try:
        accounts, observations = load_inputs(args.input)
        report = build_report(accounts, observations, parse_date(args.date),
                              [p.strip() for p in args.platforms.split(",")], args.group_by, args.rank_by)
        write_reports(report, args.output)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Error: {error}\n")
    print(f"Report ready: {args.output / 'report.html'}")


if __name__ == "__main__":
    main()
