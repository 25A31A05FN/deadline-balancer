"""SQLite-backed B.Tech assignment submission register."""

import sqlite3
from pathlib import Path
import pandas as pd

DB_PATH = Path(__file__).with_name("assignment_tracker.db")


def connect():
    con = sqlite3.connect(DB_PATH)

    con.execute("""
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            subject TEXT NOT NULL,
            assignment_no TEXT NOT NULL,
            title TEXT DEFAULT '',
            due_date TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending',
            submitted_date TEXT DEFAULT '',
            confirmation_note TEXT DEFAULT '',
            UNIQUE(semester, subject, assignment_no)
        )
    """)

    con.commit()
    return con


def load_assignments():

    with connect() as con:

        return pd.read_sql_query(
            """
            SELECT *
            FROM assignments
            ORDER BY semester, subject, assignment_no
            """,
            con
        )


def save_assignment(row):

    with connect() as con:

        con.execute("""
            INSERT INTO assignments
            (
                semester,
                subject,
                assignment_no,
                title,
                due_date,
                status,
                submitted_date,
                confirmation_note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(semester, subject, assignment_no)
            DO UPDATE SET

                title=excluded.title,
                due_date=excluded.due_date,
                status=excluded.status,
                submitted_date=excluded.submitted_date,
                confirmation_note=excluded.confirmation_note
        """, (
            row["semester"],
            row["subject"],
            row["assignment_no"],
            row.get("title", ""),
            row.get("due_date", ""),
            row.get("status", "Pending"),
            row.get("submitted_date", ""),
            row.get("confirmation_note", "")
        ))

        con.commit()


def delete_assignment(record_id):

    with connect() as con:

        con.execute(
            "DELETE FROM assignments WHERE id=?",
            (int(record_id),)
        )

        con.commit()


def replace_all(df):

    required = [
        "semester",
        "subject",
        "assignment_no",
        "title",
        "due_date",
        "status",
        "submitted_date",
        "confirmation_note"
    ]

    clean = df.copy()

    for col in required:

        if col not in clean:
            clean[col] = ""

    with connect() as con:

        con.execute("DELETE FROM assignments")

        for _, r in clean.iterrows():

            con.execute("""
                INSERT INTO assignments
                (
                    semester,
                    subject,
                    assignment_no,
                    title,
                    due_date,
                    status,
                    submitted_date,
                    confirmation_note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)

                ON CONFLICT(semester, subject, assignment_no)
                DO UPDATE SET

                    title=excluded.title,
                    due_date=excluded.due_date,
                    status=excluded.status,
                    submitted_date=excluded.submitted_date,
                    confirmation_note=excluded.confirmation_note
            """, (
                str(r["semester"]),
                str(r["subject"]),
                str(r["assignment_no"]),
                str(r["title"]),
                str(r["due_date"]),
                str(r["status"]),
                str(r["submitted_date"]),
                str(r["confirmation_note"])
            ))

        con.commit()
