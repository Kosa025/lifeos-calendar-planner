"""Adaptive D-block boundary computation.

Computes a single day's D1/D2/D3 windows from its real calendar shape
instead of a fixed weekly clock template — see
docs/superpowers/plans/2026-09-21-adaptive-day-blocks.md and the spec's
"D1 / D2 / D3 — adaptive deep-work chunks" section for the design this
implements.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List


@dataclass
class BusyInterval:
    start: datetime
    end: datetime


@dataclass
class DayBlock:
    id: str
    start: datetime
    end: datetime

    @property
    def duration_min(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def _merge_and_clip(
    busy_intervals: List[BusyInterval], day_start: datetime, day_end: datetime
) -> List[BusyInterval]:
    """Clip each interval to [day_start, day_end], drop empty/out-of-window
    ones, then merge overlapping/touching intervals."""
    clipped = []
    for iv in busy_intervals:
        start = max(iv.start, day_start)
        end = min(iv.end, day_end)
        if start < end:
            clipped.append(BusyInterval(start=start, end=end))

    clipped.sort(key=lambda iv: iv.start)
    merged: List[BusyInterval] = []
    for iv in clipped:
        if merged and iv.start <= merged[-1].end:
            merged[-1].end = max(merged[-1].end, iv.end)
        else:
            merged.append(BusyInterval(start=iv.start, end=iv.end))
    return merged


def compute_day_blocks(
    day_start: datetime,
    day_end: datetime,
    busy_intervals: List[BusyInterval],
    min_block_minutes: int,
) -> List[DayBlock]:
    """
    Compute D1/D2/D3 as the free gaps between day_start and day_end (the
    workable window between MR ending and ER starting) after subtracting
    busy_intervals. Gaps shorter than min_block_minutes are dropped rather
    than kept as a fake block. Returns 0-3 DayBlock entries in
    chronological order, labeled D1/D2/D3 — if more than three real gaps
    exist, only the first three (chronologically) are kept.
    """
    busy = _merge_and_clip(busy_intervals, day_start, day_end)

    gaps: List[tuple] = []
    cursor = day_start
    for iv in busy:
        if cursor < iv.start:
            gaps.append((cursor, iv.start))
        cursor = max(cursor, iv.end)
    if cursor < day_end:
        gaps.append((cursor, day_end))

    min_seconds = min_block_minutes * 60
    real_gaps = [g for g in gaps if (g[1] - g[0]).total_seconds() >= min_seconds]

    labels = ["D1", "D2", "D3"]
    return [
        DayBlock(id=labels[i], start=g[0], end=g[1])
        for i, g in enumerate(real_gaps[:3])
    ]
