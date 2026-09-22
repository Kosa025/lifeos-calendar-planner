from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from main import LifeOSPlanner

WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def test_adaptive_slots_for_day_with_no_conflicts_splits_around_buffer_and_int():
    # With no calendar events, the day still isn't one unbroken 08:00-21:00
    # span: the fixed BUFFER (11:15-12:00) and INT (17:00-18:00) windows are
    # protected from adaptive placement, same as the old fixed template.
    planner = LifeOSPlanner()
    slots = planner._adaptive_slots_for_day(day_date=date(2026, 9, 22), existing_events=[])
    assert [s["id"] for s in slots] == ["D1", "D2", "D3"]
    assert slots[0]["time"] == "08:00-11:15"
    assert slots[1]["time"] == "12:00-17:00"
    assert slots[2]["time"] == "18:00-21:00"
    for s in slots:
        assert s["duration_min"] == s["remaining"]
        assert s["tasks"] == []
        assert s["status"] == "ok"


def test_adaptive_slots_for_day_splits_around_a_class():
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
    assert slots[1]["time"] == "13:00-17:00"
    assert slots[2]["time"] == "18:00-21:00"


def test_adaptive_slots_never_overlap_buffer_or_int_windows():
    # Regression test: an adaptive D-block, if left unprotected, would span
    # straight across the 11:15-12:00 BUFFER or 17:00-18:00 INT window
    # (both still separately rendered as their own fixed blocks in
    # _build_day_blocks) producing a silent double-booking. No slot's time
    # range may overlap either protected window, with or without other
    # calendar events present.
    buffer_start = time(11, 15)
    buffer_end = time(12, 0)
    int_start = time(17, 0)
    int_end = time(18, 0)

    def _overlaps_protected(slot_start: time, slot_end: time) -> bool:
        return (slot_start < buffer_end and slot_end > buffer_start) or \
               (slot_start < int_end and slot_end > int_start)

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
