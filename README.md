# Cross-platform Account Tracker

English · [中文](./README.zh-CN.md)

**Offline account monitoring and multi-metric analytics.**

Turn prepared daily account data into publishing and engagement summaries, priority-account views, platform rankings, and recurring reports.

## Try it

Requires Python 3.9 or later. No packages, network access, or API keys are needed.

```bash
python3 tracker.py --input examples --date 2026-09-05 --output reports
python3 tracker.py --input examples --date 2026-09-05 --group-by business_group --rank-by engagement --platforms weibo,douyin --output reports
```

Open `reports/report.html`. Re-running overwrites generated report files in that directory.

| Option | Choices / default |
| --- | --- |
| `--group-by` | `group` (default), `business_group`, `tracking_tier`, `account_type`, `market` |
| `--rank-by` | `posts_published` (default), `engagement`, `likes_gained`, `comments_gained`, `reposts_gained` |
| `--platforms` | Comma-separated names; default `weibo,douyin,xiaohongshu` |

Rankings always stay within each platform, regardless of the grouping dimension. They use current month-to-date totals, require complete coverage of the selected metric only, and assign competition ranks for ties (1, 1, 3).

## Input contract

Provide two UTF-8 CSV files. Account IDs remain strings and must already match across platforms. See [synthetic examples](./examples).

### accounts.csv

`account_id,account_name,group,business_group,tracking_tier,account_type,market,owner,tags,active`

- `account_id` and `account_name` are required; IDs must be unique.
- The original `group` is retained. All additional columns are optional, so old rosters still work.
- `tracking_tier`: `priority`, `standard`, or `watchlist`; missing/blank defaults to `standard`.
- `account_type`: `owned`, `competitor`, `benchmark`, or `creator`; missing/blank remains unspecified.
- `business_group`, `market`, `owner`, and `tags` are descriptive text. Use semicolons inside tags, e.g. `news;video`.
- `active`: `true`/`false` or `1`/`0`; missing/blank defaults to true. Inactive accounts are excluded from reports and expected coverage.
- Missing grouping values form an unspecified (blank) group; no business classification is inferred.

### observations.csv

`date,account_id,platform,posts_published,reposts_gained,likes_gained,comments_gained`

Each row represents one account/platform/day. Dates use `YYYY-MM-DD`. All four metrics are **daily increments**, not cumulative snapshots: posts published that day, and reposts, likes, and comments gained that day. Interactions can be gained on older posts.

- Counts must be nonnegative integers when supplied.
- A blank cell, omitted metric column, or absent daily row means **unknown (`None`)**, never zero.
- An explicit `0` means confirmed no new activity.
- Legacy `posts` maps to `posts_published` when the new column is absent. If both columns exist, `posts_published` takes precedence, even when blank.
- Duplicate account/platform/day keys, invalid dates, counts, or metadata are rejected.
- Rows outside active accounts or selected platforms are excluded and counted. Counts and dates are still validated in those rows.

## Metrics and coverage

Each metric has its own observed/expected day count, coverage fraction (0–1), and `complete` / `partial` / `missing` status. Zero counts as observed. For group and overall totals, coverage counts account-platform-days; unknown entries are never filled with zero.

Base metrics sum known observations. A partial sum is explicitly marked partial; a completely unknown sum stays null/blank.

`engagement = reposts_gained + likes_gained + comments_gained`

A day has known engagement only when all three interaction metrics are known for that same day. A period/group engagement total is output only when every expected entry has all three components; otherwise it stays null, with its own coverage. This prevents incomplete interaction sums from appearing reliable.

`engagement_per_post = engagement / posts_published`

The ratio requires complete interaction and post coverage plus a positive post total. With zero or unknown posts, the ratio stays null (never infinity). Ratio coverage describes input availability, so it can be complete while the ratio is undefined due to zero posts. Period and group ratios divide aggregated totals, rather than averaging daily ratios. This is an activity ratio, not attribution of engagement to that day's newly published posts.

## Reports

| Output | Contents |
| --- | --- |
| `daily.csv` | Selected-day metrics and independent coverage for each active account/platform. |
| `monthly.csv` | Current and previous month-to-date metrics, independent coverage, and changes. |
| `priority.csv` | Month-to-date rows for `tracking_tier=priority`, including missing data. |
| `rankings.csv` | Platform-local rankings with selected metric and value. |
| `groups.csv` | Dynamic grouping dimension/value, platform totals, and coverage. |
| `summary.json` | Parameters, overall metrics/coverage, and excluded/out-of-window counts. |
| `report.json` | Complete structured report, including priority accounts and rankings. |
| `report.html` | Offline tables for all metrics, coverage, priority accounts, groups, and rankings. |

CSV unknown values are blank; JSON uses null; HTML uses a dash. Each metric's export columns include `_observed_days`, `_expected_days`, `_coverage`, and `_status`. Monthly columns use `current_` / `previous_` prefixes. Changes require complete coverage in both periods and defined values. The output schema now uses `posts_published`; legacy compatibility applies to input CSVs.

Comparison windows start at each month's first day. The previous window ends on the same day number, capped at that month's last day. March 31 therefore compares with February 1–28/29. Read the date windows before comparing totals. Future observations do not enter the selected period. Expected coverage includes every active account on every selected platform; an unobserved platform is unknown, not zero.

## Design

A single-file core, standard-library Python, local CSV inputs, and offline HTML/CSV/JSON outputs. No dependencies, crawlers, platform APIs, or automatic collection. Activity counts do not measure content quality or policy compliance.

## Validation

```bash
python3 -m unittest discover -s tests -v
git diff --check
```

Tests cover legacy input, zero versus unknown, independent coverage, conservative engagement totals, zero denominators, metadata/grouping, priority accounts, platform rankings, date windows, CLI options, and exports.
