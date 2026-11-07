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

## What each file does

### `app.py`: the web interface
The Streamlit entry point (`streamlit run app.py`). It builds the sidebar navigation and all eight pages (Overview, My Tasks, Deadline Balancer, Study Planner, Exam Preparation, Assignment Tracker, Progress & Analytics, Settings). It holds the UI state (task table, caps, holidays, horizon) in `st.session_state` and calls the other modules to do the real work. It contains no scheduling logic of its own.

### `deadline_balancer.py`: the core engine and CLI
The heart of the project, with no UI dependencies.
- **Data model:** `Task` (one piece of work with effort, start, deadline, original deadline) and `Config` (daily/weekend/weekly caps, fairness, weekend and holiday rules, horizon).
- **Workload maths:** `daily_load`, `weekly_load`, `overload_score`, `overloaded_days`, `overloaded_weeks`.
- **Balancing:** `balance()` greedily applies the best legal deadline extension, then `prune()` pulls deadlines back toward their originals to keep changes minimal. `legal_deadline()` enforces holidays and weekend rules.
- **I/O and CLI:** `load_tasks()` reads a CSV, `report()` prints a text summary, `write_csv()` and `make_chart()` / `write_chart()` produce the outputs, and `main()` is the command-line entry point.

### `app_logic.py`: glue between the UI and the engine
Helpers that turn UI data into engine data and engine results back into things the UI can show.
- `PRESETS` (Light / Normal / Heavy workloads) and `sample_df()` (the demo tasks shown on first launch).
- `parse_holidays()` parses the holiday text box; `df_to_tasks()` converts the editable table into `Task` objects.
- `changes_df()`, `weekly_df()`, `fairness_df()` and `summary()` build the result tables.
- `chart_png()` and `report_pdf()` produce the downloadable chart and PDF report.

### `extract.py`: importing tasks from files
Reads a task list from **CSV, DOCX, PDF, PNG or JPG** and returns a table plus plain-language notes about what was guessed.
- Matches messy column headers to the standard ones (`SYNONYMS`), recognises many date formats, infers the year, and guesses type and hours from free text (`parse_text`).
- Uses OCR (pytesseract) for images and scanned PDFs, and pdfplumber / python-docx for text PDFs and Word files.
- Entry point is `read_tasks(data, filename, today)`. OCR results are drafts, so the app asks you to review them.

### `study_features.py`: planning and study tools
Everything beyond deadline balancing.
- `priority_score()` / `add_priority_columns()`: a transparent score from urgency, your priority (Low to Urgent), exam/quiz type and effort; also tracks status and completed hours.
- `progress_summary()`, `deadline_alerts()` (what's due in the next N days) and `study_recommendations()`.
- `build_timetable()`: a day-by-day study schedule within your daily cap.
- `exam_preparation_plan()`: a per-subject plan leading up to an exam date.
- `make_ics()`: exports deadlines as a calendar file for Google/Apple/Outlook.

### `assignment_tracker.py`: submission register (SQLite)
A small database layer for the Assignment Tracker page. It creates `assignment_tracker.db` and an `assignments` table (semester, subject, assignment number, title, due date, status, submitted date, confirmation note), with `load_assignments()`, `save_assignment()`, `delete_assignment()` and `replace_all()`.

### `sample_tasks.csv`
Example input with Mathematics, Physics, Computer Science and Electronics tasks. Use it to try the CLI or to see the expected column format.

### `requirements.txt` and `packages.txt`
`requirements.txt` lists the Python packages (Streamlit, pandas, matplotlib, Pillow, pdfplumber, pypdfium2, pytesseract, pyarrow, python-docx). `packages.txt` lists system packages (`tesseract-ocr`) that Streamlit Cloud and the Dev Container install automatically.

### `.devcontainer/devcontainer.json`
Dev Container / GitHub Codespaces setup: Python 3.11 image, installs dependencies, auto-starts the app and forwards port 8501.

### `__pycache__/`
Python's compiled bytecode cache, generated automatically. It can be deleted and should be added to `.gitignore`.

## Tech stack

Python · Streamlit · pandas · matplotlib · pdfplumber · pypdfium2 · pytesseract · Pillow · python-docx · SQLite

## Deploying

Works on [Streamlit Community Cloud](https://streamlit.io/cloud): `requirements.txt` and `packages.txt` are picked up automatically. Note that the SQLite tracker database is local to the running instance and may reset on redeploy.

## License

Add a license of your choice (e.g. MIT) before publishing.
