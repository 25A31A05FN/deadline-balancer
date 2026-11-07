
from datetime import date, timedelta
import pandas as pd
import streamlit as st

from app_logic import (
    PRESETS, chart_png, changes_df, df_to_tasks, fairness_df,
    parse_holidays, report_pdf, sample_df, summary, weekly_df
)
from deadline_balancer import Config, balance, make_chart
from extract import COLUMNS, TYPES, read_tasks
from study_features import (
    PRIORITY_VALUES, add_priority_columns, build_timetable,
    deadline_alerts, exam_preparation_plan, make_ics,
    progress_summary, study_recommendations
)
from assignment_tracker import (
    load_assignments, save_assignment, delete_assignment, replace_all
)

st.set_page_config(
    page_title="Deadline Balancer",
    page_icon="📅",
    layout="wide"
)

st.markdown("""
<style>
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}
[data-testid="stSidebar"] {
    border-right: 1px solid rgba(128,128,128,.18);
}
.db-hero {
    padding: 1.1rem 1.35rem;
    border-radius: 16px;
    background: linear-gradient(110deg,#1d4ed8,#2563eb);
    color: white;
    margin-bottom: 1rem;
}
.db-hero h1 {
    color: white;
    margin: 0;
}
.db-muted {
    color: rgba(255,255,255,.85);
}
</style>
""", unsafe_allow_html=True)

TODAY = date.today()

st.session_state.setdefault(
    "tasks",
    add_priority_columns(sample_df(TODAY), TODAY)
)
st.session_state.setdefault("run", False)
st.session_state.setdefault("balanced_result", None)
st.session_state.setdefault("page", "Overview")

PAGES = [
    "Overview",
    "My Tasks",
    "Deadline Balancer",
    "Study Planner",
    "Exam Preparation",
    "Assignment Tracker",
    "Progress & Analytics",
    "Settings"
]

# SIDEBAR NAVIGATION
with st.sidebar:
    st.markdown("## 📅 Deadline Balancer")

    page = st.radio(
        "WORKSPACE",
        PAGES,
        key="page",
        label_visibility="collapsed"
    )

    st.divider()
    st.caption("B.Tech Student Workspace")
    st.caption("Organize • Plan • Submit • Track")


# SHARED SETTINGS
if "daily_cap" not in st.session_state:
    (
        st.session_state.daily_cap,
        st.session_state.weekend_cap,
        st.session_state.weekly_cap
    ) = PRESETS["Normal"]

if "fairness" not in st.session_state:
    st.session_state.fairness = True

if "no_weekend" not in st.session_state:
    st.session_state.no_weekend = True

if "holidays" not in st.session_state:
    st.session_state.holidays = ""

if "horizon_on" not in st.session_state:
    st.session_state.horizon_on = False

if "horizon_end" not in st.session_state:
    st.session_state.horizon_end = TODAY + timedelta(days=30)


st.markdown("""
<div class="db-hero">
    <h1>📅 Deadline Balancer</h1>
    <div class="db-muted">
        Your academic command centre — tasks, deadlines,
        assignments and study progress.
    </div>
</div>
""", unsafe_allow_html=True)


# ==========================================================
# 1. OVERVIEW
# ==========================================================

if page == "Overview":

    st.title("Overview")
    st.caption(
        "A quick look at your semester workload and submission progress."
    )

    tasks_df = add_priority_columns(st.session_state.tasks, TODAY)
    p = progress_summary(tasks_df)

    a = load_assignments()

    total_req = len(a)

    submitted = (
        int((a.status == "Submitted").sum())
        if total_req else 0
    )

    pending = (
        int((a.status == "Pending").sum())
        if total_req else 0
    )

    late = (
        int((a.status == "Late").sum())
        if total_req else 0
    )

    c = st.columns(4)

    c[0].metric("Academic tasks", len(tasks_df))
    c[1].metric("Study progress", f"{p['percent']:.0f}%")
    c[2].metric(
        "Assignments submitted",
        f"{submitted}/{total_req}"
    )
    c[3].metric("Pending submissions", pending + late)

    st.progress(min(p["percent"] / 100, 1.0))

    st.subheader("Upcoming deadlines")

    upcoming = deadline_alerts(tasks_df, TODAY, 7)

    if upcoming.empty:
        st.success("No task deadlines in the next 7 days.")
    else:
        st.dataframe(
            upcoming,
            use_container_width=True,
            hide_index=True
        )

    st.caption(
        "Use the left sidebar to open My Tasks, Deadline Balancer, "
        "Study Planner, Exam Preparation, Assignment Tracker, "
        "Analytics or Settings."
    )


# ==========================================================
# 2. MY TASKS
# ==========================================================

elif page == "My Tasks":

    st.title("📚 My Tasks")

    st.caption(
        "Add, import and manage assignments, quizzes, labs, "
        "projects and other academic work."
    )

    with st.expander("Add a task manually", expanded=True):

        with st.form("add_task_form", clear_on_submit=True):

            x1, x2, x3 = st.columns(3)

            subject = x1.text_input("Subject")
            title = x2.text_input("Task title")
            kind = x3.selectbox("Type", TYPES)

            x4, x5, x6 = st.columns(3)

            hours = x4.number_input(
                "Estimated hours", 0.5, 200.0, 4.0, 0.5
            )

            due = x5.date_input(
                "Due date",
                TODAY + timedelta(days=7)
            )

            priority = x6.selectbox(
                "Priority",
                PRIORITY_VALUES,
                index=1
            )

            fixed = st.checkbox(
                "Deadline cannot move",
                value=kind in ("quiz", "exam")
            )

            if st.form_submit_button("Add task", type="primary"):

                if not title.strip():
                    st.error("Enter a task title.")

                else:
                    row = {
                        "subject": subject.strip() or "General",
                        "title": title.strip(),
                        "type": kind,
                        "effort_hours": hours,
                        "deadline": due,
                        "start": None,
                        "fixed": fixed,
                        "max_shift_days": None,
                        "priority": priority,
                        "completed_hours": 0.0,
                        "status": "Not started"
                    }

                    st.session_state.tasks = pd.concat(
                        [
                            st.session_state.tasks,
                            pd.DataFrame([row])
                        ],
                        ignore_index=True
                    )

                    st.success("Task added.")

    uploaded = st.file_uploader(
        "Import tasks (CSV, DOCX, PDF, PNG/JPG/WEBP, TXT/MD)",
        type=[
            "csv", "docx", "pdf", "png",
            "jpg", "jpeg", "webp", "txt", "md"
        ],
        key="task_upload"
    )

    if uploaded and st.button("Import uploaded file"):

        try:
            df, notes = read_tasks(
                uploaded.getvalue(),
                uploaded.name,
                TODAY
            )

            st.session_state.tasks = add_priority_columns(
                df, TODAY
            )

            st.success(
                f"Imported {len(df)} tasks. Review the table below."
            )

            for note in notes:
                st.info(note)

        except Exception as e:
            st.error(str(e))

    st.subheader("Your task list")

    tasks = add_priority_columns(
        st.session_state.tasks,
        TODAY
    )

    edited = st.data_editor(
        tasks,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "type": st.column_config.SelectboxColumn(
                options=TYPES
            ),
            "priority": st.column_config.SelectboxColumn(
                options=PRIORITY_VALUES
            ),
            "status": st.column_config.SelectboxColumn(
                options=[
                    "Not started",
                    "In progress",
                    "Completed"
                ]
            ),
            "deadline": st.column_config.DateColumn(
                format="DD MMM YYYY"
            )
        },
        key="tasks_editor"
    )

    st.session_state.tasks = edited

    st.download_button(
        "Download task list CSV",
        edited.to_csv(index=False).encode(),
        "my_tasks.csv",
        "text/csv"
    )


# ==========================================================
# 3. SETTINGS
# ==========================================================

elif page == "Settings":

    st.title("⚙️ Study & balancing settings")

    st.caption(
        "Configure your available study hours and deadline restrictions here."
    )

    level = st.radio(
        "Workload preset",
        ["Light", "Normal", "Heavy", "Custom"],
        index=1,
        horizontal=True
    )

    if level == "Custom":

        st.session_state.daily_cap = st.number_input(
            "Weekday hours",
            1.0, 16.0,
            float(st.session_state.daily_cap),
            0.5
        )

        st.session_state.weekend_cap = st.number_input(
            "Weekend hours",
            0.0, 16.0,
            float(st.session_state.weekend_cap),
            0.5
        )

        st.session_state.weekly_cap = st.number_input(
            "Weekly hours",
            5.0, 100.0,
            float(st.session_state.weekly_cap),
            1.0
        )

    else:

        (
            st.session_state.daily_cap,
            st.session_state.weekend_cap,
            st.session_state.weekly_cap
        ) = PRESETS[level]

        st.info(
            f"{st.session_state.daily_cap:g} h weekdays · "
            f"{st.session_state.weekend_cap:g} h weekends · "
            f"{st.session_state.weekly_cap:g} h/week"
        )

    st.session_state.fairness = st.toggle(
        "Share deadline delays fairly between subjects",
        st.session_state.fairness
    )

    st.session_state.no_weekend = st.toggle(
        "Never move deadlines onto weekends",
        st.session_state.no_weekend
    )

    st.session_state.holidays = st.text_input(
        "Holidays / exam days (YYYY-MM-DD, comma separated)",
        st.session_state.holidays
    )

    st.session_state.horizon_on = st.toggle(
        "Set last allowed deadline date",
        st.session_state.horizon_on
    )

    if st.session_state.horizon_on:

        st.session_state.horizon_end = st.date_input(
            "Last allowed date",
            st.session_state.horizon_end
        )


# ==========================================================
# 4. DEADLINE BALANCER
# ==========================================================

elif page == "Deadline Balancer":

    st.title("⚖️ Deadline Balancer")

    st.caption(
        "The original greedy + prune balancing algorithm is retained."
    )

    blackout, bad = parse_holidays(
        st.session_state.holidays
    )

    if bad:
        st.warning(
            "Unrecognized dates: " + ", ".join(bad)
        )

    cfg = Config(
        TODAY,
        st.session_state.daily_cap,
        st.session_state.weekend_cap,
        st.session_state.weekly_cap,
        0.5 if st.session_state.fairness else 0.0,
        st.session_state.no_weekend,
        blackout,
        st.session_state.horizon_end
        if st.session_state.horizon_on else None
    )

    st.write(
        f"Capacity: **{cfg.daily_cap:g} h/day**, "
        f"**{cfg.weekend_cap:g} h/weekend**, "
        f"**{cfg.weekly_cap:g} h/week**"
    )

    st.dataframe(
        st.session_state.tasks[
            [
                "subject", "title", "type",
                "effort_hours", "deadline", "fixed"
            ]
        ],
        use_container_width=True,
        hide_index=True
    )

    if st.button(
        "⚖️ Balance my deadlines",
        type="primary"
    ):

        task_list, incomplete, past = df_to_tasks(
            st.session_state.tasks,
            TODAY
        )

        if not task_list:
            st.error(
                "Add tasks with future due dates and effort hours first."
            )

        else:

            result = balance(task_list, cfg)

            st.session_state.balanced_result = (
                task_list, result, cfg
            )

            st.success(
                f"Balancing complete. {incomplete} incomplete "
                f"and {past} past-due rows skipped."
            )

    if st.session_state.balanced_result:

        orig, new, cfg = st.session_state.balanced_result

        s = summary(orig, new, cfg)

        m = st.columns(3)

        m[0].metric(
            "Deadlines moved",
            s["moved"]
        )

        m[1].metric(
            "Total delay",
            f"{s['delay']} days"
        )

        m[2].metric(
            "Overload score",
            f"{s['after']:.1f}",
            delta=f"{s['after'] - s['before']:.1f}",
            delta_color="inverse"
        )

        st.subheader("Suggested changes")

        st.dataframe(
            changes_df(new),
            use_container_width=True,
            hide_index=True
        )

        t1, t2, t3 = st.tabs(
            ["Daily workload", "Weekly view", "Fairness"]
        )

        with t1:
            st.pyplot(make_chart(orig, new, cfg))

        with t2:
            st.dataframe(
                weekly_df(orig, new, cfg),
                use_container_width=True,
                hide_index=True
            )

        with t3:
            st.bar_chart(fairness_df(new))

        out = pd.DataFrame([
            {
                "Subject": t.subject,
                "Task": t.title,
                "Original due": t.original_deadline,
                "New due": t.deadline,
                "Delay days": t.shift
            }
            for t in new
        ])

        st.download_button(
            "Download balanced deadlines CSV",
            out.to_csv(index=False).encode(),
            "balanced_deadlines.csv",
            "text/csv"
        )

        st.download_button(
            "Download PDF report",
            report_pdf(orig, new, cfg),
            "deadline_report.pdf",
            "application/pdf"
        )


# ==========================================================
# 5. STUDY PLANNER
# ==========================================================

elif page == "Study Planner":

    st.title("🗓️ Study Planner")

    timetable = build_timetable(
        add_priority_columns(
            st.session_state.tasks,
            TODAY
        ),
        TODAY,
        st.session_state.daily_cap,
        st.session_state.weekend_cap,
        30
    )

    if timetable.empty:

        st.info(
            "Add tasks with future due dates and remaining hours "
            "to create your timetable."
        )

    else:

        st.dataframe(
            timetable,
            use_container_width=True,
            hide_index=True
        )

        st.download_button(
            "Download timetable CSV",
            timetable.to_csv(index=False).encode(),
            "study_timetable.csv",
            "text/csv"
        )

        st.download_button(
            "Add sessions to calendar (.ics)",
            make_ics(timetable).encode(),
            "study_timetable.ics",
            "text/calendar"
        )

    st.subheader("Study recommendations")

    for tip in study_recommendations(
        st.session_state.tasks,
        TODAY
    ):
        st.write("• " + tip)


# ==========================================================
# 6. EXAM PREPARATION
# ==========================================================

elif page == "Exam Preparation":

    st.title("🎓 Exam Preparation")

    with st.form("exam_plan_form"):

        subject = st.text_input("Subject")

        exam_date = st.date_input(
            "Exam date",
            TODAY + timedelta(days=14)
        )

        hours = st.number_input(
            "Study hours per day",
            0.5, 12.0, 2.0, 0.5
        )

        topics = st.text_area(
            "Syllabus topics (one topic per line)",
            placeholder="Unit 1 - Basics\nUnit 2 - Applications"
        )

        make = st.form_submit_button(
            "Generate revision plan",
            type="primary"
        )

    if make:

        if exam_date < TODAY:

            st.error("Exam date must be today or later.")

        else:

            plan = exam_preparation_plan(
                subject or "Exam",
                exam_date,
                hours,
                TODAY,
                [
                    x.strip()
                    for x in topics.splitlines()
                    if x.strip()
                ]
            )

            st.dataframe(
                plan,
                use_container_width=True,
                hide_index=True
            )

            st.download_button(
                "Download exam plan",
                plan.to_csv(index=False).encode(),
                "exam_plan.csv",
                "text/csv"
            )


# ==========================================================
# 7. B.TECH ASSIGNMENT TRACKER
# ==========================================================

elif page == "Assignment Tracker":

    st.title("📝 B.Tech Assignment Tracker")

    st.caption(
        "Record how many assignments each subject requires "
        "and confirm every submission."
    )

    data = load_assignments()

    total = len(data)

    submitted = (
        int((data.status == "Submitted").sum())
        if total else 0
    )

    pending = (
        int((data.status == "Pending").sum())
        if total else 0
    )

    late = (
        int((data.status == "Late").sum())
        if total else 0
    )

    c = st.columns(4)

    c[0].metric("Required entries", total)
    c[1].metric("Submitted", submitted)
    c[2].metric("Pending", pending)
    c[3].metric("Late", late)

    # ADD REQUIRED ASSIGNMENT
    with st.expander(
        "＋ Add required assignment",
        expanded=True
    ):

        with st.form(
            "assignment_add_form",
            clear_on_submit=True
        ):

            a1, a2, a3 = st.columns(3)

            semester = a1.selectbox(
                "Semester",
                [
                    "1-1", "1-2",
                    "2-1", "2-2",
                    "3-1", "3-2",
                    "4-1", "4-2"
                ]
            )

            subject = a2.text_input(
                "Subject name",
                placeholder="Mathematics-II"
            )

            number = a3.text_input(
                "Assignment number",
                placeholder="1 / 2 / 3"
            )

            a4, a5 = st.columns(2)

            title = a4.text_input(
                "Assignment title (optional)"
            )

            due = a5.date_input(
                "Due date",
                value=TODAY + timedelta(days=7)
            )

            if st.form_submit_button(
                "Add to required register",
                type="primary"
            ):

                if not subject.strip() or not number.strip():

                    st.error(
                        "Subject and assignment number are required."
                    )

                else:

                    try:

                        save_assignment({
                            "semester": semester,
                            "subject": subject.strip(),
                            "assignment_no": number.strip(),
                            "title": title.strip(),
                            "due_date": due.isoformat(),
                            "status": "Pending",
                            "submitted_date": "",
                            "confirmation_note": ""
                        })

                        st.success(
                            "Assignment added to your register."
                        )

                    except Exception as e:

                        st.error(
                            f"Could not save: {e}"
                        )

    # SUBMISSION CONFIRMATION TABLE
    st.subheader("Submission confirmation register")

    data = load_assignments()

    if data.empty:

        st.info(
            "No assignments yet. Add the assignments your faculty "
            "requires for each subject."
        )

    else:

        editable = data.drop(
            columns=["id"]
        ).copy()

        edited = st.data_editor(
            editable,
            use_container_width=True,
            hide_index=True,
            key="assignment_editor",
            column_config={
                "semester": st.column_config.SelectboxColumn(
                    options=[
                        "1-1", "1-2",
                        "2-1", "2-2",
                        "3-1", "3-2",
                        "4-1", "4-2"
                    ]
                ),

                "status": st.column_config.SelectboxColumn(
                    options=[
                        "Pending",
                        "Submitted",
                        "Late",
                        "Not required"
                    ]
                ),

                "due_date": st.column_config.TextColumn(
                    "Due date (YYYY-MM-DD)"
                ),

                "submitted_date": st.column_config.TextColumn(
                    "Submitted date (YYYY-MM-DD)"
                ),

                "confirmation_note": st.column_config.TextColumn(
                    "Receipt / confirmation note"
                )
            }
        )

        if st.button(
            "Save submission confirmations",
            type="primary"
        ):

            replace_all(edited)

            st.success(
                "Assignment register saved."
            )

            st.rerun()

        st.download_button(
            "Export assignment register CSV",
            data.to_csv(index=False).encode(),
            "btech_assignment_register.csv",
            "text/csv"
        )

        remove_id = st.selectbox(
            "Delete an assignment record",
            data.id.tolist(),
            format_func=lambda x: (
                f"Record {x}: "
                f"{data.loc[data.id == x, 'subject'].iloc[0]} "
                f"— Assignment "
                f"{data.loc[data.id == x, 'assignment_no'].iloc[0]}"
            )
        )

        if st.button("Delete selected record"):

            delete_assignment(remove_id)

            st.rerun()

    st.info(
        "Tip: enter the required assignment count given by your faculty. "
        "The tracker does not assume a universal B.Tech assignment count."
    )


# ==========================================================
# 8. PROGRESS & ANALYTICS
# ==========================================================

elif page == "Progress & Analytics":

    st.title("📊 Progress & Analytics")

    data = add_priority_columns(
        st.session_state.tasks,
        TODAY
    )

    p = progress_summary(data)

    c = st.columns(4)

    c[0].metric(
        "Total tasks",
        p["total"]
    )

    c[1].metric(
        "Completed tasks",
        p["done"]
    )

    c[2].metric(
        "Progress",
        f"{p['percent']:.1f}%"
    )

    c[3].metric(
        "Hours completed",
        f"{p['completed']:.1f}"
    )

    st.progress(
        min(p["percent"] / 100, 1.0)
    )

    if not data.empty:

        st.subheader("Tasks by subject")

        st.bar_chart(
            data.groupby("subject")["effort_hours"].sum()
        )

        st.subheader("Task status")

        st.bar_chart(
            data["status"].value_counts()
        )

    assignments = load_assignments()

    if not assignments.empty:

        st.subheader("Assignment submissions by status")

        st.bar_chart(
            assignments["status"].value_counts()
        )
