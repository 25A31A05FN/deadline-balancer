"""Extra study-planning features for Deadline Balancer.

These helpers are deliberately dependency-light and work with the existing
Task/Config model. Timetable suggestions are estimates, not calendar bookings.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from email.utils import format_datetime
from typing import Iterable
import uuid

import pandas as pd

PRIORITY_VALUES = ["Low", "Medium", "High", "Urgent"]


def priority_score(row: dict, today: date) -> float:
    """Transparent heuristic score: urgency + user priority + exam/task type."""
    due = row.get("deadline")
    if pd.isna(due) or due is None:
        return 0.0
    due = pd.Timestamp(due).date()
    days_left = max((due - today).days, 0)
    priority = str(row.get("priority", "Medium")).title()
    priority_points = {"Low": 0, "Medium": 2, "High": 4, "Urgent": 6}.get(priority, 2)
    kind = str(row.get("type", "assignment")).lower()
    kind_points = 3 if kind == "exam" else 2 if kind == "quiz" else 0
    hours = pd.to_numeric(row.get("effort_hours", 0), errors="coerce")
    hours = 0 if pd.isna(hours) else float(hours)
    return priority_points + kind_points + max(0, 10 - days_left) * 1.5 + min(hours, 20) * 0.15


def add_priority_columns(df: pd.DataFrame, today: date) -> pd.DataFrame:
    out = df.copy()
    if "priority" not in out:
        out["priority"] = "Medium"
    if "completed_hours" not in out:
        out["completed_hours"] = 0.0
    if "status" not in out:
        out["status"] = "Not started"
    out["priority"] = out["priority"].fillna("Medium").map(
        lambda x: x.title() if str(x).title() in PRIORITY_VALUES else "Medium")
    out["completed_hours"] = pd.to_numeric(out["completed_hours"], errors="coerce").fillna(0).clip(lower=0)
    if "effort_hours" in out:
        effort = pd.to_numeric(out["effort_hours"], errors="coerce").fillna(0)
        out["completed_hours"] = out[["completed_hours"]].assign(
            _cap=out["completed_hours"].clip(upper=effort))["_cap"]
    out["status"] = out["status"].fillna("Not started")
    completed_mask = out["status"].astype(str).str.lower().eq("completed")
    out.loc[completed_mask, "completed_hours"] = pd.to_numeric(
        out.loc[completed_mask, "effort_hours"], errors="coerce").fillna(0)
    fully_done = out["completed_hours"] >= pd.to_numeric(out["effort_hours"], errors="coerce").fillna(0)
    out.loc[fully_done, "status"] = "Completed"
    in_progress = (out["completed_hours"] > 0) & ~fully_done
    out.loc[in_progress & out["status"].eq("Not started"), "status"] = "In progress"
    out["priority_score"] = out.apply(lambda r: priority_score(r.to_dict(), today), axis=1)
    return out


def progress_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"total": 0, "done": 0, "percent": 0.0, "planned": 0.0, "completed": 0.0}
    effort = pd.to_numeric(df.get("effort_hours", 0), errors="coerce")
    done = pd.to_numeric(df.get("completed_hours", 0), errors="coerce")
    planned = float(effort.fillna(0).sum()) if hasattr(effort, "fillna") else 0.0
    completed = float(done.fillna(0).sum()) if hasattr(done, "fillna") else 0.0
    done_count = int((df.get("status", pd.Series(index=df.index, dtype=str)) == "Completed").sum())
    return {"total": len(df), "done": done_count,
            "percent": round(100 * completed / planned, 1) if planned else 0.0,
            "planned": planned, "completed": completed}


def deadline_alerts(df: pd.DataFrame, today: date, days: int = 7) -> pd.DataFrame:
    if df.empty or "deadline" not in df:
        return pd.DataFrame(columns=["Subject", "Task", "Due date", "Days left", "Priority"])
    x = df.copy()
    x["deadline"] = pd.to_datetime(x["deadline"], errors="coerce").dt.date
    x = x[x["deadline"].notna() & (x["deadline"] >= today) &
          (x["deadline"] <= today + timedelta(days=days))]
    if "status" in x:
        x = x[x["status"] != "Completed"]
    x["Days left"] = x["deadline"].map(lambda d: (d - today).days)
    x["Due date"] = x["deadline"]
    x["Subject"] = x.get("subject", "General")
    x["Task"] = x.get("title", "Task")
    x["Priority"] = x.get("priority", "Medium")
    return x[["Subject", "Task", "Due date", "Days left", "Priority"]].sort_values("Days left")


def build_timetable(df: pd.DataFrame, today: date, daily_cap: float,
                    weekend_cap: float, horizon_days: int = 21) -> pd.DataFrame:
    """Greedy day-by-day study plan, assigning high urgency/high priority first."""
    cols = ["Date", "Day", "Subject", "Task", "Planned hours", "Priority"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    work = df.copy()
    work["deadline"] = pd.to_datetime(work["deadline"], errors="coerce").dt.date
    work["effort_hours"] = pd.to_numeric(work["effort_hours"], errors="coerce").fillna(0)
    work["completed_hours"] = pd.to_numeric(work.get("completed_hours", 0), errors="coerce").fillna(0)
    work["remaining"] = (work["effort_hours"] - work["completed_hours"]).clip(lower=0)
    work = work[(work["remaining"] > 0) & work["deadline"].notna() & (work["deadline"] >= today)]
    work["priority_score"] = work.apply(lambda r: priority_score(r.to_dict(), today), axis=1)
    work = work.sort_values(["priority_score", "deadline"], ascending=[False, True])
    rows = []
    for offset in range(max(1, horizon_days)):
        day = today + timedelta(days=offset)
        capacity = weekend_cap if day.weekday() >= 5 else daily_cap
        left = float(capacity)
        candidates = work[work["remaining"] > 0].sort_values(
            ["priority_score", "deadline"], ascending=[False, True])
        for idx, task in candidates.iterrows():
            if day > task["deadline"] or left <= 0:
                continue
            start = task.get("start")
            if pd.notna(start):
                start_date = pd.Timestamp(start).date()
                if day < start_date:
                    continue
            amount = min(float(work.at[idx, "remaining"]), left, 2.0)
            if amount <= 0:
                continue
            rows.append({"Date": day, "Day": day.strftime("%A"),
                         "Subject": task.get("subject", "General"),
                         "Task": task.get("title", "Task"),
                         "Planned hours": round(amount, 2),
                         "Priority": task.get("priority", "Medium")})
            work.at[idx, "remaining"] -= amount
            left -= amount
    return pd.DataFrame(rows, columns=cols)


def exam_preparation_plan(subject: str, exam_date: date, hours_per_day: float,
                          today: date, topics: Iterable[str]) -> pd.DataFrame:
    """Create a simple topic/revision plan with spaced review before an exam."""
    topics = [str(t).strip() for t in topics if str(t).strip()]
    if not topics:
        topics = ["Syllabus review"]
    days = max((exam_date - today).days, 1)
    rows = []
    slots = []
    for i, topic in enumerate(topics):
        slots.append((today + timedelta(days=min(i, days - 1)), topic, "Learn / practice"))
        review1 = exam_date - timedelta(days=2)
        review2 = exam_date - timedelta(days=1)
        if review1 >= today:
            slots.append((review1, topic, "Revision"))
        if review2 >= today:
            slots.append((review2, topic, "Quick recall"))
    per_slot = max(0.5, float(hours_per_day))
    for d, topic, activity in sorted(slots, key=lambda x: (x[0], x[1])):
        if d <= exam_date:
            rows.append({"Date": d, "Subject": subject, "Topic": topic,
                         "Activity": activity, "Suggested hours": per_slot})
    return pd.DataFrame(rows)


def study_recommendations(df: pd.DataFrame, today: date) -> list[str]:
    tips = []
    if df.empty:
        return ["Add a few tasks to receive personalized study suggestions."]
    alerts = deadline_alerts(df, today, 3)
    if not alerts.empty:
        tips.append(f"Start with {len(alerts)} task(s) due in the next 3 days; schedule a focused session today.")
    total = pd.to_numeric(df.get("effort_hours", 0), errors="coerce").fillna(0).sum()
    done = pd.to_numeric(df.get("completed_hours", 0), errors="coerce").fillna(0).sum()
    if total and done / total < 0.25:
        tips.append("Your recorded progress is below 25%. Try two 25-minute focus sessions and update completed hours.")
    high = df[df.get("priority", pd.Series("Medium", index=df.index)).isin(["High", "Urgent"])]
    if len(high):
        tips.append(f"You have {len(high)} high/urgent priority task(s). Work on the nearest deadline first.")
    if total > 0 and total - done > 20:
        tips.append("There is more than 20 hours of work remaining. Split large tasks into smaller milestones.")
    if not tips:
        tips.append("Your workload looks manageable. Keep a short daily review and reserve time for revision.")
    tips.append("Take a 5–10 minute break after each 45–50 minute focused study block.")
    return tips


def make_ics(df: pd.DataFrame) -> str:
    """Export timetable rows as an iCalendar file (local floating times)."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Deadline Balancer//Study Plan//EN", "CALSCALE:GREGORIAN"]
    cursor_by_day = {}
    for row in df.to_dict("records"):
        d = pd.Timestamp(row["Date"]).date()
        start_hour = cursor_by_day.get(d, 9.0)
        duration = float(row["Planned hours"])
        start_dt = datetime.combine(d, time(int(start_hour), int((start_hour % 1) * 60)))
        end_hour = start_hour + duration
        end_dt = datetime.combine(d, time(int(end_hour) % 24, int((end_hour % 1) * 60)))
        cursor_by_day[d] = min(end_hour + 0.25, 20.0)
        uid = uuid.uuid4().hex
        title = f"Study: {row['Subject']} - {row['Task']}".replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")
        lines.extend(["BEGIN:VEVENT", f"UID:{uid}@deadline-balancer", f"DTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}",
                      f"DTSTART:{start_dt:%Y%m%dT%H%M%S}", f"DTEND:{end_dt:%Y%m%dT%H%M%S}",
                      f"SUMMARY:{title}", f"DESCRIPTION:Suggested study session ({duration:g} hours)", "END:VEVENT"])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
