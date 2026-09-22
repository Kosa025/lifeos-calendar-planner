"""
LifeOS Calendar Planner — Session 3
Priority-first weekly planner with Notion API + Google Calendar integration.
Usage:
    python main.py                                        # full run (Notion + Calendar)
    python main.py --no-calendar                          # plan only, no calendar write
    python main.py --csv "Daily Tasks.csv" --no-calendar  # CSV fallback, no calendar
"""

import csv
import json
import os
import argparse
import re
from datetime import datetime, timedelta, date, time
from typing import List, Dict, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

WARSAW_TZ = ZoneInfo("Europe/Warsaw")

from blocks import BusyInterval, compute_day_blocks

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ─── Constants ────────────────────────────────────────────────────────────────

QUICK_KEYWORDS = [
    "send", "email", "mail", "check", "call", "message", "msg", "napisac",
    "wyslac", "zadzwonic", "repost", "dodac", "reply", "ask", "zapytac",
    "write", "wiadomosc", "slack", "teams", "odpowiedz", "short", "quick",
    "notify", "reminder", "przypomnienie", "instagram", "linkedin post",
]

LONG_KEYWORDS = [
    "course", "kurs", "project", "projekt", "learn", "study", "nauka",
    "homework", "praca domowa", "implement", "build", "create", "zrobic",
    "make", "develop", "refactor", "analyze", "analiza", "research",
    "thesis", "praca", "prepare", "przygotowac", "plan", "strategy",
    "complete", "finish", "skonczyc", "dokonczyc", "review", "przejrzec",
    "advanced ml", "ai cv", "aplikacja",
]

DS_BLOCKS = {
    "D1": [
        {"id": "DS1", "time": "08:00-09:30", "duration_min": 90},
        {"id": "LIFEB_BREAKFAST", "time": "09:30-10:00", "duration_min": 30, "fixed": True},
        {"id": "DS2", "time": "10:00-11:15", "duration_min": 75},
    ],
    "D2": [
        {"id": "DS3", "time": "12:00-13:00", "duration_min": 60},
        {"id": "DS4", "time": "13:05-14:00", "duration_min": 55},
        {"id": "LIFEB_LUNCH", "time": "14:00-14:45", "duration_min": 45, "fixed": True},
        {"id": "DS5", "time": "15:00-16:00", "duration_min": 60},
        {"id": "DS6", "time": "16:00-17:00", "duration_min": 60},
    ],
    "D3": [
        {"id": "DS7", "time": "18:00-20:30", "duration_min": 150},
        {"id": "DS_DAILY_LOG", "time": "20:30-21:00", "duration_min": 30, "fixed": True},
    ],
}

MIN_BLOCK_MINUTES = 45  # placeholder — Maciej will tune this from his self-experiment logging (see spec)
MR_END_TIME = time(8, 0)
ER_START_TIME = time(21, 0)

PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2, "Other": 3, "To Check": 4}

GCAL_SCOPES = ["https://www.googleapis.com/auth/calendar"]

GCAL_COLORS = {
    "MR":           "2",   # Sage/Green
    "ER":           "2",   # Sage/Green
    "LIFEB":        "2",   # Sage/Green
    "D1":           "7",   # Peacock/Blue
    "D2":           "9",   # Blueberry/Dark Blue
    "D3":           "6",   # Tangerine/Orange
    "INT":          "8",   # Graphite/Gray
    "DS_DAILY_LOG": "5",   # Banana/Yellow
    "TO_CHECK":     "8",   # Graphite/Gray
    "WEEK_REVIEW":  "5",   # Banana/Yellow
}

DS_LABELS = {
    "DS1": "DS1 — Deep Work",
    "DS2": "DS2 — Deep Work",
    "DS3": "DS3 — Focus Block",
    "DS4": "DS4 — Focus Block",
    "DS5": "DS5 — Focus Block",
    "DS6": "DS6 — Focus Block",
    "DS7": "DS7 — Evening Work",
}


# ─── Standalone Calendar Helpers ──────────────────────────────────────────────

def get_calendar_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    token_path = "token.json"
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, GCAL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, GCAL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def get_or_create_lifeos_calendar(service) -> str:
    """Returns the calendarId for 'LifeOS Calendar Planner', creating it if needed."""
    calendar_list = service.calendarList().list().execute()
    for cal in calendar_list.get("items", []):
        if cal.get("summary") == "LifeOS Calendar Planner":
            print(f"[INFO] Using existing calendar: {cal['id']}")
            return cal["id"]

    new_calendar = {
        "summary": "LifeOS Calendar Planner",
        "description": "Automated LifeOS deep work blocks and routines",
        "timeZone": "Europe/Warsaw",
    }
    created = service.calendars().insert(body=new_calendar).execute()
    print(f"[INFO] Created new calendar: {created['id']}")
    return created["id"]


def get_existing_events(service, lifeos_cal_id: str, week_start: date, week_end: date) -> list:
    """
    Fetch events from ALL calendars (except LifeOS) for conflict detection.
    Returns list of dicts: {summary, calendar, start_dt, end_dt}
    """
    warsaw = ZoneInfo("Europe/Warsaw")
    time_min = datetime.combine(week_start, time(0, 0)).isoformat() + "Z"
    time_max = datetime.combine(week_end, time(23, 59)).isoformat() + "Z"
    calendar_list = service.calendarList().list().execute()
    all_calendars = calendar_list.get("items", [])
    existing = []
    for cal in all_calendars:
        cal_id = cal["id"]
        cal_name = cal.get("summary", cal_id)
        if cal_id == lifeos_cal_id:
            continue
        try:
            result = service.events().list(
                calendarId=cal_id, timeMin=time_min, timeMax=time_max,
                singleEvents=True, orderBy="startTime"
            ).execute()
            for event in result.get("items", []):
                start = event["start"].get("dateTime", event["start"].get("date"))
                end = event["end"].get("dateTime", event["end"].get("date"))
                if not start or not end:
                    continue
                try:
                    if "T" not in start:
                        continue  # Skip all-day events — they don't block timed DS slots
                    else:
                        start_dt = datetime.fromisoformat(
                            start.replace("Z", "+00:00")).astimezone(warsaw)
                        end_dt = datetime.fromisoformat(
                            end.replace("Z", "+00:00")).astimezone(warsaw)
                    existing.append({
                        "summary": event.get("summary", ""),
                        "calendar": cal_name,
                        "start_dt": start_dt,
                        "end_dt": end_dt,
                    })
                except Exception:
                    pass
        except Exception as e:
            print(f"[WARNING] Could not read calendar '{cal_name}': {e}")
            continue
    print(f"[INFO] Found {len(existing)} existing events across {len(all_calendars)} calendars")
    return existing


def overlaps(start1: datetime, end1: datetime, existing_events: list) -> bool:
    """Returns True if [start1, end1) overlaps with any existing event."""
    for ev in existing_events:
        if start1 < ev["end_dt"] and end1 > ev["start_dt"]:
            return True
    return False


def delete_lifeos_events_for_day(service, lifeos_cal_id: str, day_date: date):
    """Delete all LifeOS events for a given day. ONLY operates on lifeos_cal_id."""
    time_min = datetime.combine(day_date, time(0, 0)).isoformat() + "Z"
    time_max = datetime.combine(day_date, time(23, 59)).isoformat() + "Z"
    result = service.events().list(
        calendarId=lifeos_cal_id, timeMin=time_min, timeMax=time_max,
        singleEvents=True,
    ).execute()
    deleted = 0
    for event in result.get("items", []):
        service.events().delete(calendarId=lifeos_cal_id, eventId=event["id"]).execute()
        deleted += 1
    if deleted:
        print(f"[CLEANUP] Deleted {deleted} old LifeOS events for {day_date}")


# ─── LifeOSPlanner ────────────────────────────────────────────────────────────

class LifeOSPlanner:

    # ── Data loading ──────────────────────────────────────────────────────────

    def parse_csv(self, filepath: str) -> List[Dict]:
        """Load CSV, filter Done and empty-name rows, return active task list."""
        active = []
        skipped_done = 0
        skipped_empty = 0

        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("Name", "").strip()
                status = row.get("Status", "").strip()

                if not name:
                    skipped_empty += 1
                    continue
                if status == "Done":
                    skipped_done += 1
                    continue

                active.append({
                    "name": name,
                    "priority": row.get("Priority", "Other").strip() or "Other",
                    "status": status,
                    "deadline_raw": row.get("Deadline", "").strip(),
                    "scheduled_date_raw": row.get("Scheduled Date", "").strip(),
                    "created": row.get("Created time", "").strip(),
                    "last_edited": row.get("Last edited time", "").strip(),
                    "description": "",
                })

        print(f"\n{'='*55}")
        print("  LIFEOS PLANNER — CSV PARSE SUMMARY")
        print(f"{'='*55}")
        print(f"  Total rows read      : {len(active) + skipped_done + skipped_empty}")
        print(f"  Active tasks         : {len(active)}")
        print(f"  Skipped (Done)       : {skipped_done}")
        print(f"  Skipped (empty name) : {skipped_empty}")
        print(f"{'='*55}\n")
        return active

    def load_from_notion(self) -> List[Dict]:
        """Load tasks from Notion database. Returns [] if unavailable (triggers CSV fallback)."""
        token = os.getenv("NOTION_TOKEN")
        database_id = os.getenv("NOTION_DATABASE_ID")
        if not token or not database_id:
            print("[WARNING] Notion API unavailable — falling back to CSV")
            return []
        try:
            from notion_client import Client
            notion = Client(auth=token)
            response = notion.databases.query(
                database_id=database_id,
                filter={
                    "property": "Status",
                    "select": {"does_not_equal": "Done"},
                },
            )
            tasks = []
            for page in response.get("results", []):
                props = page.get("properties", {})

                def get_title(prop):
                    parts = prop.get("title", [])
                    return "".join(p.get("plain_text", "") for p in parts).strip()

                def get_select(prop):
                    sel = prop.get("select")
                    return sel.get("name", "") if sel else ""

                def get_date(prop):
                    d = prop.get("date")
                    return d.get("start", "") if d else ""

                name = get_title(props.get("Name", {}))
                if not name:
                    continue

                priority = get_select(props.get("Priority", {})) or "Other"
                status = get_select(props.get("Status", {}))
                deadline_raw = get_date(props.get("Deadline", {}))
                scheduled_date_raw = get_date(props.get("Scheduled Date", {}))

                description = ""
                try:
                    blocks = notion.blocks.children.list(block_id=page["id"])
                    description = self._extract_text_from_blocks(blocks)
                except Exception:
                    pass

                tasks.append({
                    "name": name,
                    "priority": priority,
                    "status": status,
                    "deadline_raw": deadline_raw,
                    "scheduled_date_raw": scheduled_date_raw,
                    "created": "",
                    "last_edited": "",
                    "description": description,
                })

            print(f"\n{'='*55}")
            print("  LIFEOS PLANNER — NOTION LOAD SUMMARY")
            print(f"{'='*55}")
            print(f"  Active tasks loaded  : {len(tasks)}")
            print(f"{'='*55}\n")
            return tasks

        except Exception as e:
            print(f"[WARNING] Notion API unavailable — falling back to CSV\n  Reason: {e}")
            return []

    def _extract_text_from_blocks(self, blocks_response: Dict) -> str:
        lines = []
        for block in blocks_response.get("results", []):
            btype = block.get("type", "")
            content = block.get(btype, {})
            rich_text = content.get("rich_text", [])
            text = "".join(t.get("plain_text", "") for t in rich_text)
            if text:
                lines.append(text)
        return "\n".join(lines)

    # ── Task classification ───────────────────────────────────────────────────

    def _parse_deadline(self, raw: str) -> Optional[date]:
        if not raw or raw.lower() in ("no time", ""):
            return None
        cleaned = re.sub(r"\s*\(GMT[+-]\d+\)", "", raw).strip()
        iso_match = re.match(r"(\d{4}-\d{2}-\d{2})", cleaned)
        if iso_match:
            try:
                return datetime.strptime(iso_match.group(1), "%Y-%m-%d").date()
            except ValueError:
                pass
        for fmt in (
            "%B %d, %Y %I:%M %p",
            "%B %d, %Y %H:%M",
            "%B %d, %Y",
        ):
            try:
                return datetime.strptime(cleaned, fmt).date()
            except ValueError:
                continue
        return None

    def classify_task(self, task: Dict) -> Dict:
        name_lower = task["name"].lower()
        is_long = any(kw in name_lower for kw in LONG_KEYWORDS)
        is_quick = any(kw in name_lower for kw in QUICK_KEYWORDS)

        if is_long and not is_quick:
            task_type = "long"
            est_min = 90
        elif is_quick and not is_long:
            task_type = "quick"
            est_min = 20
        else:
            task_type = "medium"
            est_min = 60

        task["task_type"] = task_type
        task["estimated_min"] = est_min
        task["deadline"] = self._parse_deadline(task.get("deadline_raw", ""))
        task["scheduled_date"] = self._parse_deadline(task.get("scheduled_date_raw", ""))
        return task

    # ── Scheduling ────────────────────────────────────────────────────────────

    def _adaptive_slots_for_day(self, day_date: date, existing_events: List[Dict]) -> List[Dict]:
        """
        Build this day's D1/D2/D3 slot list from its real calendar shape,
        using blocks.compute_day_blocks. Returns dicts shaped like the
        legacy static week_slots entries so _place_globally and
        _build_day_blocks keep working unchanged.
        """
        day_start = datetime.combine(day_date, MR_END_TIME, tzinfo=WARSAW_TZ)
        day_end = datetime.combine(day_date, ER_START_TIME, tzinfo=WARSAW_TZ)

        busy = [
            BusyInterval(start=ev["start_dt"], end=ev["end_dt"])
            for ev in existing_events
            if ev["start_dt"].date() == day_date or ev["end_dt"].date() == day_date
        ]

        day_blocks = compute_day_blocks(
            day_start=day_start, day_end=day_end,
            busy_intervals=busy, min_block_minutes=MIN_BLOCK_MINUTES,
        )

        return [
            {
                "id": b.id,
                "time": f"{b.start.strftime('%H:%M')}-{b.end.strftime('%H:%M')}",
                "duration_min": b.duration_min,
                "remaining": b.duration_min,
                "tasks": [],
                "status": "ok",
            }
            for b in day_blocks
        ]

    def generate_weekly_plan(
        self,
        tasks: List[Dict],
        existing_events: Optional[List[Dict]] = None,
        start_date: Optional[str] = None,
    ) -> Dict:
        """
        Distribute tasks across Mon-Sat using global priority filling.
        Sunday = Week Review only (no regular DS blocks).
        Slots that conflict with existing_events are marked BLOCKED.
        """
        if existing_events is None:
            existing_events = []

        if start_date is None:
            start_date = str(current_monday(date.today()))

        week_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        week_end = week_start + timedelta(days=6)
        days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday",
                        "Friday", "Saturday", "Sunday"]
        overflow: List[Dict] = []

        # ── Bucket tasks by priority ──────────────────────────────────────────
        p1_tasks: List[Dict] = []
        p2_tasks: List[Dict] = []
        p3_tasks: List[Dict] = []
        other_tasks: List[Dict] = []
        to_check_pinned: Dict[date, List[Dict]] = {}

        def _pin_date(t: Dict) -> Optional[date]:
            return t.get("deadline") or t.get("scheduled_date")

        for t in tasks:
            if t["priority"] == "To Check":
                pd = _pin_date(t)
                if pd:
                    if week_start <= pd <= week_end:
                        to_check_pinned.setdefault(pd, []).append(t)
                else:
                    p3_tasks.append(t)
            elif t["priority"] == "P1":
                p1_tasks.append(t)
            elif t["priority"] == "P2":
                p2_tasks.append(t)
            elif t["priority"] == "P3":
                p3_tasks.append(t)
            else:
                other_tasks.append(t)

        def _dl_key(t: Dict) -> date:
            d = t.get("deadline") or t.get("scheduled_date")
            return d if d else date(9999, 12, 31)

        p1_tasks.sort(key=_dl_key)
        p2_tasks.sort(key=_dl_key)
        p3_tasks.sort(key=_dl_key)

        # ── Build ordered slot list — Mon-Sat only (offset 0-5); Sunday excluded ──
        # Adaptive: each day's D1/D2/D3 come from its real calendar shape,
        # not a fixed weekly template (see blocks.compute_day_blocks).
        week_slots: List[Dict] = []
        for offset in range(6):  # 0=Mon … 5=Sat; 6=Sun handled separately
            day_date = week_start + timedelta(days=offset)
            for slot in self._adaptive_slots_for_day(day_date, existing_events):
                week_slots.append({
                    "day_offset": offset,
                    "block": slot["id"],
                    **slot,
                })

        # ── Mark slots that conflict with existing primary calendar events ──────
        blocked_count = 0
        for slot in week_slots:
            day_date = week_start + timedelta(days=slot["day_offset"])
            start_hhmm, end_hhmm = slot["time"].split("-")
            sh, sm = map(int, start_hhmm.split(":"))
            eh, em = map(int, end_hhmm.split(":"))
            ds_start = datetime(day_date.year, day_date.month, day_date.day,
                                sh, sm, tzinfo=WARSAW_TZ)
            ds_end = datetime(day_date.year, day_date.month, day_date.day,
                              eh, em, tzinfo=WARSAW_TZ)
            if overlaps(ds_start, ds_end, existing_events):
                print(f"[SKIP] {slot['id']} on {day_date} conflicts with existing event — skipping slot")
                slot["status"] = "BLOCKED"
                blocked_count += 1

        if blocked_count:
            print(f"[INFO] {blocked_count} DS slot(s) marked BLOCKED due to conflicts")

        # Mark slots that have fully ended today as PAST
        today = date.today()
        now = get_now_warsaw()
        for slot in week_slots:
            if slot["status"] != "ok":
                continue
            slot_day = week_start + timedelta(days=slot["day_offset"])
            if slot_day != today:
                continue
            start_hhmm, end_hhmm = slot["time"].split("-")
            eh, em = map(int, end_hhmm.split(":"))
            slot_end_dt = datetime(slot_day.year, slot_day.month, slot_day.day,
                                   eh, em, tzinfo=WARSAW_TZ)
            if slot_is_skippable(slot_end_dt, now):
                print(f"[PAST] Skipping {slot['id']} on {slot_day} — ended at {end_hhmm} "
                      f"(now {now.strftime('%H:%M')})")
                slot["status"] = "PAST"
            else:
                sh, sm = map(int, start_hhmm.split(":"))
                slot_start_dt = datetime(slot_day.year, slot_day.month, slot_day.day,
                                         sh, sm, tzinfo=WARSAW_TZ)
                if slot_start_dt <= now:
                    print(f"[KEEP] {slot['id']} on {slot_day} — in progress "
                          f"({slot['time']}), keeping")

        available_slots = [s for s in week_slots if s["status"] == "ok"]

        def _place_globally(queue: List[Dict], slots: List[Dict]) -> List[Dict]:
            unplaced = []
            for task in queue:
                needed = task["estimated_min"]
                placed = False
                for slot in slots:
                    if slot["remaining"] >= needed or (not slot["tasks"] and needed > slot["duration_min"]):
                        slot["tasks"].append(self._task_entry(task))
                        slot["remaining"] -= needed
                        placed = True
                        break
                if not placed:
                    unplaced.append(task)
            return unplaced

        overflow.extend(_place_globally(p1_tasks, available_slots))
        overflow.extend(_place_globally(p2_tasks, available_slots))
        overflow.extend(_place_globally(p3_tasks, available_slots))
        _place_globally(other_tasks, available_slots)

        # ── Assemble per-day plan ─────────────────────────────────────────────
        plan_days = []
        for offset in range(7):
            day_date = week_start + timedelta(days=offset)
            pinned = to_check_pinned.get(day_date, [])

            if offset == 6:  # Sunday
                plan_days.append({
                    "date": str(day_date),
                    "day": "Sunday",
                    "to_check": [self._task_entry(t) for t in pinned],
                    "blocks": self._build_sunday_blocks(),
                })
            else:
                day_slots = [s for s in week_slots if s["day_offset"] == offset]
                plan_days.append({
                    "date": str(day_date),
                    "day": days_of_week[offset],
                    "to_check": [self._task_entry(t) for t in pinned],
                    "blocks": self._build_day_blocks(day_slots, existing_events, day_date),
                })

        overflow_out = [
            {"name": t["name"], "priority": t["priority"], "reason": "OVERFLOW — reschedule"}
            for t in overflow
        ]

        return {
            "week_start": start_date,
            "generated_at": datetime.now().isoformat(),
            "overflow_tasks": overflow_out,
            "days": plan_days,
        }

    def _task_entry(self, t: Dict) -> Dict:
        entry = {
            "name": t["name"],
            "priority": t["priority"],
            "type": t["task_type"],
            "estimated_min": t["estimated_min"],
            "deadline": str(t["deadline"]) if t.get("deadline") else "no deadline",
        }
        if t.get("description"):
            entry["description"] = t["description"]
        return entry

    def _build_day_blocks(self, day_slots: List[Dict], existing_events=None, day_date=None) -> List[Dict]:
        blocks = []

        blocks.append({
            "block": "MR", "time": "06:55-08:00",
            "type": "Morning Routine", "fixed": True, "sessions": [],
        })

        for slot in day_slots:
            blocks.append({
                "block": slot["id"],
                "time": slot["time"],
                "fixed": False,
                "sessions": [{
                    "id": slot["id"],
                    "time": slot["time"],
                    "duration_min": slot["duration_min"],
                    "status": slot.get("status", "ok"),
                    "tasks": slot.get("tasks", []),
                }],
            })

        if existing_events is not None and day_date is not None:
            int_start = datetime.combine(day_date, time(17, 0), tzinfo=WARSAW_TZ)
            int_end   = datetime.combine(day_date, time(18, 0), tzinfo=WARSAW_TZ)
            int_free = not overlaps(int_start, int_end, existing_events)
        else:
            int_free = True
        if int_free:
            blocks.append({
                "block": "INT", "time": "17:00-18:00", "type": "buffer",
                "note": "[INT buffer — sister pickup, calls, packages]",
                "fixed": True, "sessions": [],
            })
        else:
            print(f"[SKIP] INT Buffer on {day_date} — slot occupied")

        blocks.append({
            "block": "ER", "time": "21:00-23:00",
            "type": "Evening Routine", "fixed": True, "sessions": [],
        })

        return blocks

    def _build_sunday_blocks(self) -> List[Dict]:
        return [
            {
                "block": "MR", "time": "06:55-08:00",
                "type": "Morning Routine", "fixed": True, "sessions": [],
            },
            {
                "block": "REST", "time": "", "type": "rest_day", "fixed": True, "sessions": [],
            },
            {
                "block": "D3", "time": "20:00-21:00", "fixed": False,
                "sessions": [
                    {
                        "id": "DS_WEEK_REVIEW",
                        "time": "20:00-21:00",
                        "type": "week_review",
                        "tasks": [],
                    }
                ],
            },
            {
                "block": "ER", "time": "21:00-23:00",
                "type": "Evening Routine", "fixed": True, "sessions": [],
            },
        ]

    # ── Export ────────────────────────────────────────────────────────────────

    def export_json(self, plan: Dict, output_path: str):
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        print(f"  [OK] JSON saved -> {output_path}")

    def export_readable(self, plan: Dict, output_path: str) -> str:
        lines = []
        week_start_str = datetime.strptime(plan["week_start"], "%Y-%m-%d").strftime("%B %d, %Y")
        lines.append(f"===== LIFEOS WEEKLY PLAN | Week of {week_start_str} =====")
        lines.append(f"Generated: {plan['generated_at'][:10]}")
        lines.append("")

        if plan["overflow_tasks"]:
            lines.append("  OVERFLOW TASKS (did not fit this week):")
            for t in plan["overflow_tasks"]:
                lines.append(f"  [{t['priority']}] {t['name']} -- {t['reason']}")
            lines.append("")

        for day in plan["days"]:
            lines.append(f"--- {day['day'].upper()}, {day['date']} ---")
            lines.append("")

            if day.get("to_check"):
                lines.append("  TO CHECK (pinned reminders for today):")
                for t in day["to_check"]:
                    lines.append(f"    [x] [{t['priority']}] {t['name']}")
                    if t.get("description"):
                        lines.append(f"       -> {t['description'][:120]}")
                lines.append("")

            for block in day["blocks"]:
                EN = "\u2013"
                EM = "\u2014"
                if block["block"] == "MR":
                    t = block['time'].replace('-', EN)
                    lines.append(f"[MR]    {t}  Morning Routine (FIXED)")
                elif block["block"] == "ER":
                    t = block['time'].replace('-', EN)
                    lines.append(f"[ER]    {t}  Evening Routine (FIXED)")
                elif block["block"] == "BUFFER":
                    t = block['time'].replace('-', EN)
                    lines.append(f"        {t}  {EM} buffer / transition")
                elif block["block"] == "INT":
                    t = block['time'].replace('-', EN)
                    lines.append(f"[INT]   {t}  {block.get('note','')}")
                elif block["block"] == "REST":
                    lines.append("")
                    lines.append(f"        {EM} Rest day {EM} no scheduled deep work {EM}")
                    lines.append("")
                elif block["block"] in ("D1", "D2", "D3"):
                    label_map = {"D1": "Morning Block", "D2": "Afternoon Block", "D3": "Evening Block"}
                    t = block['time'].replace('-', EN)
                    lines.append(f"[{block['block']}]    {t}  {label_map[block['block']]}")
                    for sess in block["sessions"]:
                        sid = sess["id"]
                        stime = sess["time"].replace("-", EN)

                        if sess.get("type") == "week_review":
                            lines.append(f"  DS_WEEK_REVIEW     {stime}  (FIXED SPECIAL)")
                            lines.append("    Review past week + plan next week")
                        elif sess.get("type") == "fixed_block":
                            label = sid.replace("LIFEB_", "").replace("_", " ")
                            lines.append(f"  {label:<18} {stime}  (FIXED)")
                        elif sid == "DS_DAILY_LOG":
                            lines.append(f"  DS_DAILY_LOG       {stime}  Daily Review (FIXED)")
                        else:
                            if sess.get("status") == "PAST":
                                continue  # omit fully-ended slots from txt
                            lines.append(f"  {sid:<18} {stime}")
                            if sess.get("status") == "BLOCKED":
                                lines.append("    [X] BLOCKED -- conflicts with existing calendar event")
                            else:
                                for t in sess["tasks"]:
                                    lines.append(
                                        f"    * [{t['priority']}] {t['name']} "
                                        f"(~{t['estimated_min']} min, {t['type']})"
                                    )
                                    if t.get("description"):
                                        lines.append(f"       -> {t['description'][:120]}")
                                if not sess["tasks"]:
                                    lines.append("    * (free slot)")
            lines.append("")
            lines.append("")

        text = "\n".join(lines)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"  [OK] Text saved  -> {output_path}")
        return text

    # ── Google Calendar ───────────────────────────────────────────────────────

    def write_to_google_calendar(self, plan: Dict, service, lifeos_cal_id: str):
        """
        Write weekly plan events to 'LifeOS Calendar Planner' calendar.
        - NEVER writes to 'primary' or any other calendar.
        - Deletes then reinserts LifeOS events for today and future days.
        - Skips past days entirely.
        - Skips fixed blocks that have fully ended today.
        - Sunday: Week Review only, no regular DS blocks.
        - Timezone: Europe/Warsaw.
        """
        tz = "Europe/Warsaw"
        week_start_str = plan["week_start"]
        today = date.today()
        now = get_now_warsaw()

        def _norm(s: str) -> str:
            return re.sub(r"([+-]\d{2}:\d{2}|Z)$", "", s)

        existing_keys: set = set()
        inserted: List[str] = []
        skipped: List[str] = []

        def _insert(event: Dict):
            summary = event.get("summary", "")
            start = event.get("start", {})
            raw = start.get("dateTime") or start.get("date", "")
            key = (summary, _norm(raw))
            if key in existing_keys:
                skipped.append(f"{summary} @ {_norm(raw)}")
                return
            service.events().insert(calendarId=lifeos_cal_id, body=event).execute()
            existing_keys.add(key)
            inserted.append(f"{summary} @ {_norm(raw)}")

        def _dt(day_str: str, hhmm: str) -> str:
            return f"{day_str}T{hhmm}:00"

        def _past(day_obj: date, end_hhmm: str) -> bool:
            """True if this fixed slot has fully ended on today."""
            if day_obj != today:
                return False
            eh, em = map(int, end_hhmm.split(":"))
            slot_end = datetime(day_obj.year, day_obj.month, day_obj.day,
                                eh, em, tzinfo=WARSAW_TZ)
            return slot_end <= now

        # ── Build events per day ──────────────────────────────────────────────
        for day in plan["days"]:
            d = day["date"]
            day_obj = date.fromisoformat(d)
            is_sunday = day["day"] == "Sunday"

            if day_obj < today:
                continue  # Never touch past days

            # Delete old LifeOS events for this day, then reinsert fresh
            delete_lifeos_events_for_day(service, lifeos_cal_id, day_obj)
            existing_keys -= {k for k in list(existing_keys) if k[1].startswith(d)}

            # Fixed routine blocks — all days
            if not _past(day_obj, "08:00"):
                _insert({
                    "summary": "Morning Routine",
                    "start": {"dateTime": _dt(d, "06:55"), "timeZone": tz},
                    "end":   {"dateTime": _dt(d, "08:00"), "timeZone": tz},
                    "colorId": GCAL_COLORS["MR"],
                    "description": "Fixed morning routine block — MR",
                })
            if not _past(day_obj, "23:00"):
                _insert({
                    "summary": "Evening Routine",
                    "start": {"dateTime": _dt(d, "21:00"), "timeZone": tz},
                    "end":   {"dateTime": _dt(d, "23:00"), "timeZone": tz},
                    "colorId": GCAL_COLORS["ER"],
                    "description": "Fixed evening routine block — ER",
                })

            if is_sunday:
                if not _past(day_obj, "21:00"):
                    _insert({
                        "summary": "Week Review & Planning",
                        "colorId": GCAL_COLORS["WEEK_REVIEW"],
                        "description": (
                            "Weekly review checklist:\n"
                            "What did I complete this week?\n"
                            "What didn't get done and why?\n"
                            "Top 3 priorities for next week\n"
                            "Schedule adjustments needed?\n"
                            "Update Notion Daily Tasks for next week"
                        ),
                        "start": {"dateTime": _dt(d, "20:00"), "timeZone": tz},
                        "end":   {"dateTime": _dt(d, "21:00"), "timeZone": tz},
                    })
                continue  # Skip all other blocks for Sunday

            # INT Buffer — only if plan includes it for this day (free slot check)
            has_int = any(b["block"] == "INT" for b in day.get("blocks", []))
            if has_int and not _past(day_obj, "18:00"):
                _insert({
                    "summary": "INT Buffer",
                    "start": {"dateTime": _dt(d, "17:00"), "timeZone": tz},
                    "end":   {"dateTime": _dt(d, "18:00"), "timeZone": tz},
                    "colorId": GCAL_COLORS["INT"],
                    "description": "[INT buffer — sister pickup, calls, packages]",
                })

            if not _past(day_obj, "10:00"):
                _insert({
                    "summary": "Breakfast",
                    "start": {"dateTime": _dt(d, "09:30"), "timeZone": tz},
                    "end":   {"dateTime": _dt(d, "10:00"), "timeZone": tz},
                    "colorId": GCAL_COLORS["LIFEB"],
                })
            if not _past(day_obj, "14:45"):
                _insert({
                    "summary": "Lunch",
                    "start": {"dateTime": _dt(d, "14:00"), "timeZone": tz},
                    "end":   {"dateTime": _dt(d, "14:45"), "timeZone": tz},
                    "colorId": GCAL_COLORS["LIFEB"],
                })
            if not _past(day_obj, "15:00"):
                _insert({
                    "summary": "Post-lunch walk",
                    "start": {"dateTime": _dt(d, "14:45"), "timeZone": tz},
                    "end":   {"dateTime": _dt(d, "15:00"), "timeZone": tz},
                    "colorId": GCAL_COLORS["LIFEB"],
                })
            if not _past(day_obj, "21:00"):
                _insert({
                    "summary": "Daily Log Review",
                    "start": {"dateTime": _dt(d, "20:30"), "timeZone": tz},
                    "end":   {"dateTime": _dt(d, "21:00"), "timeZone": tz},
                    "colorId": GCAL_COLORS["DS_DAILY_LOG"],
                    "description": "Daily review:\n* What went well?\n* What didn't?\n* 2 top tasks for tomorrow",
                })

            # DS sessions from plan blocks
            for block in day["blocks"]:
                block_id = block["block"]
                if block_id not in ("D1", "D2", "D3"):
                    continue
                color_id = GCAL_COLORS[block_id]

                for sess in block["sessions"]:
                    sid = sess["id"]
                    if sess.get("type") in ("fixed_block", "week_review") or sid == "DS_DAILY_LOG":
                        continue
                    if sess.get("status") in ("BLOCKED", "PAST"):
                        continue

                    start_t, end_t = sess["time"].split("-")
                    tasks = sess.get("tasks", [])
                    if tasks:
                        desc_lines = []
                        for t in tasks:
                            desc_lines.append(f"* [{t['priority']}] {t['name']} (~{t['estimated_min']} min)")
                            if t.get("description"):
                                snippet = t["description"][:200].replace("\n", " ")
                                desc_lines.append(f"  -> {snippet}")
                        description = "\n".join(desc_lines)
                    else:
                        description = "(free slot)"

                    _insert({
                        "summary": DS_LABELS.get(sid, sid),
                        "start": {"dateTime": _dt(d, start_t), "timeZone": tz},
                        "end":   {"dateTime": _dt(d, end_t),   "timeZone": tz},
                        "colorId": color_id,
                        "description": description,
                    })

            # To Check pinned — all-day events
            next_d = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            for t in day.get("to_check", []):
                _insert({
                    "summary": f"Check: {t['name'][:80]}",
                    "start": {"date": d},
                    "end":   {"date": next_d},
                    "colorId": GCAL_COLORS["TO_CHECK"],
                    "description": "To Check reminder — scheduled for this date",
                })

        print(f"\n[INFO] Inserted {len(inserted)} events, {len(skipped)} skipped.")
        if inserted:
            print("[CALENDAR] Inserted:")
            for s in inserted:
                print(f"  + {s}")
        if skipped:
            print("[CALENDAR] Skipped (duplicates):")
            for s in skipped:
                print(f"  ~ {s}")


# ─── Classification summary ───────────────────────────────────────────────────

def print_classification_summary(tasks: List[Dict]):
    by_priority: Dict[str, List] = {}
    by_type: Dict[str, List] = {"quick": [], "medium": [], "long": []}
    for t in tasks:
        by_priority.setdefault(t["priority"], []).append(t)
        by_type.setdefault(t["task_type"], []).append(t)

    print("TASK CLASSIFICATION SUMMARY")
    print("-" * 60)
    for p in ("P1", "P2", "P3", "Other", "To Check"):
        group = by_priority.get(p, [])
        if group:
            print(f"  {p:<10} {len(group):>2} tasks")
            for t in group:
                dl = str(t["deadline"]) if t.get("deadline") else "no deadline"
                print(f"           [{t['task_type']:<6} ~{t['estimated_min']:>3}m] {t['name'][:55]}  | {dl}")
    print("-" * 60)
    print(f"  quick   : {len(by_type.get('quick', []))} tasks")
    print(f"  medium  : {len(by_type.get('medium', []))} tasks")
    print(f"  long    : {len(by_type.get('long', []))} tasks")
    print("-" * 60)
    print()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def current_monday(from_date: date) -> date:
    return from_date - timedelta(days=from_date.weekday())


def get_now_warsaw() -> datetime:
    return datetime.now(ZoneInfo("Europe/Warsaw"))


def slot_is_skippable(slot_end_dt: datetime, now: datetime) -> bool:
    return slot_end_dt <= now


def get_current_week_range():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def task_is_schedulable(task: Dict, week_start: date, week_end: date) -> bool:
    scheduled = task.get("scheduled_date")
    if scheduled is None:
        return True
    if scheduled > week_end:
        return False
    return True


def next_monday(from_date: date) -> date:
    days_ahead = 7 - from_date.weekday()
    return from_date + timedelta(days=days_ahead if days_ahead != 7 else 7)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="LifeOS Weekly Planner")
    parser.add_argument("--csv", help="Path to CSV fallback file", default=None)
    parser.add_argument("--no-calendar", action="store_true", help="Skip Google Calendar write")
    parser.add_argument("--week", help="Week start YYYY-MM-DD (default: next Monday)", default=None)
    args = parser.parse_args()

    planner = LifeOSPlanner()

    # 1. Load tasks
    tasks = planner.load_from_notion()
    if not tasks and args.csv:
        tasks = planner.parse_csv(args.csv)
    elif not tasks:
        print("[ERROR] No tasks loaded. Provide --csv or configure NOTION_TOKEN in .env")
        raise SystemExit(1)

    tasks = [planner.classify_task(t) for t in tasks]

    # Apply Scheduled Date filter — exclude tasks scheduled for a future week
    week_filt_start, week_filt_end = get_current_week_range()
    tasks = [t for t in tasks if task_is_schedulable(t, week_filt_start, week_filt_end)]
    print(f"[INFO] {len(tasks)} tasks eligible this week (after Scheduled Date filter)")

    print_classification_summary(tasks)

    # 2. Determine week bounds for conflict fetch
    week_start_date = datetime.strptime(
        args.week if args.week else str(current_monday(date.today())), "%Y-%m-%d"
    ).date()
    week_end_date = week_start_date + timedelta(days=6)

    now_info = get_now_warsaw()
    print(f"[INFO] Week: {week_start_date} to {week_end_date}")
    print(f"[INFO] Current time (Warsaw): {now_info.strftime('%Y-%m-%d %H:%M')}")

    # 3. Get calendar service and resolve LifeOS calendar
    if not args.no_calendar:
        service = get_calendar_service()
        lifeos_cal_id = get_or_create_lifeos_calendar(service)
        existing_events = get_existing_events(service, lifeos_cal_id, week_start_date, week_end_date)
    else:
        service = None
        lifeos_cal_id = None
        existing_events = []

    # 4. Generate conflict-aware plan
    plan = planner.generate_weekly_plan(
        tasks,
        existing_events=existing_events,
        start_date=args.week,
    )

    # 5. Export files
    planner.export_json(plan, "weekly_plan.json")
    readable = planner.export_readable(plan, "weekly_plan.txt")

    print()
    safe = readable.encode("ascii", errors="replace").decode("ascii")
    print(safe)

    if plan["overflow_tasks"]:
        print(f"\n[!] {len(plan['overflow_tasks'])} task(s) overflowed — check overflow_tasks in weekly_plan.json")

    # 6. Write to LifeOS calendar
    if not args.no_calendar:
        planner.write_to_google_calendar(plan, service, lifeos_cal_id)

    print("\nDone. Files saved: weekly_plan.json, weekly_plan.txt")
