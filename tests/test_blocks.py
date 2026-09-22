from datetime import datetime
from zoneinfo import ZoneInfo

from blocks import BusyInterval, DayBlock, compute_day_blocks

TZ = ZoneInfo("Europe/Warsaw")


def _dt(hour, minute=0):
    return datetime(2026, 9, 22, hour, minute, tzinfo=TZ)


def test_no_busy_intervals_yields_single_full_block():
    blocks = compute_day_blocks(
        day_start=_dt(8, 0), day_end=_dt(21, 0),
        busy_intervals=[], min_block_minutes=45,
    )
    assert len(blocks) == 1
    assert blocks[0].id == "D1"
    assert blocks[0].start == _dt(8, 0)
    assert blocks[0].end == _dt(21, 0)
    assert blocks[0].duration_min == 13 * 60


def test_single_busy_interval_splits_into_two_blocks():
    busy = [BusyInterval(start=_dt(9, 0), end=_dt(13, 0))]
    blocks = compute_day_blocks(
        day_start=_dt(8, 0), day_end=_dt(21, 0),
        busy_intervals=busy, min_block_minutes=45,
    )
    assert [b.id for b in blocks] == ["D1", "D2"]
    assert blocks[0].start == _dt(8, 0)
    assert blocks[0].end == _dt(9, 0)
    assert blocks[1].start == _dt(13, 0)
    assert blocks[1].end == _dt(21, 0)


def test_gap_shorter_than_minimum_is_dropped_not_kept_as_fake_block():
    # Two busy intervals leave a 20-minute gap between them — below the 45 min minimum.
    busy = [
        BusyInterval(start=_dt(8, 0), end=_dt(12, 0)),
        BusyInterval(start=_dt(12, 20), end=_dt(21, 0)),
    ]
    blocks = compute_day_blocks(
        day_start=_dt(8, 0), day_end=_dt(21, 0),
        busy_intervals=busy, min_block_minutes=45,
    )
    assert blocks == []


def test_busy_interval_clipped_to_window_bounds():
    # Busy interval starts before day_start and ends after day_end — should be
    # treated as fully covering the window, leaving no free blocks.
    busy = [BusyInterval(start=_dt(0, 0), end=_dt(23, 59))]
    blocks = compute_day_blocks(
        day_start=_dt(8, 0), day_end=_dt(21, 0),
        busy_intervals=busy, min_block_minutes=45,
    )
    assert blocks == []


def test_overlapping_busy_intervals_are_merged():
    busy = [
        BusyInterval(start=_dt(9, 0), end=_dt(11, 0)),
        BusyInterval(start=_dt(10, 0), end=_dt(13, 0)),  # overlaps the first
    ]
    blocks = compute_day_blocks(
        day_start=_dt(8, 0), day_end=_dt(21, 0),
        busy_intervals=busy, min_block_minutes=45,
    )
    assert [b.id for b in blocks] == ["D1", "D2"]
    assert blocks[0].end == _dt(9, 0)
    assert blocks[1].start == _dt(13, 0)


def test_more_than_three_gaps_keeps_the_three_longest():
    # Four busy intervals leave five free gaps of 60, 45, 45, 45, and 405
    # minutes. The three LONGEST survive (405, 60, and the first of the
    # 45-min ties), then get re-sorted chronologically for D1/D2/D3
    # labeling — the evening block (405 min) must not be discarded just
    # because it's chronologically last.
    busy = [
        BusyInterval(start=_dt(9, 0), end=_dt(9, 45)),
        BusyInterval(start=_dt(10, 30), end=_dt(11, 15)),
        BusyInterval(start=_dt(12, 0), end=_dt(12, 45)),
        BusyInterval(start=_dt(13, 30), end=_dt(14, 15)),
    ]
    blocks = compute_day_blocks(
        day_start=_dt(8, 0), day_end=_dt(21, 0),
        busy_intervals=busy, min_block_minutes=45,
    )
    assert [b.id for b in blocks] == ["D1", "D2", "D3"]
    assert blocks[0].start == _dt(8, 0)
    assert blocks[0].end == _dt(9, 0)
    assert blocks[1].start == _dt(9, 45)
    assert blocks[1].end == _dt(10, 30)
    assert blocks[2].start == _dt(14, 15)
    assert blocks[2].end == _dt(21, 0)


def test_busy_interval_entirely_outside_window_is_ignored():
    busy = [BusyInterval(start=_dt(22, 0), end=_dt(23, 0))]
    blocks = compute_day_blocks(
        day_start=_dt(8, 0), day_end=_dt(21, 0),
        busy_intervals=busy, min_block_minutes=45,
    )
    assert len(blocks) == 1
    assert blocks[0].start == _dt(8, 0)
    assert blocks[0].end == _dt(21, 0)
