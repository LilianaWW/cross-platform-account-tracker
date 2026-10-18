# 跨平台账号追踪工具

[English](./README.md) · 中文

多指标账号追踪：发文、转发、点赞、评论、总互动、篇均互动，以及平台内排行和重点账号报告。

```bash
python3 tracker.py --input examples --date 2026-09-05 --group-by business_group --rank-by engagement --output reports
```

需要 Python 3.9+，无额外依赖。打开 `reports/report.html` 查看结果。

- `observations.csv` 使用 `date,account_id,platform,posts_published,reposts_gained,likes_gained,comments_gained`。指标均为当天新增量，不是累计值。
- 空值、缺列、缺行表示未知；`0` 表示确认无新增。旧字段 `posts` 在新列不存在时映射为 `posts_published`；两列同时存在时以新列为准，包括空值。
- 每项指标独立计算 complete/partial/missing 覆盖率。基础指标合计已知值并标记覆盖情况；完全未知时不输出零。
- 总互动为转发、点赞、评论之和，仅在该统计范围内三项组成指标全部完整时输出。篇均互动还要求发文覆盖完整且合计大于零；否则为空。零分母下即使输入覆盖完整，篇均互动仍为空。
- `accounts.csv` 保留 `group`，支持 `business_group,tracking_tier,account_type,market,owner,tags,active`。仅 `account_id,account_name` 必填。
- `tracking_tier` 为 priority/standard/watchlist，默认 standard。`account_type` 为 owned/competitor/benchmark/creator，可留空。`active` 为 true/false 或 1/0，默认 true；停用账号不进入统计。
- `--group-by` 支持 group/business_group/tracking_tier/account_type/market，默认 group。
- `--rank-by` 支持 posts_published/engagement/likes_gained/comments_gained/reposts_gained，默认 posts_published。排名始终在各平台内部进行，仅要求所选指标的本月覆盖完整。

报告包含 daily.csv、monthly.csv、priority.csv、rankings.csv、groups.csv、summary.json、report.json 和 report.html。重点账号独立呈现。CSV 空白、JSON null 和 HTML 横线均不代表零。月度变化要求两期对应指标完整且可计算；月末比较窗口可能长短不同。

完整字段、覆盖率定义和报告说明见 [英文文档](./README.md)，模拟数据说明见 [examples](./examples/README.md)。

```bash
python3 -m unittest discover -s tests -v
git diff --check
```
