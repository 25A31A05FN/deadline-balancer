"""UI-independent helpers for the Streamlit app (kept separate so they can be tested)."""
from __future__ import annotations

import io
from collections import defaultdict
from datetime import date, timedelta
from typing import List, Tuple

import pandas as pd

from deadline_balancer import (DEFAULT_MAX_SHIFT, FIXED_TYPES, LEAD_DAYS, Config, Task,
                               daily_load, make_chart, overload_score, overloaded_days,
                               overloaded_weeks, weekly_load)
from extract import COLUMNS, TYPES

# name -> (weekday hours, weekend-day hours, hours per week)
PRESETS = {
    "Light": (3.0, 2.0, 18.0),
    "Normal": (5.0, 3.0, 28.0),
    "Heavy": (7.0, 4.0, 38.0),
}

_SAMPLE = [  # subject, title, type, hours, days from today
    ("Mathematics", "Assignment 3", "assignment", 8, 4),
    ("Mathematics", "Quiz 2", "quiz", 3, 3),
    ("Physics", "Lab Report 4", "lab", 6, 4),
    ("Physics", "Tutorial Sheet 5", "tutorial", 4, 3),
    ("Computer Science", "Mini Project", "project", 20, 4),
    ("Computer Science", "Assignment 2", "assignment", 7, 7),
    ("Electronics", "Assignment 4", "assignment", 8, 4),
    ("Electronics", "Tutorial 6", "tutorial", 3, 5),
    ("Humanities", "Essay", "assignment", 6, 8),
    ("Humanities", "Presentation Prep", "project", 10, 11),
    ("Mathematics", "Tutorial 7", "tutorial", 3, 10),
    ("Physics", "Assignment 6", "assignment", 6, 14),
]


def sample_df(today: date) -> pd.DataFrame:
    rows = [dict(subject=s, title=t, type=k, effort_hours=float(h), deadline=today + timedelta(d),
                 start=None, fixed=k in FIXED_TYPES, max_shift_days=None)
            for s, t, k, h, d in _SAMPLE]
    return pd.DataFrame(rows, columns=COLUMNS)


def parse_holidays(text: str) -> Tuple[set, List[str]]:
    days, bad = set(), []
    for part in text.replace(";", ",").replace("\n", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            days.add(date.fromisoformat(part))
        except ValueError:
            bad.append(part)
    return days, bad


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT or str(v) in ("", "NaT", "nan")


def df_to_tasks(df: pd.DataFrame, today: date) -> Tuple[List[Task], int, int]:
    """Table -> Task objects. Returns (tasks, incomplete_rows_skipped, past_due_skipped)."""
    tasks, incomplete, past = [], 0, 0
    for i, r in enumerate(df.to_dict("records"), start=1):
        if _blank(r.get("deadline")) or _blank(r.get("effort_hours")) or float(r["effort_hours"]) <= 0:
            if not all(_blank(r.get(k)) for k in ("subject", "title", "deadline", "effort_hours")):
                incomplete += 1
            continue
        dl = pd.Timestamp(r["deadline"]).date()
        if dl < today:
            past += 1
            continue
        kind = r.get("type") if r.get("type") in TYPES else "assignment"
        start = pd.Timestamp(r["start"]).date() if not _blank(r.get("start")) else dl - timedelta(LEAD_DAYS.get(kind, 7) - 1)
        start = min(max(start, today), dl)
        fixed = bool(r.get("fixed")) or kind in FIXED_TYPES
        ms = DEFAULT_MAX_SHIFT.get(kind, 3) if _blank(r.get("max_shift_days")) else int(r["max_shift_days"])
        title = r["title"] if not _blank(r.get("title")) else f"Task {i}"
        subject = r["subject"] if not _blank(r.get("subject")) else "General"
        tasks.append(Task(f"T{i}", str(subject), str(title), kind, float(r["effort_hours"]), dl, start,
                          fixed, 0 if fixed else ms, dl))
    return tasks, incomplete, past


def changes_df(new: List[Task]) -> pd.DataFrame:
    rows = [dict(Subject=t.subject, Task=t.title, **{"Original due date": t.original_deadline,
                 "New due date": t.deadline, "Delay (days)": t.shift})
            for t in sorted(new, key=lambda x: x.original_deadline) if t.shift > 0]
    return pd.DataFrame(rows, columns=["Subject", "Task", "Original due date", "New due date", "Delay (days)"])


def weekly_df(orig: List[Task], new: List[Task], cfg: Config) -> pd.DataFrame:
    b, a = weekly_load(daily_load(orig)), weekly_load(daily_load(new))
    rows = []
    for w in sorted(set(b) | set(a)):
        rows.append({"Week starting": w, "Hours before": round(b.get(w, 0), 1),
                     "Hours after": round(a.get(w, 0), 1), "Weekly limit": cfg.weekly_cap})
    return pd.DataFrame(rows)


def fairness_df(new: List[Task]) -> pd.DataFrame:
    per = defaultdict(int)
    for t in new:
        per[t.subject] += t.shift
    return pd.DataFrame({"Subject": list(per), "Days of delay": list(per.values())}).set_index("Subject")


def summary(orig: List[Task], new: List[Task], cfg: Config) -> dict:
    moved = [t for t in new if t.shift > 0]
    return dict(days_before=len(overloaded_days(orig, cfg)), days_after=len(overloaded_days(new, cfg)),
                weeks_after=len(overloaded_weeks(new, cfg)), moved=len(moved),
                delay=sum(t.shift for t in moved),
                before=overload_score(orig, cfg), after=overload_score(new, cfg))


def chart_png(orig, new, cfg) -> bytes:
    fig = make_chart(orig, new, cfg)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    return buf.getvalue()


def report_pdf(orig, new, cfg) -> bytes:
    """A simple 2+ page PDF: summary + changes table, then the workload chart."""
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure
    s, ch = summary(orig, new, cfg), changes_df(new)
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        per_page = 22
        chunks = [ch.iloc[i:i + per_page] for i in range(0, max(len(ch), 1), per_page)]
        for n, chunk in enumerate(chunks):
            fig = Figure(figsize=(8.27, 11.69))
            ax = fig.add_axes([0.06, 0.04, 0.88, 0.9])
            ax.axis("off")
            if n == 0:
                ax.text(0, 1.0, "Deadline Balancer report", fontsize=18, weight="bold", va="top")
                lines = [f"Prepared on {cfg.today:%d %b %Y}",
                         f"Overloaded days: {s['days_before']} before -> {s['days_after']} after",
                         f"Deadlines moved: {s['moved']}   |   Total delay: {s['delay']} day(s)",
                         f"Limits: {cfg.daily_cap:g} h/weekday, {cfg.weekend_cap:g} h/weekend day, "
                         f"{cfg.weekly_cap:g} h/week"]
                for i, ln in enumerate(lines):
                    ax.text(0, 0.95 - i * 0.025, ln, fontsize=10, va="top")
                top = 0.82
            else:
                top = 1.0
            ax.text(0, top, "Suggested deadline changes", fontsize=13, weight="bold", va="top")
            if chunk.empty:
                ax.text(0, top - 0.04, "No changes needed.", fontsize=10, va="top")
            else:
                cell = [[r["Subject"], r["Task"], f"{r['Original due date']:%a %d %b}",
                         f"{r['New due date']:%a %d %b}", f"+{r['Delay (days)']}"]
                        for _, r in chunk.iterrows()]
                tbl = ax.table(cellText=cell, colLabels=["Subject", "Task", "Was due", "Now due", "Delay"],
                               bbox=[0, max(top - 0.05 - 0.035 * (len(cell) + 1), 0.02), 1, 0.035 * (len(cell) + 1)],
                               colWidths=[0.25, 0.33, 0.16, 0.16, 0.10])
                tbl.auto_set_font_size(False)
                tbl.set_fontsize(8.5)
            pdf.savefig(fig)
        pdf.savefig(make_chart(orig, new, cfg))
    return buf.getvalue()
