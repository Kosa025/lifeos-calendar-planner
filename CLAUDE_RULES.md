# CLAUDE_RULES.md — LifeOS Calendar Planner

Rules for AI agents operating on this project. Read before modifying scheduling logic.

---

## Task Classification

| Type   | Keywords (examples)                                        | Duration estimate |
|--------|------------------------------------------------------------|-------------------|
| quick  | send, email, call, check, repost, message, ask, wyslac     | 15–30 min         |
| medium | homework, notes, planning, linkedin, cv, review, przejrzec | 45–90 min         |
| long   | course, project, thesis, learn, study, implement, develop  | 90–180 min        |

Classification is keyword-based (name.lower()). If both quick and long keywords match, classify as medium.

---

## LifeBlocks Structure

```
MR   06:55–08:00   Morning Routine     FIXED — no tasks ever
D1   08:00–11:15   Morning Block
  DS1  08:00–09:30   90 min   → TOP PRIORITY (P1)
  LIFEB_BREAKFAST  09:30–10:00  FIXED
  DS2  10:00–11:15   75 min   → P1 continuation
BUFFER  11:15–12:00  transition — unscheduled
D2   12:00–17:00   Afternoon Block
  DS3  12:00–13:00   60 min   → P1 remaining / P2
  DS4  13:05–14:00   55 min   → P2
  LIFEB_LUNCH  14:00–14:45  FIXED (flexible 13:00–15:00)
  DS5  15:00–16:00   60 min   → P2
  DS6  16:00–17:00   60 min   → P2
INT  17:00–18:00   Buffer (family, interruptions)  UNSCHEDULED
D3   18:00–21:00   Evening Block
  DS7  18:00–20:30  150 min   → P2 / P3
  DS_DAILY_LOG  20:30–21:00  FIXED SPECIAL SESSION
ER   21:00–23:00   Evening Routine     FIXED — no tasks ever
```

---

## Constraints — Never Violate

1. **MR** (06:55–08:00) — SACRED. No tasks. No exceptions.
2. **ER** (21:00–23:00) — SACRED. No tasks. No exceptions.
3. **DS_DAILY_LOG** (20:30–21:00) — FIXED. Only daily review content. No regular tasks.
4. **LIFEB_BREAKFAST / LIFEB_LUNCH** — Fixed blocks. Do not move or overwrite.
5. **INT** (17:00–18:00) — Always unscheduled. Note: `[INT buffer — sister pickup, calls, packages]`.

---

## Scheduling Algorithm

1. Load CSV → filter `Status != "Done"` and `Name != ""`
2. Classify each task (type + estimated_min)
3. Sort: P1 → P2 → P3 → Other → To Check; within priority, by Deadline ASC (None = far future)
4. Pin deadline tasks to their deadline date (or day before if deadline > week_start)
5. Distribute remaining tasks round-robin across 7 days
6. Fill sessions per day:
   - D1 (DS1, DS2) ← P1 tasks
   - D2 (DS3–DS6) ← remaining P1 + P2
   - D3 (DS7) ← P2 + P3 + Other + To Check
7. Tasks that exceed daily capacity → `overflow_tasks[]` with flag `⚠️ OVERFLOW — reschedule`

---

## Priority Placement

| Priority  | Preferred block | Fallback    |
|-----------|-----------------|-------------|
| P1        | D1 (DS1 first)  | D2          |
| P2        | D2              | D3 (DS7)    |
| P3        | D3 (DS7)        | Later days  |
| Other     | Any free slot   | —           |
| To Check  | Any free slot   | —           |

---

## INT Handling

- 17:00–18:00 is always reserved as unscheduled buffer
- Typical uses: family pickups, phone calls, unexpected packages
- Never schedule tasks here even if overflow exists

---

## CSV Parsing Notes

- File may start with BOM (`\ufeff`) — use `encoding="utf-8-sig"`
- Deadline field is mixed format: `"March 25, 2026"`, `"March 25, 2026 1:00 PM"`, `"March 13, 2026 12:00 (GMT+1)"`, `"No time"`, empty
- Strip `(GMT±N)` suffix before parsing
- `Status == "Inbox"` means unscheduled — treat as a normal active task

---

## DS Block Units

- Minimum unit: 15 minutes
- Valid lengths: 15, 30, 45, 60, 75, 90, 105, 120, 135, 150 min
- Multiple short tasks (quick) can share one DS
- One long task can occupy an entire DS
