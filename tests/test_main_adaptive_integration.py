from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from main import LifeOSPlanner

WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def test_adaptive_slots_for_day_with_no_conflicts_splits_around_buffer_and_int():
    # With no calendar events, the day still isn't one unbroken 08:00-21:00
    # span: BUFFER (11:15-12:00), INT (17:00-18:00), Breakfast (9:30-10:00),
    # Lunch+walk (14:00-15:00), and Daily Log Review (20:30-21:00) are all
    # protected from adaptive placement. That leaves 5 real gaps of 90, 75,
    # 120, 120, and 150 minutes — the 3 longest (150, then the two 120s in
    # chronological order) become D1/D2/D3.
    planner = LifeOSPlanner()
    slots = planner._adaptive_slots_for_day(day_date=date(2026, 9, 22), existing_events=[])
    assert [s["id"] for s in slots] == ["D1", "D2", "D3"]
    assert slots[0]["time"] == "12:00-14:00"
    assert slots[1]["time"] == "15:00-17:00"
    assert slots[2]["time"] == "18:00-20:30"
    for s in slots:
        assert s["duration_min"] == s["remaining"]
        assert s["tasks"] == []
        assert s["status"] == "ok"


def test_adaptive_slots_for_day_splits_around_a_class():
    # The class (9:00-13:00) swallows Breakfast and BUFFER into one merged
    # busy interval. Combined with Lunch+walk (14:00-15:00), INT
    # (17:00-18:00), and Daily Log Review (20:30-21:00), the gaps are
    # 60, 60, 120, 150 minutes — the 3 longest keep 150, 120, and the
    # first 60 (08:00-09:00), dropping the second 60 (13:00-14:00).
    planner = LifeOSPlanner()
    existing_events = [{
        "summary": "Kozminski class",
        "calendar": "primary",
        "start_dt": datetime(2026, 9, 22, 9, 0, tzinfo=WARSAW_TZ),
        "end_dt": datetime(2026, 9, 22, 13, 0, tzinfo=WARSAW_TZ),
    }]
    slots = planner._adaptive_slots_for_day(day_date=date(2026, 9, 22), existing_events=existing_events)
    assert [s["id"] for s in slots] == ["D1", "D2", "D3"]
    assert slots[0]["time"] == "08:00-09:00"
    assert slots[1]["time"] == "15:00-17:00"
    assert slots[2]["time"] == "18:00-20:30"


def test_adaptive_slots_never_overlap_buffer_or_int_windows():
    # Regression test: an adaptive D-block, if left unprotected, would span
    # straight across the 11:15-12:00 BUFFER or 17:00-18:00 INT window
    # (both still separately rendered as their own fixed blocks in
    # _build_day_blocks), or across the meal/log windows that
    # write_to_google_calendar inserts unconditionally (Breakfast, Lunch,
    # Post-lunch walk, Daily Log Review) — producing a silent
    # double-booking. No slot's time range may overlap any protected
    # window, with or without other calendar events present.
    protected_windows = [
        (time(11, 15), time(12, 0)),   # BUFFER
        (time(17, 0), time(18, 0)),    # INT
        (time(9, 30), time(10, 0)),    # Breakfast
        (time(14, 0), time(14, 45)),   # Lunch
        (time(14, 45), time(15, 0)),   # Post-lunch walk
        (time(20, 30), time(21, 0)),   # Daily Log Review
    ]

    def _overlaps_protected(slot_start: time, slot_end: time) -> bool:
        return any(
            slot_start < win_end and slot_end > win_start
            for win_start, win_end in protected_windows
        )

    planner = LifeOSPlanner()

    scenarios = [
        [],
        [{
            "summary": "Kozminski class",
            "calendar": "primary",
            "start_dt": datetime(2026, 9, 22, 9, 0, tzinfo=WARSAW_TZ),
            "end_dt": datetime(2026, 9, 22, 13, 0, tzinfo=WARSAW_TZ),
        }],
    ]
    for existing_events in scenarios:
        slots = planner._adaptive_slots_for_day(day_date=date(2026, 9, 22), existing_events=existing_events)
        for s in slots:
            sh, sm = map(int, s["time"].split("-")[0].split(":"))
            eh, em = map(int, s["time"].split("-")[1].split(":"))
            assert not _overlaps_protected(time(sh, sm), time(eh, em)), \
                f"slot {s['id']} ({s['time']}) overlaps a protected BUFFER/INT window"


def test_adaptive_slots_for_day_blocked_by_multi_day_event():
    # An event spanning Monday 20:00 -> Wednesday 10:00 neither starts nor
    # ends on Tuesday, but it still fully occupies Tuesday's whole
    # 08:00-21:00 workable window and must block adaptive placement that
    # day (see Finding 4: the old per-day filter matched only
    # start_dt.date()/end_dt.date(), silently treating a day entirely
    # inside a multi-day event as fully free and handing out D1/D2/D3
    # slots that double-book the conference). With the filter removed,
    # compute_day_blocks clips the event to Tuesday's window itself and
    # correctly finds zero free gaps.
    planner = LifeOSPlanner()
    existing_events = [{
        "summary": "Conference",
        "calendar": "primary",
        "start_dt": datetime(2026, 9, 21, 20, 0, tzinfo=WARSAW_TZ),
        "end_dt": datetime(2026, 9, 23, 10, 0, tzinfo=WARSAW_TZ),
    }]
    slots = planner._adaptive_slots_for_day(day_date=date(2026, 9, 22), existing_events=existing_events)
    assert slots == []


def test_generate_weekly_plan_places_task_into_adaptive_block():
    planner = LifeOSPlanner()
    tasks = [{
        "name": "Write report", "priority": "P1", "status": "Inbox",
        "deadline_raw": "", "scheduled_date_raw": "", "created": "",
        "last_edited": "", "description": "",
    }]
    tasks = [planner.classify_task(t) for t in tasks]

    plan = planner.generate_weekly_plan(tasks, existing_events=[], start_date="2026-09-21")

    monday = plan["days"][0]
    d1_block = next(b for b in monday["blocks"] if b["block"] == "D1")
    placed_names = [
        t["name"] for sess in d1_block["sessions"] for t in sess.get("tasks", [])
    ]
    assert "Write report" in placed_names
