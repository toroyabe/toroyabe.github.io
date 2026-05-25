# StaffAny weekly report

A single-file Python script that pulls data from the StaffAny API and writes
a multi-sheet **Excel (.xlsx)** report for the upcoming week. The headline is
an **OT Capping Weekly Report** tuned for Singaporean full-time baristas
(standard week 9.5h × 5 days = **47.5h**, daily cap **9.5h**), but the caps
and contract filter are configurable.

Workbook sheets:

1. **Summary** — week, org, parameters, methodology note.
2. **OT Capping** — next week scheduled hours vs each staff's weekly cap,
   with red rows for `OVER` (excess weekly or any day > 9.5h) and yellow
   rows for `WARN` (≥90% of cap). Includes a per-day breakdown of any day
   exceeding the daily cap.
3. **Shifts** — scheduled hours and shift counts per staff for next week.
4. **Timesheets** — prior-week scheduled vs clocked hours.
5. **Sales** — prior-week target/actual sales by section.
6. **Leaves** — approved leaves and day-offs falling in next week.

## Requirements

- Python 3.9+ (uses `zoneinfo` from stdlib).
- `openpyxl` (`pip install openpyxl`).
- A StaffAny API bearer token (format `wks_<prefix>.<secret>`).

## Run

```bash
pip install openpyxl
export STAFFANY_TOKEN='wks_xxx.yyyy'
export STAFFANY_BASE_URL='https://api.staffany.com'    # adjust if different

python3 weekly_report.py \
    --tz Asia/Singapore \
    --contract-filter FULL_TIME \
    --output report.xlsx
```

Open `report.xlsx` in Excel / Google Sheets / Numbers.

## Useful flags

| Flag                 | Default                 | Notes                                                                 |
| -------------------- | ----------------------- | --------------------------------------------------------------------- |
| `--week-start`       | next Monday             | ISO date (YYYY-MM-DD) of the target Monday                            |
| `--ot-cap`           | `47.5`                  | Fallback weekly cap when `compensation.weeklyHours` is not set        |
| `--daily-cap`        | `9.5`                   | Days scheduled above this are listed in the OT section                |
| `--ot-warn-pct`      | `90`                    | % of weekly cap that triggers a WARN (still under cap)                |
| `--contract-filter`  | _(none)_                | Repeatable; e.g. `--contract-filter FULL_TIME`                        |
| `--section-id`       | _(none)_                | Repeatable; restricts shifts/timesheets/sales/dayOffs/leaves          |
| `--tz`               | `Asia/Singapore`        | Used for week boundaries and display timestamps                       |
| `--debug`            | off                     | Print each request URL and the top-level response keys to stderr      |

## Cron (manual weekly schedule)

A typical Singapore weekday morning run that emails the report to a manager:

```cron
# 09:00 every Friday SGT — generate next-week report
0 9 * * 5  cd ~/staffany && STAFFANY_TOKEN=$(cat .token) \
    python3 weekly_report.py --contract-filter FULL_TIME \
    --output ~/staffany-reports/$(date +\%Y-\%m-\%d).xlsx
```

## Notes

- Weekly cap precedence: per-staff `compensation.weeklyHours` → `--ot-cap`.
- Excess in the OT section is `max(0, scheduled - cap)`. Daily flags are listed
  separately so a person hitting OT through a single long day still gets caught
  even if their weekly total is under cap.
- Projected OT cost is shown only when an `overtimeRate` is set on the
  staff's compensation row.
- Leaves come from `/workspace/v2/leaves/records/search`; if the org hasn't
  enabled that endpoint the script falls back gracefully to the `/dayOffs` data.
