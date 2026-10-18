# Synthetic fixtures

**All accounts, metadata, and metric values are simulated.** They are not real account performance. The project only reads local files: it never scrapes websites or calls platform APIs.

The fixture covers August 1–5 and September 1–5, 2026, for four accounts on three platforms. IDs with leading zeros remain strings.

- All metrics are daily increments, not cumulative totals: `posts_published`, `reposts_gained`, `likes_gained`, `comments_gained`.
- Blank cells and absent metric columns/rows mean unknown. Explicit `0` means confirmed no new activity.
- `001` includes zero publishing activity with known interactions, and a blank interaction component on one date.
- `003` lacks two September `xiaohongshu` rows, including September 5.
- `004` lacks August `douyin` rows.
- A September 6 row demonstrates the report cutoff. One out-of-roster account and one extra platform demonstrate scope filtering.
- Metadata includes business groups, priority/standard/watchlist tiers, account types, markets, owners, tags, and active flags. All four sample accounts are active.

Old observations containing `posts` instead of `posts_published` still load; other missing metrics remain unknown. If both columns exist, the new column wins even when blank. Old rosters still load, defaulting to `tracking_tier=standard` and `active=true`; other new fields remain unspecified.

```bash
python3 tracker.py --input examples --date 2026-09-05 --group-by business_group --rank-by engagement --output reports
```

`--group-by` supports `group`, `business_group`, `tracking_tier`, `account_type`, `market`. `--rank-by` supports `posts_published`, `engagement`, `likes_gained`, `comments_gained`, `reposts_gained`. Rankings are always platform-local and require complete coverage of the chosen metric. Each metric has independent coverage. Incomplete interaction components suppress the derived engagement total and ratio; zero posts suppress the ratio. Priority accounts appear in their own report section and CSV/JSON data.
