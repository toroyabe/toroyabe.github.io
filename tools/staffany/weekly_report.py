#!/usr/bin/env python3
"""Generate a weekly StaffAny HTML report.

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
      --output report.html
"""

import argparse
import html as html_mod
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
    p.add_argument("--output", default="weekly-report.html")
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


# ---------- Rendering ----------

def fmt_hours(minutes):
    return f"{minutes / 60.0:.2f}"


def esc(s):
    return html_mod.escape("" if s is None else str(s))


def render_ot_section(staff, scheduled, comps_by_user, default_cap, daily_cap, warn_pct, contract_filter):
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
        # Per-day excess: list days where scheduled hours exceed the daily cap.
        daily_flags = []
        for day, day_min in sorted(info["by_day"].items()):
            day_h = day_min / 60.0
            if day_h > daily_cap + 1e-6:
                daily_flags.append(f"{day} ({day_h:.2f}h, +{day_h - daily_cap:.2f})")
        if excess_weekly > 0 or daily_flags:
            status = "OVER"
            css = "row-over"
        elif pct >= warn_pct:
            status = "WARN"
            css = "row-warn"
        else:
            status = "OK"
            css = ""
        projected_ot_cost = f"${excess_weekly * (ot_rate or 0):.2f}" if (excess_weekly > 0 and ot_rate) else "-"
        rows.append((person, contract, cap, sched_hours, excess_weekly, pct, daily_flags, status, projected_ot_cost, css))
    rows.sort(key=lambda r: (r[7] != "OVER", r[7] != "WARN", -r[4], -r[3]))

    body = "".join(
        f'<tr class="{css}">'
        f"<td>{esc(name)}</td>"
        f"<td>{esc(contract or '-')}</td>"
        f"<td class='num'>{cap:.1f}</td>"
        f"<td class='num'>{sched:.2f}</td>"
        f"<td class='num'>{('+' + format(excess, '.2f')) if excess > 0 else '0.00'}</td>"
        f"<td class='num'>{pct:.0f}%</td>"
        f"<td class='muted'>{esc('; '.join(daily_flags)) or '-'}</td>"
        f"<td><span class='badge {status.lower()}'>{status}</span></td>"
        f"<td class='num'>{esc(proj_ot)}</td>"
        f"</tr>"
        for (name, contract, cap, sched, excess, pct, daily_flags, status, proj_ot, css) in rows
    ) or "<tr><td colspan='9' class='muted'>No matching staff with shifts for next week.</td></tr>"
    filter_note = ""
    if contract_filter:
        filter_note = (f"<p class='muted'>Filter: contractType &isin; {{{esc(', '.join(contract_filter))}}}. "
                       f"Excluded {skipped_by_filter} other staff with shifts.</p>")
    return f"""
<section>
  <h2>OT Capping Weekly Report &mdash; next week</h2>
  <p class='muted'>SG full-time barista standard: <strong>9.5h &times; 5 days = 47.5h/week</strong>.
     Weekly cap uses each staff's <code>compensation.weeklyHours</code> when present, otherwise {default_cap:.1f}h.
     Daily cap {daily_cap:.1f}h.</p>
  {filter_note}
  <table>
    <thead><tr>
      <th>Staff</th><th>Contract</th><th>Weekly cap (h)</th><th>Scheduled (h)</th>
      <th>Excess (h)</th><th>% of cap</th><th>Days &gt; {daily_cap:.1f}h</th>
      <th>Status</th><th>Projected OT cost</th>
    </tr></thead>
    <tbody>{body}</tbody>
  </table>
</section>"""


def render_shifts_section(staff, scheduled, unassigned):
    rows = sorted(
        ((staff.get(uid, {}).get("name", uid), info["minutes"], info["count"], info["by_day"])
         for uid, info in scheduled.items()),
        key=lambda r: -r[1],
    )
    body = "".join(
        f"<tr><td>{esc(name)}</td><td class='num'>{fmt_hours(mins)}</td><td class='num'>{count}</td>"
        f"<td class='muted'>{esc(', '.join(f'{d}: {fmt_hours(m)}h' for d, m in sorted(by_day.items())))}</td></tr>"
        for (name, mins, count, by_day) in rows
    ) or "<tr><td colspan='4' class='muted'>No assigned shifts.</td></tr>"
    extra = ""
    if unassigned["count"]:
        extra = (f"<p class='muted'>Plus <strong>{unassigned['count']}</strong> unassigned slot(s) totalling "
                 f"<strong>{fmt_hours(unassigned['minutes'])} h</strong>.</p>")
    return f"""
<section>
  <h2>Shifts per staff &mdash; next week</h2>
  <table>
    <thead><tr><th>Staff</th><th>Hours</th><th># Shifts</th><th>By day</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
  {extra}
</section>"""


def render_timesheets_section(staff, actuals, scheduled_prev):
    keys = set(actuals) | set(scheduled_prev)
    rows = []
    for uid in keys:
        name = staff.get(uid, {}).get("name", uid)
        sched = scheduled_prev.get(uid, {}).get("minutes", 0.0) / 60.0
        act = actuals.get(uid, {}).get("minutes", 0.0) / 60.0
        delta = act - sched
        missing = actuals.get(uid, {}).get("missing_clock", 0)
        rows.append((name, sched, act, delta, missing))
    rows.sort(key=lambda r: -abs(r[3]))
    body = "".join(
        f"<tr><td>{esc(n)}</td>"
        f"<td class='num'>{s:.2f}</td>"
        f"<td class='num'>{a:.2f}</td>"
        f"<td class='num'>{d:+.2f}</td>"
        f"<td class='num'>{m or ''}</td></tr>"
        for (n, s, a, d, m) in rows
    ) or "<tr><td colspan='5' class='muted'>No timesheet data for prior week.</td></tr>"
    return f"""
<section>
  <h2>Timesheet actuals &mdash; prior week</h2>
  <table>
    <thead><tr><th>Staff</th><th>Scheduled (h)</th><th>Clocked (h)</th><th>Delta (h)</th><th>Missing clock</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
</section>"""


def render_sales_section(sales, sections):
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
        actual = sum((by_date.get("actualSales") or {}).values()) if isinstance(by_date.get("actualSales"), dict) else 0
        spl = totals.get("estimatedSalesPerLaborHour")
        rows.append((name, target, actual, spl))
        grand_target += target or 0
        grand_actual += actual or 0
    body = "".join(
        f"<tr><td>{esc(n)}</td><td class='num'>{t:,.2f}</td><td class='num'>{a:,.2f}</td>"
        f"<td class='num'>{(spl or 0):,.2f}</td></tr>"
        for (n, t, a, spl) in sorted(rows, key=lambda r: -r[1])
    ) or "<tr><td colspan='4' class='muted'>No sales data.</td></tr>"
    footer = (f"<tfoot><tr><th>Total</th><th class='num'>{grand_target:,.2f}</th>"
              f"<th class='num'>{grand_actual:,.2f}</th><th></th></tr></tfoot>") if rows else ""
    return f"""
<section>
  <h2>Sales totals &mdash; prior week</h2>
  <table>
    <thead><tr><th>Section</th><th>Target</th><th>Actual</th><th>Est. $/labor h</th></tr></thead>
    <tbody>{body}</tbody>
    {footer}
  </table>
</section>"""


def render_leaves_section(staff, day_offs, leaves):
    rows = []
    for d in day_offs:
        name = staff.get(d.get("userId"), {}).get("name", d.get("userId"))
        rows.append((d.get("date", ""), name, d.get("dayType", "-"), d.get("hours") or "-", d.get("reason") or "-", "day-off"))
    for lv in leaves:
        uid = lv.get("staffId") or lv.get("userId")
        name = staff.get(uid, {}).get("name", uid)
        date_s = lv.get("startDate") or lv.get("date") or ""
        end_s = lv.get("endDate") or ""
        span = f"{date_s} → {end_s}" if end_s and end_s != date_s else date_s
        rows.append((span, name, lv.get("leaveTypeName") or lv.get("typeName") or "leave",
                     lv.get("hours") or lv.get("totalHours") or "-",
                     lv.get("note") or lv.get("reason") or "-", "leave"))
    rows.sort()
    body = "".join(
        f"<tr><td>{esc(d)}</td><td>{esc(n)}</td><td>{esc(t)}</td>"
        f"<td class='num'>{esc(h)}</td><td>{esc(r)}</td><td class='muted'>{esc(k)}</td></tr>"
        for (d, n, t, h, r, k) in rows
    ) or "<tr><td colspan='6' class='muted'>No leaves or day-offs scheduled.</td></tr>"
    return f"""
<section>
  <h2>Leaves &amp; day-offs &mdash; next week</h2>
  <table>
    <thead><tr><th>Date</th><th>Staff</th><th>Type</th><th>Hours</th><th>Reason</th><th>Source</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
</section>"""


CSS = """
:root { color-scheme: light dark; }
body { font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 2rem auto; max-width: 1100px; padding: 0 1rem; color: #1a1a1a; }
h1 { margin: 0 0 .25rem; font-size: 1.6rem; }
h2 { margin-top: 2.25rem; font-size: 1.15rem; border-bottom: 1px solid #ddd; padding-bottom: .3rem; }
header.meta { color: #555; margin-bottom: 1rem; }
table { width: 100%; border-collapse: collapse; margin-top: .5rem; }
th, td { padding: .45rem .6rem; border-bottom: 1px solid #eee; text-align: left; vertical-align: top; }
th { background: #f7f7f8; font-weight: 600; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.muted { color: #777; font-size: 0.9em; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.78rem; font-weight: 600; }
.badge.ok   { background: #e6f4ea; color: #137333; }
.badge.warn { background: #fff4ce; color: #8a6d00; }
.badge.over { background: #fde2e1; color: #b3261e; }
.row-over td { background: #fff5f4; }
.row-warn td { background: #fffbe6; }
@media (prefers-color-scheme: dark) {
  body { color: #eee; background: #111; }
  th { background: #1d1d1f; }
  th, td { border-color: #2a2a2a; }
  .muted { color: #999; }
  .row-over td { background: #2a1414; }
  .row-warn td { background: #2a2410; }
}
"""


def render(meta, sections_html):
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{esc(meta['title'])}</title>
<style>{CSS}</style>
</head><body>
<header class="meta">
  <h1>{esc(meta['title'])}</h1>
  <div>Week of <strong>{esc(meta['week_label'])}</strong> &middot;
       Generated {esc(meta['generated_at'])} &middot;
       Org: <strong>{esc(meta['org'])}</strong></div>
</header>
{''.join(sections_html)}
<footer class="muted" style="margin-top:2rem">
  <p>SG full-time barista standard: 9.5h &times; 5 days = 47.5h/week.
     Weekly cap source: per-staff <code>compensation.weeklyHours</code> when set; fallback {meta['default_cap']:.1f}h.
     Daily cap: {meta['daily_cap']:.1f}h. Warn at {meta['warn_pct']:.0f}% of weekly cap.</p>
</footer>
</body></html>
"""


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

    sections_html = [
        render_ot_section(staff, scheduled_next, comps_by_user,
                          args.ot_cap, args.daily_cap, args.ot_warn_pct, args.contract_filter),
        render_shifts_section(staff, scheduled_next, unassigned_next),
        render_timesheets_section(staff, actuals_prev, scheduled_prev),
        render_sales_section(sales_prev, sections),
        render_leaves_section(staff, day_offs_next, leaves_next),
    ]

    week_label = f"{next_from.date().isoformat()} – {(next_to.date() - timedelta(days=1)).isoformat()}"
    meta = {
        "title": f"StaffAny Weekly Report — {week_label}",
        "week_label": week_label,
        "generated_at": datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z"),
        "org": org_name or "(unknown)",
        "default_cap": args.ot_cap,
        "daily_cap": args.daily_cap,
        "warn_pct": args.ot_warn_pct,
    }
    html_out = render(meta, sections_html)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"Wrote {args.output} ({len(html_out):,} bytes)")


if __name__ == "__main__":
    main()
