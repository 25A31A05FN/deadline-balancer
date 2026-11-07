# 📅 Deadline Balancer

An academic command centre for students. Enter your assignments, labs, quizzes and exams, and Deadline Balancer models your daily and weekly workload, flags overload, and proposes the **minimum deadline extensions** that remove it, spread fairly across subjects. It also includes a study timetable generator, exam-prep planner, submission tracker and progress analytics.

Built with [Streamlit](https://streamlit.io/) and pandas. Also usable as a standalone command-line tool.

## Features

| Page | What it does |
|---|---|
| **Overview** | Semester snapshot: upcoming deadlines, task progress, submission counts. |
| **My Tasks** | Editable task table. Import from **CSV, DOCX, PDF, PNG/JPG** (screenshots and photos are read with OCR). Export back to CSV. |
| **Deadline Balancer** | Detects overloaded days and weeks and suggests deadline shifts. Shows before/after workload charts, a per-subject fairness view, and downloads (CSV, chart PNG, PDF report). |
| **Study Planner** | Day-by-day study timetable based on task priority and your daily cap, deadline alerts, study recommendations, and `.ics` calendar export. |
| **Exam Preparation** | Per-subject exam plan from your exam date and available hours per day. |
| **Assignment Tracker** | Per-semester register of required assignments with Pending / Submitted / Late status and confirmation notes. Stored in a local SQLite database. |
| **Progress & Analytics** | Charts of tasks by subject, task status, and submissions by status. |
| **Settings** | Workload presets, caps, fairness, weekend rule, holidays and planning horizon. |

## How the balancing works

- Each task's effort (hours) is spread evenly from its start date to its deadline. If no start date is given, one is derived from the task type (e.g. assignment 7 days, project 14, lab 5, tutorial 4, quiz 3, exam 10 days before the deadline).
- You set capacity: hours per **weekday**, per **weekend day**, and per **week** (Mon–Sun). Overload score = total daily excess + total weekly excess.
- **Greedy step:** repeatedly apply the legal deadline extension with the best `overload reduction / (shift days × fairness penalty)`. The fairness penalty grows for subjects that were already shifted, so no single teacher's subject absorbs all the movement.
- **Prune step:** pull each moved deadline back toward its original date as long as overload does not get worse, leaving the smallest possible changes.

**Constraints respected**

- Quizzes and exams (or any task with `fixed = 1`) never move.
- Deadlines only move **later**, never beyond `max_shift_days` per task, and never past the horizon (e.g. semester end).
- Deadlines never land on holidays/blackout dates, and optionally not on weekends.

Default flexibility (days a deadline may move): assignment 5, project 7, tutorial 3, lab 3, quiz 0, exam 0.

**Workload presets** (weekday h / weekend h / weekly h): Light 3 / 2 / 18, Normal 5 / 3 / 28, Heavy 7 / 4 / 38.

## Getting started

### Requirements

- Python 3.11 recommended
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (needed only for reading images and scanned PDFs)

### Install

```bash
git clone <your-repo-url>
cd deadline-balancer

pip install -r requirements.txt

# OCR engine (Debian/Ubuntu); on macOS: brew install tesseract
sudo apt install tesseract-ocr
```

### Run the web app

```bash
streamlit run app.py
```

Then open http://localhost:8501.

> A Dev Container / GitHub Codespaces config is included. It installs the dependencies and starts the app automatically on port 8501.

### Run from the command line

```bash
python deadline_balancer.py sample_tasks.csv \
  --daily-cap 5 --weekend-cap 3 --weekly-cap 28 \
  --fairness 0.5 --no-weekend-deadlines \
  --blackout 2026-11-01 2026-11-05 \
  --horizon-end 2026-12-15 \
  --out balanced_deadlines.csv --chart workload.png
```

| Option | Default | Meaning |
|---|---|---|
| `tasks_csv` | n/a | Input task file (required) |
| `--today` | today | Reference date, `YYYY-MM-DD` |
| `--daily-cap` | 5.0 | Max hours on a weekday |
| `--weekend-cap` | 3.0 | Max hours on a weekend day |
| `--weekly-cap` | 28.0 | Max hours per Mon–Sun week |
| `--fairness` | 0.5 | Penalty for shifting an already-shifted subject (0 = off) |
| `--no-weekend-deadlines` | off | Disallow deadlines on weekends |
| `--blackout` | none | Dates deadlines cannot land on |
| `--horizon-end` | none | No deadline may move past this date |
| `--out` | `balanced_deadlines.csv` | Output CSV of new deadlines |
| `--chart` | `workload.png` | Workload chart (needs matplotlib) |

## Task file format

CSV with these columns (see [`sample_tasks.csv`](sample_tasks.csv)):

```csv
id,subject,title,type,effort_hours,deadline,start,fixed,max_shift_days
M1,Mathematics,Assignment 3,assignment,8,2026-10-30,,,
M2,Mathematics,Quiz 2,quiz,3,2026-10-29,,,
```

- **Required:** `subject`, `title`, `type`, `effort_hours`, `deadline` (`YYYY-MM-DD`)
- **Optional:** `start` (release date), `fixed` (1 = can't move), `max_shift_days`
- **Types:** `assignment`, `quiz`, `exam`, `project`, `lab`, `tutorial`

When importing in the app, column headers are matched flexibly (e.g. "course", "due date", "hours", "workload") and many date formats are understood (`30 Oct 2026`, `Oct 30th`, `30/10/26`, …). Imports from images and scanned PDFs are a **draft**; always review them in the editable table before balancing.

## Project structure

```
├── app.py                # Streamlit UI (all pages)
├── app_logic.py          # Presets, DataFrame ⇄ Task conversion, charts, PDF report
├── deadline_balancer.py  # Core balancing algorithm + CLI
├── extract.py            # Task import from CSV / DOCX / PDF / images (OCR)
├── study_features.py     # Priority scoring, timetable, exam plan, alerts, .ics export
├── assignment_tracker.py # SQLite-backed assignment submission register
├── sample_tasks.csv      # Example input
├── requirements.txt      # Python dependencies
├── packages.txt          # System packages (tesseract-ocr)
└── .devcontainer/        # Codespaces / Dev Container setup
```

The Assignment Tracker creates `assignment_tracker.db` next to the code on first use.

## Tech stack

Python · Streamlit · pandas · matplotlib · pdfplumber · pypdfium2 · pytesseract · Pillow · python-docx · SQLite

## Deploying

Works on [Streamlit Community Cloud](https://streamlit.io/cloud): `requirements.txt` and `packages.txt` are picked up automatically. Note that the SQLite tracker database is local to the running instance and may reset on redeploy.

## License

Add a license of your choice (e.g. MIT) before publishing.
