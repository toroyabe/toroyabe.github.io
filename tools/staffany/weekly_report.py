#!/usr/bin/env python3
"""Generate a weekly StaffAny Excel (.xlsx) report.

Sections:
  - OT Capping (headline) -- next week's scheduled hours vs each staff's cap.
  - Shifts per staff      -- next week's scheduled hours and shift count.
  - Timesheet actuals     -- prior week scheduled vs clocked.
  - Sales totals          -- prior week target / actual sales by section.
  - Leaves / day-offs     -- approved leaves and day-offs falling in next week.

Auth:
  Bearer token in STAFFANY_TOKEN (or --token). Token format: wks_<prefix>.<secret>.

Usage:
  STAFFANY_TOKEN=wks_... python3 weekly_report.py \\
      --base-url https://api.staffany.com \\
      --tz Asia/Singapore \\
      --output report.xlsx
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    sys.exit("This script requires openpyxl. Install with: pip install openpyxl")

DEFAULT_BASE_URL = "https://api.staffany.com"
# Singaporean full-time barista standard: 9.5h x 5 days = 47.5h / week.
DEFAULT_OT_CAP_HOURS = 47.5
DEFAULT_DAILY_CAP_HOURS = 9.5


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default=os.environ.get("STAFFANY_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--token", default=os.environ.get("STAFFANY_TOKEN"))
    p.add_argument("--tz", default=os.environ.get("STAFFANY_TZ", "Asia/Singapore"))
    p.add_argument("--week-start", help="ISO date (YYYY-MM-DD) of the target Monday; default = next Monday")
    p.add_argument("--ot-cap", type=float, default=DEFAULT_OT_CAP_HOURS,
                   help=f"Weekly OT cap in hours; falls back to per-staff compensation.weeklyHours when present "
                        f"(default {DEFAULT_OT_CAP_HOURS} = 9.5h x 5 days, SG full-time barista standard)")
    p.add_argument("--daily-cap", type=float, default=DEFAULT_DAILY_CAP_HOURS,
                   help=f"Daily cap; any scheduled day above this is flagged (default {DEFAULT_DAILY_CAP_HOURS})")
    p.add_argument("--ot-warn-pct", type=float, default=90.0, help="Warn at this %% of weekly cap (default 90)")
    p.add_argument("--contract-filter", action="append", default=None,
                   help="Restrict OT section to staff with this contractType (repeatable, e.g. FULL_TIME). "
                        "Default: include everyone.")
    p.add_argument("--section-id", action="append", dest="section_ids",
                   help="Restrict to one or more section UUIDs (repeatable)")
    p.add_argument("--output", default="weekly-report.xlsx")
    p.add_argument("--debug", action="store_true", help="Print raw API payloads to stderr")
    return p.parse_args()


# ---------- HTTP ----------

def make_client(base_url, token, debug=False):
    if not token:
        sys.exit("STAFFANY_TOKEN is not set (or pass --token).")

    def request(method, path, *, params=None, body=None):
        url = base_url.rstrip("/") + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if debug:
            print(f"[{method}] {url}", file=sys.stderr)
            if body is not None:
                print("  body:", json.dumps(body), file=sys.stderr)
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            sys.exit(f"HTTP {e.code} {method} {path}: {err_body}")
        except urllib.error.URLError as e:
            sys.exit(f"Network error calling {method} {path}: {e}")
        if debug:
            print("  -> keys:", list(payload.get("data", {}).keys()) if isinstance(payload.get("data"), dict) else "array", file=sys.stderr)
        return payload

    return request


# ---------- Time helpers ----------

def week_bounds(tz, week_start_arg):
    today = datetime.now(tz).date()
    if week_start_arg:
        start = datetime.fromisoformat(week_start_arg).date()
    else:
        # next Monday (always advances; if today is Monday, take +7)
        days_ahead = (7 - today.weekday()) or 7
        start = today + timedelta(days=days_ahead)
    next_from = datetime.combine(start, datetime.min.time(), tz)
    next_to = next_from + timedelta(days=7)
    prev_from = next_from - timedelta(days=7)
    prev_to = next_from
    return next_from, next_to, prev_from, prev_to


def ms(dt):
    return int(dt.timestamp() * 1000)


def iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z" if dt.tzinfo is None else dt.isoformat()


def parse_dt(s, tz):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(tz)


# ---------- Collectors ----------

def collect_staff(client):
    rows = client("GET", "/workspace/v1/staff")["data"]
    out = {}
    for r in rows:
        u = r["userDetails"]
        ou = r["orgUserDetails"]
        first = ou.get("orgUserFirstName") or u.get("firstName") or ""
        last = ou.get("orgUserLastName") or u.get("lastName") or ""
        name = (first + " " + last).strip() or u.get("email") or u["id"]
        out[u["id"]] = {
            "name": name,
            "employeeId": ou.get("employeeId"),
            "status": ou.get("status"),
            "contractType": ou.get("contractType"),
            "sectionIds": ou.get("sectionIds") or [],
            "resignDate": ou.get("resignDate"),
        }
    return out


def collect_sections(client):
    payload = client("GET", "/workspace/v1/sections")
    out = {}
    for s in payload.get("data", []):
        # Tolerant of shape variations
        sid = s.get("id") or s.get("sectionId")
        name = s.get("name") or sid
        if sid:
            out[sid] = name
    return out


def collect_shifts(client, frm, to, section_ids):
    body = {"range": {"from": iso_z(frm), "to": iso_z(to)}, "includeUnassigned": True}
    if section_ids:
        body["sectionIds"] = section_ids
    return client("POST", "/workspace/v1/shifts", body=body)["data"]


def collect_timesheets(client, frm, to, section_ids):
    body = {
        "range": {"from": ms(frm), "to": ms(to)},
        "includes": ["workHours", "shiftRecords", "clockAttempts"],
    }
    if section_ids:
        body["sectionIds"] = section_ids
    return client("POST", "/workspace/v1/timesheets", body=body)["data"]


def collect_sales(client, frm, to, section_ids):
    # /sales uses YYYY-MM-DD inclusive end
    params = {"start": frm.date().isoformat(), "end": (to.date() - timedelta(days=1)).isoformat()}
    if section_ids:
        params["sectionIds"] = list(section_ids)
    return client("GET", "/workspace/v1/sales", params=params).get("data", [])


def collect_day_offs(client, frm, to, section_ids):
    body = {"range": {"from": ms(frm), "to": ms(to)}}
    if section_ids:
        body["sectionIds"] = section_ids
    return client("POST", "/workspace/v1/dayOffs", body=body)["data"].get("dayOffs", [])


def collect_leaves(client, frm, to, section_ids):
    body = {"dateRange": {"from": ms(frm), "to": ms(to)}}
    if section_ids:
        body["filters"] = {"sectionIds": section_ids}
    try:
        return client("POST", "/workspace/v2/leaves/records/search", body=body)["data"].get("items", [])
    except SystemExit:
        return []


def collect_comp(client, frm, to):
    body = {"range": {"from": iso_z(frm), "to": iso_z(to)}, "includes": ["compensations"]}
    return client("POST", "/workspace/v1/compensation", body=body)["data"].get("compensations", [])


def collect_me(client):
    return client("GET", "/workspace/v1/me").get("data", {})


# ---------- Analysis ----------

def slot_minutes(slot, shift):
    start = datetime.fromisoformat(slot["timeStart"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(slot["timeEnd"].replace("Z", "+00:00"))
    gross = (end - start).total_seconds() / 60.0
    brk = slot.get("breakOverride")
    if brk is None:
        brk = shift.get("breakTime") or 0
    return max(0.0, gross - float(brk))


def per_user_scheduled(shift_payload):
    shifts_by_id = {s["id"]: s for s in shift_payload.get("shifts", [])}
    totals = defaultdict(lambda: {"minutes": 0.0, "count": 0, "by_day": defaultdict(float)})
    unassigned = {"minutes": 0.0, "count": 0}
    for slot in shift_payload.get("shiftSlots", []):
        parent = shifts_by_id.get(slot["shiftId"], {})
        minutes = slot_minutes(slot, parent)
        uid = slot.get("userId")
        if not uid:
            unassigned["minutes"] += minutes
            unassigned["count"] += 1
            continue
        totals[uid]["minutes"] += minutes
        totals[uid]["count"] += 1
        day = slot["timeStart"][:10]
        totals[uid]["by_day"][day] += minutes
    return totals, unassigned


def latest_compensation_per_user(comps):
    """Take the most recent compensation effective in the window per user."""
    by_user = {}
    for c in comps:
        uid = c["userId"]
        eff = c.get("effectiveDate") or c.get("createdAt") or ""
        if uid not in by_user or eff > by_user[uid].get("effectiveDate") or "":
            by_user[uid] = c
    return by_user


def per_user_actuals(timesheets):
    """Sum workHours.startTime->endTime (or use scheduled link) per user for prior week."""
    totals = defaultdict(lambda: {"minutes": 0.0, "shifts": 0, "missing_clock": 0})
    # workHours have userId and startTime; pair with the matching shiftRecord for duration.
    records = {r["id"]: r for r in timesheets.get("shiftRecords", [])}
    for wh in timesheets.get("workHours", []):
        uid = wh.get("userId")
        if not uid:
            continue
        rec = records.get(wh.get("workableId")) or wh.get("ShiftRecord") or {}
        # Try multiple field names tolerantly.
        s = rec.get("clockedTimeStart") or rec.get("startTime") or rec.get("timeStart")
        e = rec.get("clockedTimeEnd") or rec.get("endTime") or rec.get("timeEnd")
        brk = rec.get("breakDuration") or rec.get("breakTime") or 0
        minutes = 0.0
        if s and e:
            try:
                ds = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
                de = datetime.fromisoformat(str(e).replace("Z", "+00:00"))
                minutes = max(0.0, (de - ds).total_seconds() / 60.0 - float(brk or 0))
            except ValueError:
                minutes = 0.0
        else:
            totals[uid]["missing_clock"] += 1
        totals[uid]["minutes"] += minutes
        totals[uid]["shifts"] += 1
    return totals


# ---------- Excel rendering ----------

HEADER_FILL = PatternFill("solid", fgColor="F2F2F2")
OVER_FILL = PatternFill("solid", fgColor="FDE2E1")
WARN_FILL = PatternFill("solid", fgColor="FFF4CE")
TITLE_FONT = Font(bold=True, size=14)
HEADER_FONT = Font(bold=True)
THIN_BORDER = Border(bottom=Side(style="thin", color="DDDDDD"))


def _autosize(ws, max_width=60):
    for col_cells in ws.columns:
        col = get_column_letter(col_cells[0].column)
        longest = 0
        for c in col_cells:
            v = c.value
            if v is None:
                continue
            s = str(v)
            longest = max(longest, max((len(line) for line in s.split("\n")), default=0))
        ws.column_dimensions[col].width = min(max(longest + 2, 10), max_width)


def _write_title(ws, title, subtitle=None):
    ws["A1"] = title
    ws["A1"].font = TITLE_FONT
    if subtitle:
        ws["A2"] = subtitle
        ws["A2"].font = Font(italic=True, color="555555")
        ws["A2"].alignment = Alignment(wrap_text=True)
    return 4 if subtitle else 3  # next free row (1-indexed)


def _write_header(ws, row, headers):
    for col_idx, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=col_idx, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.border = THIN_BORDER
        c.alignment = Alignment(horizontal="left")
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def write_ot_sheet(ws, staff, scheduled, comps_by_user, default_cap, daily_cap, warn_pct, contract_filter):
    rows = []
    skipped_by_filter = 0
    for uid, info in scheduled.items():
        info_staff = staff.get(uid, {})
        contract = info_staff.get("contractType")
        if contract_filter and contract not in contract_filter:
            skipped_by_filter += 1
            continue
        person = info_staff.get("name", uid)
        cap = (comps_by_user.get(uid) or {}).get("weeklyHours") or default_cap
        ot_rate = (comps_by_user.get(uid) or {}).get("overtimeRate")
        sched_hours = info["minutes"] / 60.0
        excess_weekly = max(0.0, sched_hours - cap)
        pct = (sched_hours / cap * 100.0) if cap else 0.0
        daily_flags = []
        for day, day_min in sorted(info["by_day"].items()):
            day_h = day_min / 60.0
            if day_h > daily_cap + 1e-6:
                daily_flags.append(f"{day} ({day_h:.2f}h, +{day_h - daily_cap:.2f})")
        if excess_weekly > 0 or daily_flags:
            status = "OVER"
        elif pct >= warn_pct:
            status = "WARN"
        else:
            status = "OK"
        projected_ot_cost = excess_weekly * ot_rate if (excess_weekly > 0 and ot_rate) else None
        rows.append((person, contract or "", cap, sched_hours, excess_weekly,
                     pct / 100.0, "; ".join(daily_flags), status, projected_ot_cost))
    rows.sort(key=lambda r: (r[7] != "OVER", r[7] != "WARN", -r[4], -r[3]))

    subtitle = (f"Singaporean full-time barista standard: 9.5h × 5 days = 47.5h/week. "
                f"Weekly cap uses compensation.weeklyHours when present, else {default_cap:.1f}h. "
                f"Daily cap: {daily_cap:.1f}h. Warn at {warn_pct:.0f}% of cap.")
    if contract_filter:
        subtitle += f"  |  Filter: contractType ∈ {{{', '.join(contract_filter)}}} (excluded {skipped_by_filter})."
    row = _write_title(ws, "OT Capping Weekly Report — next week", subtitle)
    headers = ["Staff", "Contract", "Weekly cap (h)", "Scheduled (h)",
               "Excess (h)", "% of cap", f"Days > {daily_cap:.1f}h", "Status", "Projected OT cost"]
    _write_header(ws, row, headers)

    if not rows:
        ws.cell(row=row + 1, column=1, value="No matching staff with shifts for next week.").font = Font(italic=True, color="777777")
    for i, (name, contract, cap, sched, excess, pct_frac, day_flags, status, proj) in enumerate(rows, start=row + 1):
        fill = OVER_FILL if status == "OVER" else (WARN_FILL if status == "WARN" else None)
        values = [name, contract, cap, sched, excess, pct_frac, day_flags, status, proj]
        for col_idx, v in enumerate(values, start=1):
            c = ws.cell(row=i, column=col_idx, value=v)
            if fill:
                c.fill = fill
        ws.cell(row=i, column=3).number_format = "0.0"
        ws.cell(row=i, column=4).number_format = "0.00"
        ws.cell(row=i, column=5).number_format = "0.00;[Red]+0.00"
        ws.cell(row=i, column=6).number_format = "0%"
        ws.cell(row=i, column=9).number_format = '"$"#,##0.00;[Red]"$"#,##0.00'
        ws.cell(row=i, column=8).font = Font(bold=True,
                                             color={"OVER": "B3261E", "WARN": "8A6D00", "OK": "137333"}[status])
    _autosize(ws)


def write_shifts_sheet(ws, staff, scheduled, unassigned):
    rows = sorted(
        ((staff.get(uid, {}).get("name", uid), info["minutes"] / 60.0, info["count"], info["by_day"])
         for uid, info in scheduled.items()),
        key=lambda r: -r[1],
    )
    subtitle = "Scheduled hours and shift counts for next week."
    if unassigned["count"]:
        subtitle += (f"  Plus {unassigned['count']} unassigned slot(s) totalling "
                     f"{unassigned['minutes'] / 60.0:.2f}h (not in table).")
    row = _write_title(ws, "Shifts per staff — next week", subtitle)
    _write_header(ws, row, ["Staff", "Hours", "# Shifts", "By day"])
    if not rows:
        ws.cell(row=row + 1, column=1, value="No assigned shifts.").font = Font(italic=True, color="777777")
    for i, (name, hours, count, by_day) in enumerate(rows, start=row + 1):
        by_day_str = ", ".join(f"{d}: {m / 60.0:.2f}h" for d, m in sorted(by_day.items()))
        ws.cell(row=i, column=1, value=name)
        c = ws.cell(row=i, column=2, value=hours); c.number_format = "0.00"
        ws.cell(row=i, column=3, value=count)
        ws.cell(row=i, column=4, value=by_day_str).alignment = Alignment(wrap_text=True)
    _autosize(ws)


def write_timesheets_sheet(ws, staff, actuals, scheduled_prev):
    keys = set(actuals) | set(scheduled_prev)
    rows = []
    for uid in keys:
        name = staff.get(uid, {}).get("name", uid)
        sched = scheduled_prev.get(uid, {}).get("minutes", 0.0) / 60.0
        act = actuals.get(uid, {}).get("minutes", 0.0) / 60.0
        missing = actuals.get(uid, {}).get("missing_clock", 0)
        rows.append((name, sched, act, act - sched, missing))
    rows.sort(key=lambda r: -abs(r[3]))

    row = _write_title(ws, "Timesheet actuals — prior week", "Scheduled vs clocked hours for the previous Mon–Sun.")
    _write_header(ws, row, ["Staff", "Scheduled (h)", "Clocked (h)", "Delta (h)", "Missing clock"])
    if not rows:
        ws.cell(row=row + 1, column=1, value="No timesheet data for prior week.").font = Font(italic=True, color="777777")
    for i, (name, sched, act, delta, missing) in enumerate(rows, start=row + 1):
        ws.cell(row=i, column=1, value=name)
        ws.cell(row=i, column=2, value=sched).number_format = "0.00"
        ws.cell(row=i, column=3, value=act).number_format = "0.00"
        c = ws.cell(row=i, column=4, value=delta); c.number_format = "0.00;[Red]-0.00"
        ws.cell(row=i, column=5, value=missing or None)
    _autosize(ws)


def write_sales_sheet(ws, sales, sections):
    rows = []
    grand_target = 0.0
    grand_actual = 0.0
    for entry in sales:
        sd = entry.get("sectionDetails", {})
        det = entry.get("salesDetails", {})
        name = sd.get("name") or sections.get(sd.get("id"), sd.get("id"))
        totals = det.get("totals", {}) or {}
        target = totals.get("totalTargetSales") or 0
        by_date = det.get("byDate", {}) or {}
        actuals_by_date = by_date.get("actualSales") if isinstance(by_date.get("actualSales"), dict) else {}
        actual = sum(actuals_by_date.values()) if actuals_by_date else 0
        spl = totals.get("estimatedSalesPerLaborHour") or 0
        rows.append((name, target, actual, spl))
        grand_target += target or 0
        grand_actual += actual or 0
    rows.sort(key=lambda r: -r[1])

    row = _write_title(ws, "Sales totals — prior week", "Per-section target vs actual sales.")
    _write_header(ws, row, ["Section", "Target", "Actual", "Est. $/labor h"])
    if not rows:
        ws.cell(row=row + 1, column=1, value="No sales data.").font = Font(italic=True, color="777777")
        _autosize(ws)
        return
    money_fmt = '#,##0.00'
    for i, (name, target, actual, spl) in enumerate(rows, start=row + 1):
        ws.cell(row=i, column=1, value=name)
        ws.cell(row=i, column=2, value=target).number_format = money_fmt
        ws.cell(row=i, column=3, value=actual).number_format = money_fmt
        ws.cell(row=i, column=4, value=spl).number_format = money_fmt
    total_row = row + 1 + len(rows)
    ws.cell(row=total_row, column=1, value="Total").font = HEADER_FONT
    c = ws.cell(row=total_row, column=2, value=grand_target); c.font = HEADER_FONT; c.number_format = money_fmt
    c = ws.cell(row=total_row, column=3, value=grand_actual); c.font = HEADER_FONT; c.number_format = money_fmt
    _autosize(ws)


def write_leaves_sheet(ws, staff, day_offs, leaves):
    rows = []
    for d in day_offs:
        name = staff.get(d.get("userId"), {}).get("name", d.get("userId"))
        rows.append((d.get("date", ""), name, d.get("dayType", "-"),
                     d.get("hours") or "", d.get("reason") or "", "day-off"))
    for lv in leaves:
        uid = lv.get("staffId") or lv.get("userId")
        name = staff.get(uid, {}).get("name", uid)
        date_s = lv.get("startDate") or lv.get("date") or ""
        end_s = lv.get("endDate") or ""
        span = f"{date_s} → {end_s}" if end_s and end_s != date_s else date_s
        rows.append((span, name, lv.get("leaveTypeName") or lv.get("typeName") or "leave",
                     lv.get("hours") or lv.get("totalHours") or "",
                     lv.get("note") or lv.get("reason") or "", "leave"))
    rows.sort()

    row = _write_title(ws, "Leaves & day-offs — next week", "Approved leaves and day-offs falling in next week.")
    _write_header(ws, row, ["Date", "Staff", "Type", "Hours", "Reason", "Source"])
    if not rows:
        ws.cell(row=row + 1, column=1, value="No leaves or day-offs scheduled.").font = Font(italic=True, color="777777")
    for i, vals in enumerate(rows, start=row + 1):
        for col_idx, v in enumerate(vals, start=1):
            ws.cell(row=i, column=col_idx, value=v)
    _autosize(ws)


def write_summary_sheet(ws, meta):
    ws["A1"] = meta["title"]; ws["A1"].font = TITLE_FONT
    items = [
        ("Week", meta["week_label"]),
        ("Organisation", meta["org"]),
        ("Generated", meta["generated_at"]),
        ("Weekly cap (fallback)", f"{meta['default_cap']:.1f} h"),
        ("Daily cap", f"{meta['daily_cap']:.1f} h"),
        ("Warn threshold", f"{meta['warn_pct']:.0f}% of cap"),
        ("Contract filter", meta.get("contract_filter") or "(all)"),
    ]
    for i, (k, v) in enumerate(items, start=3):
        ws.cell(row=i, column=1, value=k).font = HEADER_FONT
        ws.cell(row=i, column=2, value=v)
    ws.cell(row=3 + len(items) + 1, column=1,
            value="Standard for SG full-time baristas: 9.5h × 5 days = 47.5h/week. "
                  "Entries with Total Hours Worked > 47.5 are flagged as excess overtime "
                  "(red rows on the OT Capping sheet). Days scheduled above the daily cap "
                  "are listed in the 'Days > 9.5h' column.").alignment = Alignment(wrap_text=True)
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 60


def build_workbook(meta, staff, scheduled_next, unassigned_next, comps_by_user,
                   actuals_prev, scheduled_prev, sales_prev, sections,
                   day_offs_next, leaves_next, args):
    wb = Workbook()
    wb.remove(wb.active)
    write_summary_sheet(wb.create_sheet("Summary"), meta)
    write_ot_sheet(wb.create_sheet("OT Capping"), staff, scheduled_next, comps_by_user,
                   args.ot_cap, args.daily_cap, args.ot_warn_pct, args.contract_filter)
    write_shifts_sheet(wb.create_sheet("Shifts"), staff, scheduled_next, unassigned_next)
    write_timesheets_sheet(wb.create_sheet("Timesheets"), staff, actuals_prev, scheduled_prev)
    write_sales_sheet(wb.create_sheet("Sales"), sales_prev, sections)
    write_leaves_sheet(wb.create_sheet("Leaves"), staff, day_offs_next, leaves_next)
    return wb


# ---------- Main ----------

def main():
    args = parse_args()
    tz = ZoneInfo(args.tz)
    next_from, next_to, prev_from, prev_to = week_bounds(tz, args.week_start)

    client = make_client(args.base_url, args.token, debug=args.debug)
    me = collect_me(client)
    org_name = (me.get("organisation") or {}).get("name") if isinstance(me.get("organisation"), dict) else me.get("organisation") or ""

    staff = collect_staff(client)
    try:
        sections = collect_sections(client)
    except SystemExit:
        sections = {}

    shifts_next = collect_shifts(client, next_from, next_to, args.section_ids)
    shifts_prev = collect_shifts(client, prev_from, prev_to, args.section_ids)
    ts_prev = collect_timesheets(client, prev_from, prev_to, args.section_ids)
    sales_prev = collect_sales(client, prev_from, prev_to, args.section_ids)
    day_offs_next = collect_day_offs(client, next_from, next_to, args.section_ids)
    leaves_next = collect_leaves(client, next_from, next_to, args.section_ids)
    comps = collect_comp(client, next_from, next_to)

    scheduled_next, unassigned_next = per_user_scheduled(shifts_next)
    scheduled_prev, _ = per_user_scheduled(shifts_prev)
    actuals_prev = per_user_actuals(ts_prev)
    comps_by_user = latest_compensation_per_user(comps)

    week_label = f"{next_from.date().isoformat()} – {(next_to.date() - timedelta(days=1)).isoformat()}"
    meta = {
        "title": f"StaffAny Weekly Report — {week_label}",
        "week_label": week_label,
        "generated_at": datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z"),
        "org": org_name or "(unknown)",
        "default_cap": args.ot_cap,
        "daily_cap": args.daily_cap,
        "warn_pct": args.ot_warn_pct,
        "contract_filter": ", ".join(args.contract_filter) if args.contract_filter else None,
    }

    wb = build_workbook(meta, staff, scheduled_next, unassigned_next, comps_by_user,
                        actuals_prev, scheduled_prev, sales_prev, sections,
                        day_offs_next, leaves_next, args)
    wb.save(args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
