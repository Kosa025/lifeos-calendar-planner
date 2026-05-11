# LifeOS Calendar Planner

An automated weekly schedule generator that reads tasks from **Notion**, detects conflicts across all your **Google Calendars**, and writes a structured deep-work plan back to a dedicated Google Calendar — respecting your real schedule.

Built around the LifeOS day architecture: fixed morning/evening routines, three deep-work blocks (D1/D2/D3), and an INT buffer.

---

## Features

- Pulls active tasks from a Notion database (filters out Done, applies priority order P1 → P2 → P3)
- Reads **all** your Google Calendars for conflict detection (not just primary) — skips all-day events, only blocks on real timed conflicts
- Generates a priority-first weekly plan: tasks are placed globally across Mon–Sat slots in priority order
- **"From now" mode** — when run mid-week, skips slots that have already ended today, keeps in-progress slots
- **Scheduled Date filter** — tasks scheduled for a future week are excluded from the current plan
- **INT Buffer awareness** — the 17:00–18:00 buffer slot is only added when it's genuinely free
- Deletes and reinserts LifeOS events for today and future days on every run (clean slate, no duplicates)
- Exports `weekly_plan.json` (machine-readable) and `weekly_plan.txt` (human-readable)
- CSV fallback if Notion is unavailable

---

## LifeOS Day Architecture

| Block    | Time          | Type                        |
|----------|---------------|-----------------------------|
| MR       | 06:55–08:00   | Morning Routine (fixed)     |
| D1       | 08:00–11:15   | Deep Work — Morning         |
| BUFFER   | 11:15–12:00   | Transition buffer           |
| D2       | 12:00–17:00   | Deep Work — Afternoon       |
| INT      | 17:00–18:00   | Buffer: family/calls/errands|
| D3       | 18:00–21:00   | Deep Work — Evening         |
| ER       | 21:00–23:00   | Evening Routine (fixed)     |

Sunday is a rest day with a Week Review block (20:00–21:00) only.

---

## Requirements

- Python 3.10+
- A Notion integration with access to your Daily Tasks database
- A Google Cloud project with the Calendar API enabled and OAuth2 credentials

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/lifeos-calendar-planner.git
cd lifeos-calendar-planner
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable                  | Description                                          |
|---------------------------|------------------------------------------------------|
| `NOTION_TOKEN`            | Notion integration token (`ntn_...`)                 |
| `NOTION_DATABASE_ID`      | ID of your Daily Tasks database                      |
| `GOOGLE_CREDENTIALS_PATH` | Path to your Google OAuth2 credentials JSON          |

### 4. Set up Notion integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Create a new integration, copy the token → `NOTION_TOKEN`
3. Open your Daily Tasks database in Notion → **Share** → invite the integration
4. Copy the database ID from the URL → `NOTION_DATABASE_ID`

Your Notion database needs these properties:

| Property         | Type   | Used for                              |
|------------------|--------|---------------------------------------|
| `Name`           | Title  | Task name                             |
| `Status`         | Select | Filters out `Done` tasks              |
| `Priority`       | Select | `P1` / `P2` / `P3` / `Other` / `To Check` |
| `Deadline`       | Date   | Sorts tasks within priority groups    |
| `Scheduled Date` | Date   | Excludes tasks planned for future weeks |

### 5. Set up Google Calendar credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services** → **Credentials**
2. Enable the **Google Calendar API** for your project
3. Create an **OAuth 2.0 Client ID** (Desktop app type)
4. Download `credentials.json` and place it in the project folder
5. On first run, a browser window will open for you to authorise access — `token.json` is saved automatically after that

---

## Usage

```bash
# Full run: fetch from Notion + write to Google Calendar
python main.py

# Plan only — no calendar write (safe to test)
python main.py --no-calendar

# CSV fallback instead of Notion
python main.py --csv "Daily Tasks.csv" --no-calendar

# Plan a specific week (default: current week's Monday)
python main.py --week 2026-05-05
```

### Example terminal output

```
[INFO] Week: 2026-04-20 to 2026-04-26
[INFO] Current time (Warsaw): 2026-04-22 10:20
[INFO] Found 38 existing events across 6 calendars
[INFO] 55 tasks eligible this week (after Scheduled Date filter)
[PAST] Skipping DS1 on 2026-04-22 — ended at 09:30 (now 10:20)
[KEEP] DS2 on 2026-04-22 — in progress (10:00-11:15), keeping
[SKIP] INT Buffer on 2026-04-22 — slot occupied
[CLEANUP] Deleted 4 old LifeOS events for 2026-04-22
[INFO] Inserted 49 events, 0 skipped.
Done. Files saved: weekly_plan.json, weekly_plan.txt
```

---

## Project Structure

```
lifeos-calendar-planner/
├── main.py              # Core planner — all logic lives here
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
├── .gitignore
└── README.md
```

---

## Security notes

- `credentials.json` and `token.json` are in `.gitignore` — never commit them
- `.env` is in `.gitignore` — never commit it
- The planner **only writes to** the dedicated `LifeOS Calendar Planner` calendar — it never touches primary or any other calendar
- It **never deletes** from any calendar other than `LifeOS Calendar Planner`

---

## Timezone

All scheduling is done in **Europe/Warsaw** (CET/CEST). To change it, replace `WARSAW_TZ = ZoneInfo("Europe/Warsaw")` at the top of `main.py`.
