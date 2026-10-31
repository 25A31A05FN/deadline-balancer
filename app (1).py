from datetime import date, timedelta

import pandas as pd
import streamlit as st

from app_logic import (PRESETS, chart_png, changes_df, df_to_tasks, fairness_df, parse_holidays,
                       report_pdf, sample_df, summary, weekly_df)
from deadline_balancer import Config, balance, make_chart
from extract import TYPES, read_tasks

st.set_page_config(page_title="Deadline Balancer", page_icon="📅", layout="wide")


def _start_balancing():
    st.session_state["run"] = True


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    st.caption("Tell us how much you can handle. We'll only move deadlines "
               "when your workload is too high.")

    level = st.radio(
        "How much work can you handle?",
        ["Light", "Normal", "Heavy", "Custom"], index=1, horizontal=True,
        help="Light ≈ 3 h a day, Normal ≈ 5 h a day, Heavy ≈ 7 h a day. "
             "Pick Custom to set your own numbers.")
    if level == "Custom":
        weekday = st.number_input("Hours you can study on a weekday", 1.0, 16.0, 5.0, 0.5)
        weekend = st.number_input("Hours you can study on a weekend day", 0.0, 16.0, 3.0, 0.5)
        weekly = st.number_input("Most hours in one week", 5.0, 100.0, 28.0, 1.0)
    else:
        weekday, weekend, weekly = PRESETS[level]
        st.caption(f"≈ {weekday:g} h on weekdays · {weekend:g} h on weekends · {weekly:g} h a week")

    st.divider()
    fair = st.toggle("Share delays fairly between subjects", value=True,
                     help="On: no single teacher's deadlines get pushed again and again. "
                          "Off: we just pick whatever needs the fewest total days of delay.")
    no_weekend = st.toggle("Never move a deadline onto a weekend", value=True)

    holidays_text = st.text_input(
        "Holidays or exam days (deadlines can't land here)",
        placeholder="e.g. 2026-11-01, 2026-11-14",
        help="Type dates as YYYY-MM-DD, separated by commas.")
    blackout, bad = parse_holidays(holidays_text)
    if bad:
        st.warning("Couldn't read: " + ", ".join(bad) + ". Use the form 2026-11-14.")

    with st.expander("More options"):
        today = st.date_input("Today's date", value=date.today(),
                              help="Only tasks due today or later are used.")
        cap_on = st.toggle("Set a last allowed date", value=False,
                           help="No deadline will be pushed past this date (for example, end of term).")
        horizon = st.date_input("Last allowed date", value=today + timedelta(30)) if cap_on else None

cfg = Config(today, weekday, weekend, weekly, 0.5 if fair else 0.0, no_weekend, blackout, horizon)

# ------------------------------------------------------------------ header
left, right = st.columns([3, 1], vertical_alignment="center")
with left:
    st.title("📅 Deadline Balancer")
    st.caption("Add your tasks, press the button, and get the smallest deadline changes "
               "that keep your workload fair.")
with right:
    st.button("⚖️ Balance my deadlines", type="primary", width="stretch",
              on_click=_start_balancing, key="balance_btn")

# ------------------------------------------------------------------ step 1: tasks
st.subheader("1 · Your tasks")
st.session_state.setdefault("tasks", sample_df(today))
st.session_state.setdefault("editor_v", 0)
st.session_state.setdefault("seen_file", None)

up = st.file_uploader(
    "Upload your task list — CSV, PNG/JPG screenshot, or PDF",
    type=["csv", "png", "jpg", "jpeg", "pdf"],
    help="A table with a due-date column works best. Screenshots and scanned PDFs are read "
         "automatically, but please double-check the result.")
if up is not None and st.session_state["seen_file"] != up.file_id:
    st.session_state["seen_file"] = up.file_id
    try:
        with st.spinner("Reading your file…"):
            df, notes = read_tasks(up.getvalue(), up.name, today)
        st.session_state["tasks"] = df
        st.session_state["editor_v"] += 1
        st.session_state["notes"] = (f"Found {len(df)} task(s) in {up.name}.", notes)
    except ValueError as e:
        st.session_state["notes"] = None
        st.error(str(e))

if st.session_state.get("notes"):
    head, notes = st.session_state["notes"]
    st.success(head + " Check the table below, fix anything that looks wrong, then press "
               "**Balance my deadlines**.")
    for n in notes:
        st.warning(n)

c1, c2 = st.columns([1, 4])
if c1.button("Use sample tasks", help="Replace the table with example tasks"):
    st.session_state["tasks"] = sample_df(today)
    st.session_state["editor_v"] += 1
    st.session_state["notes"] = None
    st.rerun()
c2.caption("Double-click a cell to edit. Use the ＋ row at the bottom to add a task. "
           "Quizzes and exams never move.")

edited = st.data_editor(
    st.session_state["tasks"],
    key=f"editor_{st.session_state['editor_v']}",
    num_rows="dynamic",
    width="stretch",
    hide_index=True,
    column_order=["subject", "title", "type", "effort_hours", "deadline", "fixed", "start", "max_shift_days"],
    column_config={
        "subject": st.column_config.TextColumn("Subject"),
        "title": st.column_config.TextColumn("Task"),
        "type": st.column_config.SelectboxColumn("Type", options=TYPES, default="assignment"),
        "effort_hours": st.column_config.NumberColumn(
            "Hours of work", min_value=0.5, max_value=200.0, step=0.5, default=4.0,
            help="Your estimate of the total time this will take."),
        "deadline": st.column_config.DateColumn("Due date", format="DD MMM YYYY"),
        "fixed": st.column_config.CheckboxColumn(
            "Can't move", default=False, help="Tick if this deadline is not negotiable."),
        "start": st.column_config.DateColumn(
            "Start date", format="DD MMM YYYY", help="Optional. When you can begin; "
            "leave empty and we'll guess from the task type."),
        "max_shift_days": st.column_config.NumberColumn(
            "Max delay (days)", min_value=0, max_value=60, step=1,
            help="Optional. The most this deadline may be pushed back."),
    },
)

# ------------------------------------------------------------------ step 2: results
st.subheader("2 · Results")
if not st.session_state.get("run"):
    st.info("Press **⚖️ Balance my deadlines** (top right) when your tasks look right.")
    st.stop()

tasks, incomplete, past = df_to_tasks(edited, today)
if incomplete:
    st.warning(f"{incomplete} row(s) are missing a due date or hours and were skipped.")
if past:
    st.warning(f"{past} task(s) are already past due and were skipped.")
if not tasks:
    st.error("There are no usable tasks yet. Add at least one task with a due date and hours.")
    st.stop()

new = balance(tasks, cfg)
s = summary(tasks, new, cfg)

m1, m2, m3 = st.columns(3)
m1.metric("Hours over your limit", f"{s['after']:.0f} h", delta=f"{s['after'] - s['before']:.0f} h",
          delta_color="inverse",
          help=f"Extra hours you'd have to work above your daily and weekly limits. "
               f"{s['before']:.0f} h before balancing. Lower is better.")
m2.metric("Deadlines moved", s["moved"])
m3.metric("Total delay", f"{s['delay']} days")

if s["days_before"] == 0 and s["weeks_after"] == 0:
    st.success("Your workload is already within your limits — no changes needed. 🎉")
elif s["days_after"] == 0 and s["weeks_after"] == 0:
    st.success("Done. Every day and week is now within your limits.")
else:
    st.warning(
        "We improved things as far as the rules allow, but some days are still too heavy. "
        "Try raising **Max delay** on a task, choosing a heavier workload level, or removing "
        "the last-allowed-date limit.")

tab1, tab2, tab3, tab4 = st.tabs(["Suggested changes", "Daily workload", "Weekly view", "Fairness"])
with tab1:
    ch = changes_df(new)
    if ch.empty:
        st.write("No deadlines need to move.")
    else:
        st.dataframe(ch, hide_index=True, width="stretch", column_config={
            "Original due date": st.column_config.DateColumn(format="ddd DD MMM"),
            "New due date": st.column_config.DateColumn(format="ddd DD MMM"),
        })
with tab2:
    st.pyplot(make_chart(tasks, new, cfg))
    st.caption("Bars above the dashed line are days that are too heavy.")
with tab3:
    st.dataframe(weekly_df(tasks, new, cfg), hide_index=True, width="stretch")
with tab4:
    st.caption("Days of delay given to each subject.")
    st.bar_chart(fairness_df(new))

st.subheader("Download")
out = pd.DataFrame([dict(subject=t.subject, task=t.title, type=t.kind, hours=t.effort,
                         original_due=t.original_deadline, new_due=t.deadline, delay_days=t.shift)
                    for t in new])
d1, d2, d3 = st.columns(3)
d1.download_button("⬇️ Table (CSV)", out.to_csv(index=False).encode(), "balanced_deadlines.csv",
                   "text/csv", width="stretch")
d2.download_button("⬇️ Chart (PNG)", chart_png(tasks, new, cfg), "workload.png", "image/png",
                   width="stretch")
d3.download_button("⬇️ Report (PDF)", report_pdf(tasks, new, cfg), "deadline_report.pdf",
                   "application/pdf", width="stretch")
