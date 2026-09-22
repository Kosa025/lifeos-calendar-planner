from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from main import LifeOSPlanner

WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def test_adaptive_slots_for_day_with_no_conflicts_yields_one_full_block():
    planner = LifeOSPlanner()
    slots = planner._adaptive_slots_for_day(day_date=date(2026, 9, 22), existing_events=[])
    assert len(slots) == 1
    assert slots[0]["id"] == "D1"
    assert slots[0]["duration_min"] == slots[0]["remaining"]
    assert slots[0]["tasks"] == []
    assert slots[0]["status"] == "ok"


def test_adaptive_slots_for_day_splits_around_a_class():
    planner = LifeOSPlanner()
    existing_events = [{
        "summary": "Kozminski class",
        "calendar": "primary",
        "start_dt": datetime(2026, 9, 22, 9, 0, tzinfo=WARSAW_TZ),
        "end_dt": datetime(2026, 9, 22, 13, 0, tzinfo=WARSAW_TZ),
    }]
    slots = planner._adaptive_slots_for_day(day_date=date(2026, 9, 22), existing_events=existing_events)
    assert [s["id"] for s in slots] == ["D1", "D2"]
    assert slots[0]["time"] == "08:00-09:00"
    assert slots[1]["time"] == "13:00-21:00"


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
