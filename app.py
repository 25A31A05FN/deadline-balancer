"""Streamlit front-end for the Academic Deadline Balancer.

Run locally:  streamlit run app.py
"""
import io
import os
import tempfile
from collections import defaultdict
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from deadline_balancer import (Config, balance, daily_load, load_tasks,
                               overload_score, overloaded_days,
                               overloaded_weeks, report, weekly_load)

COLUMNS = ["id", "subject", "title", "type", "effort_hours", "deadline",
           "start", "fixed", "max_shift_days"]
TYPES = ["assignment", "project", "tutorial", "lab", "quiz", "exam"]

st.set_page_config(page_title="Deadline Balancer", page_icon="📅", layout="wide")
st.title("📅 Academic Deadline Balancer")
st.caption("Find overloaded days and weeks, then get the smallest deadline "
           "extensions that remove them.")


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    today = st.date_input("Today", value=date.today())
    daily_cap = st.slider("Hours per weekday", 1.0, 12.0, 5.0, 0.5)
    weekend_cap = st.slider("Hours per weekend day", 0.0, 12.0, 3.0, 0.5)
    weekly_cap = st.slider("Hours per week", 5.0, 80.0, 28.0, 1.0)
    fairness = st.slider("Fairness (spread extensions across subjects)",
                         0.0, 2.0, 0.5, 0.1)
    no_weekend = st.checkbox("No deadlines on weekends", value=True)
    use_horizon = st.checkbox("Limit how far deadlines can move")
    horizon = (st.date_input("Semester / horizon end", value=today + timedelta(days=30))
               if use_horizon else None)
    holiday_text = st.text_input("Holidays (YYYY-MM-DD, comma-separated)",
                                 help="Deadlines can't be moved onto these dates.")
    blackout = []
    for part in holiday_text.replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                blackout.append(date.fromisoformat(part))
            except ValueError:
                st.sidebar.error(f"Ignored invalid date: {part}")


# ---------------------------------------------------------------- input
def load_default() -> pd.DataFrame:
    path = os.path.join(os.path.dirname(__file__), "sample_tasks.csv")
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=COLUMNS)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNS].copy()
    df["deadline"] = pd.to_datetime(df["deadline"], errors="coerce").dt.date
    df["start"] = pd.to_datetime(df["start"], errors="coerce").dt.date
    df["fixed"] = df["fixed"].map(lambda v: str(v).strip().lower() in {"1", "true", "yes", "y", "1.0"})
    df["effort_hours"] = pd.to_numeric(df["effort_hours"], errors="coerce")
    df["max_shift_days"] = pd.to_numeric(df["max_shift_days"], errors="coerce")
    return df


st.subheader("1. Your tasks")
up = st.file_uploader("Upload a CSV (or edit the sample below)", type="csv")
base = pd.read_csv(up) if up else load_default()
data = st.data_editor(
    clean(base), num_rows="dynamic", use_container_width=True, hide_index=True,
    column_config={
        "type": st.column_config.SelectboxColumn(options=TYPES, required=True),
        "effort_hours": st.column_config.NumberColumn("effort_hours", min_value=0.5, step=0.5),
        "deadline": st.column_config.DateColumn("deadline", format="YYYY-MM-DD"),
        "start": st.column_config.DateColumn("start (optional)", format="YYYY-MM-DD"),
        "fixed": st.column_config.CheckboxColumn("fixed (can't move)"),
        "max_shift_days": st.column_config.NumberColumn("max_shift_days", min_value=0, step=1),
    },
)


def to_csv_text(df: pd.DataFrame) -> str:
    out = df.dropna(subset=["id", "subject", "type", "effort_hours", "deadline"]).copy()
    out["fixed"] = out["fixed"].map(lambda v: "1" if v else "")
    out["max_shift_days"] = out["max_shift_days"].map(lambda v: "" if pd.isna(v) else int(v))
    for c in ("start", "deadline"):
        out[c] = out[c].map(lambda v: "" if pd.isna(v) else v.isoformat())
    out["title"] = out["title"].fillna("")
    buf = io.StringIO()
    out.to_csv(buf, index=False)
    return buf.getvalue()


# ---------------------------------------------------------------- run
def make_chart(orig, new, cfg):
    b, a = daily_load(orig), daily_load(new)
    days = sorted(set(b) | set(a))
    x = list(range(len(days)))
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.bar([i - 0.2 for i in x], [b.get(d, 0) for d in days], 0.4, label="before", color="#d9534f")
    ax.bar([i + 0.2 for i in x], [a.get(d, 0) for d in days], 0.4, label="after", color="#4a90d9")
    ax.step(x, [cfg.cap(d) for d in days], where="mid", color="black", ls="--", label="daily capacity")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{d:%d %b}\n{d:%a}" for d in days], fontsize=7)
    ax.set_ylabel("hours of work")
    ax.legend()
    fig.tight_layout()
    return fig


st.subheader("2. Balance")
if st.button("Balance my deadlines", type="primary"):
    csv_text = to_csv_text(data)
    if csv_text.count("\n") < 2:
        st.error("Add at least one complete task (id, subject, type, effort, deadline).")
        st.stop()

    cfg = Config(today, daily_cap, weekend_cap, weekly_cap, fairness,
                 no_weekend, set(blackout), horizon)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_text)
        tmp = f.name
    try:
        tasks = load_tasks(tmp, today)
    except SystemExit as e:
        st.error(f"Could not read tasks: {e}")
        st.stop()
    finally:
        os.unlink(tmp)

    new = balance(tasks, cfg)
    before, after = overload_score(tasks, cfg), overload_score(new, cfg)
    moved = [t for t in new if t.shift > 0]

    c1, c2, c3 = st.columns(3)
    c1.metric("Overload score", f"{after:.1f}", f"{after - before:+.1f}", delta_color="inverse")
    c2.metric("Deadlines moved", len(moved))
    c3.metric("Total extension (days)", sum(t.shift for t in moved))

    if after <= 1e-9:
        st.success("All days and weeks are within capacity.")
    else:
        st.warning("Still overloaded after all allowed adjustments. Raise max_shift_days, "
                   "relax the caps, or consider moving a fixed quiz/exam.")

    st.pyplot(make_chart(tasks, new, cfg))

    st.markdown("#### Suggested deadline changes")
    if moved:
        st.dataframe(pd.DataFrame([{
            "Subject": t.subject, "Task": t.title,
            "Original": t.original_deadline.strftime("%a %d %b"),
            "Suggested": t.deadline.strftime("%a %d %b"),
            "Extra days": t.shift} for t in sorted(moved, key=lambda x: x.original_deadline)]),
            hide_index=True, use_container_width=True)
    else:
        st.info("No changes needed." if not overloaded_days(tasks, cfg)
                else "No legal adjustment could help.")

    per = defaultdict(int)
    for t in new:
        per[t.subject] += t.shift
    st.markdown("#### Fairness: extension days per subject")
    st.bar_chart(pd.Series(per, name="days"))

    with st.expander("Full text report"):
        st.code(report(tasks, new, cfg))

    out = pd.DataFrame([{
        "id": t.id, "subject": t.subject, "title": t.title, "type": t.kind,
        "effort_hours": t.effort, "original_deadline": t.original_deadline,
        "suggested_deadline": t.deadline, "shift_days": t.shift} for t in new])
    st.download_button("Download balanced_deadlines.csv", out.to_csv(index=False),
                       "balanced_deadlines.csv", "text/csv")
