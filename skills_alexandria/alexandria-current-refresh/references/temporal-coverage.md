# Temporal coverage before closure

Use when a handoff or CURRENT asserts daily/weekly/monthly completeness.

```json
{"tool":"alexandria_temporal_coverage","arguments":{"project":"heterarchy-alexandria","start_date":"2026-09-21","end_date":"2026-09-30","families":["agent_platform"],"timezone":"Asia/Seoul","not_expected":[]}}
```

Bounds: at most 366 days, 50 families and 18,300 explicit exclusions. Supply the
expected families from the task; an empty list reports observed families and
cannot prove a period complete when no family exists.

- COMPLETE proves durable packet presence, not contemporaneous observation.
- BACKFILL retains the target date separately from the later ingestion date.
- MISSING is an expected source gap, never NO_CHANGE.
- NOT_EXPECTED reflects explicit caller calendar policy, not an automatically
  fetched exchange holiday feed. Supply known `(family, date)` exclusions as
  `{"family":"stock_close","date":"2026-09-25"}` only when supported by the
  task's calendar evidence; this example does not assert a real exchange holiday.
- Today/future remain OPEN even if packets already exist or an exclusion was
  supplied. They cannot be terminalized.

Inspect `source_evidence` for actual `source_created_at`/`ingestion_date`;
unknown time is null. Preserve late backfills and earlier gaps in the summary.
Use `closable_daily`, `open_daily`, `missing_expected_sources`,
`late_backfills`, `weekly_close_due` and `monthly_close_due`. Boundary policy is
explicit: ISO weeks run Monday–Sunday; ordinal labels group month days in
sevens; weekly/monthly closeability needs the entire ended period in the range.
Unparseable packets are reported separately and do not prove a source was never
created. The tool performs deterministic coverage analysis, not semantic
judgment of packet contents or permission to close a period.
