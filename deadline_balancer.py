#!/usr/bin/env python3
"""
Academic Deadline Balancer
==========================
Collects academic tasks (effort + deadline), models the daily/weekly workload,
detects overload and proposes the *minimum* deadline extensions that remove it.

Model
-----
* Every task has `effort_hours` of work that is spread evenly over the days
  from its start date to its deadline (inclusive).
  start = max(today, release date) - or, if no release date is given,
  max(today, deadline - lead_days + 1), where lead_days depends on task type.
* A student can do `daily_cap` hours on a weekday and `weekend_cap` on a
  weekend day; a week (Mon-Sun) may not exceed `weekly_cap` hours.
* Overload score = sum of daily excess hours + sum of weekly excess hours.

Balancing (greedy + prune)
--------------------------
1. Repeatedly try every legal deadline extension (1..max_shift days) of every
   movable task, and apply the one with the best
       overload reduction / (shift days * fairness penalty).
   The fairness penalty grows for subjects that were already shifted, so the
   burden is shared between teachers instead of landing on one subject.
2. Stop when there is no overload or no legal move helps any more.
3. Prune: try to pull every moved deadline back towards its original date
   while the overload score does not get worse -> minimal adjustments.

Constraints respected
---------------------
* Fixed tasks (quizzes, exams, or `fixed=1`) never move.
* Deadlines only move later, never past `max_shift_days` per task and never
  past the horizon (e.g. semester end).
* Deadlines never land on blackout dates (holidays) and, optionally, weekends.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Set

EPS = 1e-9

# Typical number of days a student starts working before the deadline.
LEAD_DAYS = {"assignment": 7, "project": 14, "tutorial": 4, "lab": 5,
             "quiz": 3, "exam": 10}
# Default flexibility (days a deadline may be extended).
DEFAULT_MAX_SHIFT = {"assignment": 5, "project": 7, "tutorial": 3, "lab": 3,
                     "quiz": 0, "exam": 0}
FIXED_TYPES = {"quiz", "exam"}


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class Task:
    id: str
    subject: str
    title: str
    kind: str
    effort: float
    deadline: date
    start: date
    fixed: bool
    max_shift: int
    original_deadline: date

    @property
    def shift(self) -> int:
        return (self.deadline - self.original_deadline).days

    def span(self) -> int:
        return (self.deadline - self.start).days + 1


@dataclass
class Config:
    today: date
    daily_cap: float = 5.0
    weekend_cap: float = 3.0
    weekly_cap: float = 28.0
    fairness: float = 0.5
    no_weekend_deadlines: bool = False
    blackout: Set[date] = None
    horizon_end: Optional[date] = None

    def cap(self, d: date) -> float:
        return self.weekend_cap if d.weekday() >= 5 else self.daily_cap


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------
def _d(s: str) -> date:
    return date.fromisoformat(s.strip())


def load_tasks(path: str, today: date) -> List[Task]:
    """CSV columns: id,subject,title,type,effort_hours,deadline
    optional:       start,fixed,max_shift_days"""
    tasks: List[Task] = []
    with open(path, newline="", encoding="utf-8") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
            try:
                kind = row["type"].lower()
                deadline = _d(row["deadline"])
                effort = float(row["effort_hours"])
                if effort <= 0:
                    raise ValueError("effort_hours must be > 0")
            except (KeyError, ValueError) as e:
                sys.exit(f"{path}, line {n}: invalid row ({e})")
            if deadline < today:
                print(f"warning: '{row.get('title')}' is already past due - skipped",
                      file=sys.stderr)
                continue
            lead = LEAD_DAYS.get(kind, 7)
            start = _d(row["start"]) if row.get("start") else deadline - timedelta(lead - 1)
            start = min(max(start, today), deadline)
            fixed = (row["fixed"].lower() in {"1", "true", "yes", "y"}
                     if row.get("fixed") else kind in FIXED_TYPES)
            max_shift = (int(row["max_shift_days"]) if row.get("max_shift_days")
                         else DEFAULT_MAX_SHIFT.get(kind, 3))
            tasks.append(Task(row["id"], row["subject"], row["title"], kind,
                              effort, deadline, start, fixed,
                              0 if fixed else max_shift, deadline))
    if not tasks:
        sys.exit("no usable tasks found")
    return tasks


# --------------------------------------------------------------------------
# Workload analysis
# --------------------------------------------------------------------------
def daily_load(tasks: Iterable[Task]) -> Dict[date, float]:
    load: Dict[date, float] = defaultdict(float)
    for t in tasks:
        per_day = t.effort / t.span()
        for i in range(t.span()):
            load[t.start + timedelta(i)] += per_day
    return load


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weekly_load(load: Dict[date, float]) -> Dict[date, float]:
    wk: Dict[date, float] = defaultdict(float)
    for d, h in load.items():
        wk[week_start(d)] += h
    return wk


def overload_score(tasks: List[Task], cfg: Config) -> float:
    load = daily_load(tasks)
    s = sum(max(0.0, h - cfg.cap(d)) for d, h in load.items())
    s += sum(max(0.0, h - cfg.weekly_cap) for h in weekly_load(load).values())
    return s


def overloaded_days(tasks: List[Task], cfg: Config):
    load = daily_load(tasks)
    return sorted((d, h) for d, h in load.items() if h > cfg.cap(d) + 1e-6)


def overloaded_weeks(tasks: List[Task], cfg: Config):
    wk = weekly_load(daily_load(tasks))
    return sorted((w, h) for w, h in wk.items() if h > cfg.weekly_cap + 1e-6)


# --------------------------------------------------------------------------
# Balancing
# --------------------------------------------------------------------------
def legal_deadline(d: date, cfg: Config) -> bool:
    if cfg.blackout and d in cfg.blackout:
        return False
    if cfg.no_weekend_deadlines and d.weekday() >= 5:
        return False
    return True


def balance(tasks: List[Task], cfg: Config) -> List[Task]:
    """Return a new task list with adjusted deadlines (input is not modified)."""
    work = [Task(**t.__dict__) for t in tasks]
    subject_shift: Dict[str, int] = defaultdict(int)

    while True:
        current = overload_score(work, cfg)
        if current <= EPS:
            break
        best = None  # (ratio, -days, task, new_deadline)
        for t in work:
            if t.fixed:
                continue
            for extra in range(1, t.max_shift - t.shift + 1):
                nd = t.deadline + timedelta(extra)
                if cfg.horizon_end and nd > cfg.horizon_end:
                    break
                if not legal_deadline(nd, cfg):
                    continue
                old = t.deadline
                t.deadline = nd
                gain = current - overload_score(work, cfg)
                t.deadline = old
                if gain <= EPS:
                    continue
                cost = extra * (1 + cfg.fairness * subject_shift[t.subject])
                key = (gain / cost, -extra)
                if best is None or key > best[0]:
                    best = (key, t, nd, extra)
        if best is None:
            break  # nothing legal helps any more
        _, t, nd, extra = best
        t.deadline = nd
        subject_shift[t.subject] += extra

    prune(work, cfg)
    return work


def prune(work: List[Task], cfg: Config) -> None:
    """Pull deadlines back as far as possible without making things worse."""
    base = overload_score(work, cfg)
    for t in sorted(work, key=lambda x: -x.shift):
        while t.shift > 0:
            prev = t.deadline
            nd = prev - timedelta(1)
            while nd > t.original_deadline and not legal_deadline(nd, cfg):
                nd -= timedelta(1)
            t.deadline = nd
            s = overload_score(work, cfg)
            if s <= base + EPS:
                base = min(base, s)
            else:
                t.deadline = prev
                break


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def bar(value: float, cap: float, width: int = 24) -> str:
    scale = width / max(cap * 1.8, 1e-9)
    n = min(width, round(value * scale))
    mark = min(width - 1, round(cap * scale))
    cells = ["#" if i < n else "." for i in range(width)]
    cells[mark] = "|" if cells[mark] == "." else "!"
    return "".join(cells)


def report(orig: List[Task], new: List[Task], cfg: Config) -> str:
    out: List[str] = []
    p = out.append
    b_load, a_load = daily_load(orig), daily_load(new)
    p("=" * 72)
    p(f" DEADLINE BALANCER REPORT   (today: {cfg.today:%a %d %b %Y})")
    p("=" * 72)
    p(f"Tasks: {len(orig)}   total effort: {sum(t.effort for t in orig):.1f} h")
    p(f"Capacity: {cfg.daily_cap:g} h/weekday, {cfg.weekend_cap:g} h/weekend day, "
      f"{cfg.weekly_cap:g} h/week\n")

    # weekly table
    p("WEEKLY WORKLOAD (hours)")
    p(f"{'week of':<12}{'before':>8}{'after':>8}{'cap':>6}   status")
    bw, aw = weekly_load(b_load), weekly_load(a_load)
    for w in sorted(set(bw) | set(aw)):
        b, a = bw.get(w, 0), aw.get(w, 0)
        flag = ("OVERLOAD -> ok" if b > cfg.weekly_cap + 1e-6 and a <= cfg.weekly_cap + 1e-6
                else "OVERLOAD" if a > cfg.weekly_cap + 1e-6 else "ok")
        p(f"{w:%d %b %Y}  {b:>8.1f}{a:>8.1f}{cfg.weekly_cap:>6g}   {flag}")

    # daily overloads
    p("\nOVERLOADED DAYS (before balancing)")
    od = overloaded_days(orig, cfg)
    if not od:
        p("  none")
    for d, h in od:
        p(f"  {d:%a %d %b}  {h:5.1f} h / {cfg.cap(d):g}  {bar(h, cfg.cap(d))}"
          f"  -> after: {a_load.get(d, 0):5.1f} h")

    # suggestions
    moved = [t for t in new if t.shift > 0]
    p("\nSUGGESTED DEADLINE ADJUSTMENTS")
    if not moved:
        p("  none needed" if not od else "  no legal adjustment could help")
    for t in sorted(moved, key=lambda x: x.original_deadline):
        p(f"  {t.subject} - {t.title} [{t.id}]: {t.original_deadline:%a %d %b} "
          f"-> {t.deadline:%a %d %b}  (+{t.shift} day{'s' if t.shift > 1 else ''})")
    total = sum(t.shift for t in moved)
    p(f"  Total: {len(moved)} deadline(s) moved, {total} day(s) of extension.")

    # fairness
    p("\nFAIRNESS (extension days per subject)")
    per: Dict[str, int] = defaultdict(int)
    for t in new:
        per[t.subject] += t.shift
    for s, d in sorted(per.items(), key=lambda kv: -kv[1]):
        p(f"  {s:<22}{d:>3} day(s)")

    # residual
    rd, rw = overloaded_days(new, cfg), overloaded_weeks(new, cfg)
    p("\nRESULT")
    p(f"  overload score: {overload_score(orig, cfg):.1f} -> {overload_score(new, cfg):.1f}")
    if rd or rw:
        p("  Still overloaded after all allowed adjustments (constraints too tight;")
        p("  consider raising max_shift_days, or moving a fixed quiz/exam):")
        for d, h in rd:
            p(f"    day  {d:%a %d %b}: {h:.1f} h (cap {cfg.cap(d):g})")
        for w, h in rw:
            p(f"    week {w:%d %b}: {h:.1f} h (cap {cfg.weekly_cap:g})")
    else:
        p("  All days and weeks are within capacity.")
    return "\n".join(out)


def write_csv(path: str, new: List[Task]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "subject", "title", "type", "effort_hours",
                    "original_deadline", "suggested_deadline", "shift_days"])
        for t in new:
            w.writerow([t.id, t.subject, t.title, t.kind, t.effort,
                        t.original_deadline, t.deadline, t.shift])


def write_chart(path: str, orig: List[Task], new: List[Task], cfg: Config) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    b, a = daily_load(orig), daily_load(new)
    days = sorted(set(b) | set(a))
    x = list(range(len(days)))
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.bar([i - 0.2 for i in x], [b.get(d, 0) for d in days], 0.4, label="before", color="#d9534f")
    ax.bar([i + 0.2 for i in x], [a.get(d, 0) for d in days], 0.4, label="after", color="#4a90d9")
    ax.step(x, [cfg.cap(d) for d in days], where="mid", color="black", ls="--", label="daily capacity")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{d:%d %b}\n{d:%a}" for d in days], fontsize=7)
    ax.set_ylabel("hours of work")
    ax.set_title("Daily workload before vs after deadline balancing")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    return True


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tasks_csv")
    ap.add_argument("--today", type=_d, default=date.today(), help="YYYY-MM-DD (default: today)")
    ap.add_argument("--daily-cap", type=float, default=5.0)
    ap.add_argument("--weekend-cap", type=float, default=3.0)
    ap.add_argument("--weekly-cap", type=float, default=28.0)
    ap.add_argument("--fairness", type=float, default=0.5,
                    help="penalty for shifting a subject that was already shifted (0 = off)")
    ap.add_argument("--no-weekend-deadlines", action="store_true")
    ap.add_argument("--blackout", type=_d, nargs="*", default=[], help="dates deadlines cannot land on")
    ap.add_argument("--horizon-end", type=_d, help="no deadline may move past this date")
    ap.add_argument("--out", default="balanced_deadlines.csv")
    ap.add_argument("--chart", default="workload.png")
    args = ap.parse_args(argv)

    cfg = Config(args.today, args.daily_cap, args.weekend_cap, args.weekly_cap,
                 args.fairness, args.no_weekend_deadlines, set(args.blackout),
                 args.horizon_end)
    tasks = load_tasks(args.tasks_csv, cfg.today)
    new = balance(tasks, cfg)
    print(report(tasks, new, cfg))
    write_csv(args.out, new)
    print(f"\nWrote {args.out}" + (f" and {args.chart}" if write_chart(args.chart, tasks, new, cfg) else ""))


if __name__ == "__main__":
    main()
