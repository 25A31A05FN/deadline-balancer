"""
Read a task list from CSV, PNG/JPG (screenshot or photo) or PDF.

Returns a pandas DataFrame with the columns the app's table uses plus a list
of plain-language notes. Images and scanned PDFs go through OCR, so the result
is a *draft* that the user should check in the editable table.
"""
from __future__ import annotations

import io
import re
from datetime import date, timedelta
from typing import List, Optional, Tuple

import pandas as pd

COLUMNS = ["subject", "title", "type", "effort_hours", "deadline",
           "start", "fixed", "max_shift_days"]
TYPES = ["assignment", "quiz", "exam", "project", "lab", "tutorial"]
DEFAULT_EFFORT = {"assignment": 6, "project": 15, "tutorial": 3, "lab": 5,
                  "quiz": 3, "exam": 10}

SYNONYMS = {
    "subject": {"subject", "course", "module", "class", "paper", "unit"},
    "title": {"title", "task", "name", "assignment", "work", "description", "topic", "item"},
    "type": {"type", "kind", "category"},
    "effort_hours": {"effort_hours", "effort", "hours", "hrs", "hour", "time", "estimated hours",
                     "est hours", "estimated effort", "effort hours", "est. hours", "workload"},
    "deadline": {"deadline", "due", "due date", "date", "submission", "submission date",
                 "last date", "due on"},
    "start": {"start", "start date", "release", "release date", "start (optional)"},
    "fixed": {"fixed", "fixed (can't move)", "cant move", "can't move"},
    "max_shift_days": {"max_shift_days", "max shift", "max delay", "flexibility"},
}

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"

DATE_PATTERNS = [
    # 2026-10-30 / 2026/10/30
    (re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b"), "ymd"),
    # 30-10-2026 / 30/10/26  (day first)
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})\b"), "dmy"),
    # 30 Oct 2026 / 30th October
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+" + _MON + r"\.?,?(?:[\s\-]+(\d{4}))?\b", re.I), "d_mon"),
    # Oct 30, 2026 / October 30th
    (re.compile(r"\b" + _MON + r"\.?[\s\-]+(\d{1,2})(?:st|nd|rd|th)?(?:,?[\s\-]+(\d{4}))?\b", re.I), "mon_d"),
]
HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", re.I)
TYPE_RE = re.compile(r"\b(assignment|quiz|exam|project|lab|tutorial|test|viva|report|essay|presentation)s?\b", re.I)
TYPE_MAP = {"test": "quiz", "viva": "exam", "report": "lab", "essay": "assignment",
            "presentation": "project"}


# ---------------------------------------------------------------------------
def _make_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _infer_year(m: int, d: int, today: date) -> Optional[date]:
    cand = _make_date(today.year, m, d)
    if cand is None:
        return None
    if (today - cand).days > 60:       # clearly meant for next year
        cand = _make_date(today.year + 1, m, d)
    return cand


def find_date(text: str, today: date) -> Tuple[Optional[date], Optional[re.Match]]:
    """First date in text and its match object."""
    for pat, kind in DATE_PATTERNS:
        for m in pat.finditer(text):
            g = m.groups()
            if kind == "ymd":
                dt = _make_date(int(g[0]), int(g[1]), int(g[2]))
            elif kind == "dmy":
                y = int(g[2]); y = y + 2000 if y < 100 else y
                dt = _make_date(y, int(g[1]), int(g[0]))
            elif kind == "d_mon":
                mon = MONTHS[g[1][:3].lower()]
                dt = _make_date(int(g[2]), mon, int(g[0])) if g[2] else _infer_year(mon, int(g[0]), today)
            else:
                mon = MONTHS[g[0][:3].lower()]
                dt = _make_date(int(g[2]), mon, int(g[1])) if g[2] else _infer_year(mon, int(g[1]), today)
            if dt:
                return dt, m
    return None, None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("|", " | ")).strip(" -–—:;,.|")


def parse_text(text: str, today: date) -> Tuple[pd.DataFrame, List[str]]:
    """Turn free text / OCR output into task rows. One task per line that has a date."""
    rows, guessed = [], 0
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) < 6:
            continue
        dl, m = find_date(line, today)
        if dl is None:
            continue
        rest = line[:m.start()] + " | " + line[m.end():]
        hm = HOURS_RE.search(rest)
        effort = float(hm.group(1)) if hm else None
        if hm:
            rest = rest[:hm.start()] + " | " + rest[hm.end():]
        cells = [_clean(c) for c in re.split(r"\s{2,}|\t|\||;", rest)]
        cells = [c for c in cells if c and not re.fullmatch(r"[\W_]+", c)]
        if effort is None:      # a lone number cell such as "8" is the hours
            for c in cells:
                if re.fullmatch(r"\d+(?:\.\d+)?", c) and float(c) <= 100:
                    effort = float(c)
                    cells.remove(c)
                    break
        tm = TYPE_RE.search(line)
        kind = "assignment"
        if tm:
            w = tm.group(1).lower()
            kind = TYPE_MAP.get(w, w)
        if effort is None:
            effort = float(DEFAULT_EFFORT.get(kind, 6))
            guessed += 1
        cells = [c for c in cells if not re.fullmatch(r"\d+", c)]
        if not cells:
            continue
        if len(cells) >= 2:
            subject, title = cells[0], " ".join(cells[1:])
        else:
            subject, title = "General", cells[0]
        rows.append(dict(subject=subject, title=title, type=kind, effort_hours=effort,
                         deadline=dl, start=None, fixed=kind in ("quiz", "exam"),
                         max_shift_days=None))
    notes = []
    if guessed:
        notes.append(f"{guessed} task(s) had no hours listed, so we filled in a typical amount "
                     "for their type. Please adjust them.")
    return pd.DataFrame(rows, columns=COLUMNS), notes


# ---------------------------------------------------------------------------
def _normalise_headers(df: pd.DataFrame) -> pd.DataFrame:
    ren = {}
    for c in df.columns:
        key = str(c).strip().lower()
        for target, names in SYNONYMS.items():
            if key in names and target not in ren.values():
                ren[c] = target
                break
    return df.rename(columns=ren)


def _finish(df: pd.DataFrame, today: date) -> Tuple[pd.DataFrame, List[str]]:
    """Coerce a table with (some of) the standard columns into the app's format."""
    notes: List[str] = []
    df = _normalise_headers(df)
    if "deadline" not in df.columns:
        raise ValueError("Couldn't find a deadline / due-date column.")
    if "title" not in df.columns:
        df["title"] = [f"Task {i + 1}" for i in range(len(df))]
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df["deadline"] = df["deadline"].map(lambda v: _to_date(v, today))
    df["start"] = df["start"].map(lambda v: _to_date(v, today))
    df["type"] = df["type"].map(lambda v: _norm_type(v))
    df["subject"] = df["subject"].fillna("General").astype(str)
    df["title"] = df["title"].astype(str)
    eff = pd.to_numeric(df["effort_hours"].astype(str).str.extract(r"(\d+(?:\.\d+)?)")[0], errors="coerce")
    missing = eff.isna()
    if missing.any():
        eff[missing] = df.loc[missing, "type"].map(lambda t: float(DEFAULT_EFFORT.get(t, 6)))
        notes.append(f"{int(missing.sum())} task(s) had no hours, so we filled in a typical amount.")
    df["effort_hours"] = eff
    df["fixed"] = df["fixed"].map(lambda v: str(v).strip().lower() in {"1", "true", "yes", "y"}
                                  if v is not None and str(v) != "nan" else False)
    df["max_shift_days"] = pd.to_numeric(df["max_shift_days"], errors="coerce")
    bad = df["deadline"].isna()
    if bad.any():
        notes.append(f"{int(bad.sum())} row(s) had a date we couldn't read and were left out.")
        df = df[~bad]
    return df[COLUMNS].reset_index(drop=True), notes


def _norm_type(v) -> str:
    s = str(v).strip().lower() if v is not None else ""
    s = TYPE_MAP.get(s, s)
    return s if s in TYPES else "assignment"


def _to_date(v, today: date) -> Optional[date]:
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan", "None", "NaT"):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date()
    if isinstance(v, date):
        return v
    dt, _ = find_date(str(v), today)
    return dt


# ---------------------------------------------------------------------------
def _ocr_image(img) -> str:
    import pytesseract
    from PIL import ImageOps
    img = ImageOps.grayscale(img)
    if img.width < 1600:                       # small screenshots OCR better when enlarged
        k = 1600 / img.width
        img = img.resize((int(img.width * k), int(img.height * k)))
    img = ImageOps.autocontrast(img)
    return pytesseract.image_to_string(img, config="--psm 6")


def _read_image(data: bytes, today: date):
    from PIL import Image
    try:
        text = _ocr_image(Image.open(io.BytesIO(data)))
    except Exception as e:  # tesseract missing, corrupt image...
        raise ValueError(f"Couldn't read text from the image ({e}).")
    df, notes = parse_text(text, today)
    return df, ["Read from an image, so some words may be misread - please check the table."] + notes


def _read_pdf(data: bytes, today: date):
    import pdfplumber
    notes: List[str] = []
    frames, text_parts = [], []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for tbl in page.extract_tables():
                if tbl and len(tbl) > 1:
                    t = pd.DataFrame(tbl[1:], columns=[str(c or "").strip() for c in tbl[0]])
                    if "deadline" in _normalise_headers(t).columns:
                        frames.append(t)
            text_parts.append(page.extract_text() or "")
    if frames:
        df, n = _finish(pd.concat(frames, ignore_index=True), today)
        return df, n
    text = "\n".join(text_parts)
    if len(text.strip()) < 20:                 # scanned PDF -> OCR
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(data)
            text = "\n".join(_ocr_image(doc[i].render(scale=2.5).to_pil()) for i in range(len(doc)))
            notes.append("This PDF is a scan, so it was read with OCR - please check the table.")
        except Exception as e:
            raise ValueError(f"Couldn't read this PDF ({e}).")
    df, n = parse_text(text, today)
    return df, notes + n


def read_tasks(data: bytes, filename: str, today: date) -> Tuple[pd.DataFrame, List[str]]:
    """Main entry point. Raises ValueError with a friendly message on failure."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "csv":
        try:
            df = pd.read_csv(io.BytesIO(data), dtype=str, skipinitialspace=True)
        except Exception as e:
            raise ValueError(f"Couldn't read the CSV ({e}).")
        df, notes = _finish(df, today)
    elif ext in ("png", "jpg", "jpeg", "webp"):
        df, notes = _read_image(data, today)
    elif ext == "pdf":
        df, notes = _read_pdf(data, today)
    else:
        raise ValueError("Please upload a CSV, PNG, JPG or PDF file.")
    if df.empty:
        raise ValueError("We couldn't find any tasks with a due date in that file. "
                         "Each task should be on its own line with a date, e.g. "
                         "\"Maths | Assignment 3 | 8 hrs | 30 Oct 2026\".")
    return df, notes
