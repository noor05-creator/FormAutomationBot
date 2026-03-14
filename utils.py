"""
utils.py — Helper utilities for the Form Auto-Filler Bot v2.

Responsibilities:
  • Set up dual-sink (file + console) logging.
  • Load and validate the input data file (Excel or CSV).
  • Append per-row results to the CSV output report.
  • Checkpoint system: save / load the last completed row number so a
    crashed run can resume without re-submitting already-processed rows.
  • Provide human-like random-delay helpers.
"""

import csv
import json
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from config import (
    FIELD_SELECTORS,
    LOG_DIR,
    MAX_TYPING_DELAY,
    MIN_TYPING_DELAY,
    OUTPUT_REPORT_FILENAME,
    PROGRESS_FILE,
    SCREENSHOTS_DIR,
)


# ── Logging setup ──────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """
    Create and return a logger that writes simultaneously to:
      • a timestamped .log file in LOG_DIR  (DEBUG level — full detail)
      • the console / stdout               (INFO level  — human-readable)

    Returns
    -------
    logging.Logger
        Configured logger named "FormFillerBot".
    """
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    Path(SCREENSHOTS_DIR).mkdir(parents=True, exist_ok=True)

    timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = Path(LOG_DIR) / f"bot_run_{timestamp}.log"

    logger = logging.getLogger("FormFillerBot")
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers if setup_logging() is called more than once.
    if logger.handlers:
        logger.handlers.clear()

    # ── File handler ──────────────────────────────────────────────────────────
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # ── Console handler ───────────────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    ))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info("Logging initialised → %s", log_filename)
    return logger


# ── Data loading ───────────────────────────────────────────────────────────────

def _derive_required_columns() -> set[str]:
    """
    Derive the set of required column names from FIELD_SELECTORS so that
    config.py is the single source of truth and utils.py never needs
    to be edited when fields change.
    """
    cols: set[str] = set()
    for section in FIELD_SELECTORS.values():
        cols.update(section.keys())
    return cols


def load_input_data(
    file_path: str,
    logger: logging.Logger,
) -> Optional[pd.DataFrame]:
    """
    Read the input file (Excel or CSV) into a DataFrame, normalise column
    names, and validate that every field declared in FIELD_SELECTORS has a
    matching column.

    Missing columns generate a warning (not an error) so that the bot can
    still run with partial data — useful during development.

    Parameters
    ----------
    file_path : str
        Path to the .xlsx / .xls / .csv input file.
    logger : logging.Logger
        Logger for status messages.

    Returns
    -------
    pd.DataFrame | None
        Cleaned DataFrame on success, None on unrecoverable failure.
    """
    path = Path(file_path)

    if not path.exists():
        logger.error("Input file not found: %s", path.resolve())
        return None

    try:
        ext = path.suffix.lower()
        if ext in {".xlsx", ".xls"}:
            df = pd.read_excel(path, dtype=str)
            logger.info("Loaded Excel file: %s  (%d rows)", path.name, len(df))
        elif ext == ".csv":
            df = pd.read_csv(path, dtype=str)
            logger.info("Loaded CSV file: %s  (%d rows)", path.name, len(df))
        else:
            logger.error("Unsupported file type '%s'. Use .xlsx or .csv.", path.suffix)
            return None
    except Exception as exc:
        logger.error("Failed to read input file: %s", exc)
        return None

    # Normalise column names to lowercase + stripped.
    df.columns = [c.strip().lower() for c in df.columns]

    # Warn about columns that appear in config but are missing from the file.
    required = _derive_required_columns()
    missing  = required - set(df.columns)
    if missing:
        logger.warning(
            "The following configured fields have no matching column in the "
            "input file and will be skipped: %s",
            sorted(missing),
        )

    # Drop all-blank rows, reset index, fill remaining NaN with "".
    df = df.dropna(how="all").reset_index(drop=True).fillna("")

    if df.empty:
        logger.error("Input file contains no data rows after cleaning.")
        return None

    logger.info("Data validated — %d processable rows.", len(df))
    return df


# ── Output report ──────────────────────────────────────────────────────────────

_REPORT_HEADERS = [
    "row", "fullname", "email", "attempts", "status", "error_message", "timestamp",
]


def init_report(logger: logging.Logger) -> str:
    """
    Create (or overwrite) the output CSV report and write the header row.

    Returns
    -------
    str
        Absolute path of the report file.
    """
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    report_path = str(Path(LOG_DIR) / OUTPUT_REPORT_FILENAME)

    with open(report_path, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=_REPORT_HEADERS).writeheader()

    logger.info("Output report initialised → %s", report_path)
    return report_path


def append_to_report(
    report_path: str,
    row_number: int,
    fullname: str,
    email: str,
    attempts: int,
    status: str,
    error_message: str = "",
) -> None:
    """
    Append one result row to the CSV report.

    Parameters
    ----------
    report_path : str
        Path returned by init_report().
    row_number : int
        1-based row index.
    fullname : str
        "Firstname Lastname" derived from the data row.
    email : str
        Email address from the data row.
    attempts : int
        How many submission attempts were made (1–MAX_ATTEMPTS).
    status : str
        "SUCCESS" or "FAILED".
    error_message : str
        Last error message if status is FAILED; empty string otherwise.
    """
    with open(report_path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=_REPORT_HEADERS).writerow({
            "row":           row_number,
            "fullname":      fullname,
            "email":         email,
            "attempts":      attempts,
            "status":        status,
            "error_message": error_message,
            "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })


# ── Checkpoint / resume system ────────────────────────────────────────────────

def load_progress(logger: logging.Logger) -> int:
    """
    Read the progress checkpoint file and return the last successfully
    submitted row number (1-based), or 0 if no checkpoint exists.

    Parameters
    ----------
    logger : logging.Logger

    Returns
    -------
    int
        Last completed row number; 0 means start from the beginning.
    """
    prog_path = Path(PROGRESS_FILE)
    if not prog_path.exists():
        return 0

    try:
        data = json.loads(prog_path.read_text(encoding="utf-8"))
        last = int(data.get("last_completed_row", 0))
        logger.info("Checkpoint found — resuming after row %d.", last)
        return last
    except Exception as exc:
        logger.warning("Could not read progress file: %s — starting from row 1.", exc)
        return 0


def save_progress(row_number: int, logger: logging.Logger) -> None:
    """
    Persist the last successfully submitted row number to disk so the run
    can be resumed if it crashes.

    Parameters
    ----------
    row_number : int
        1-based index of the row just completed successfully.
    logger : logging.Logger
    """
    try:
        Path(PROGRESS_FILE).write_text(
            json.dumps({
                "last_completed_row": row_number,
                "saved_at": datetime.now().isoformat(),
            }, indent=2),
            encoding="utf-8",
        )
        logger.debug("Checkpoint saved — row %d.", row_number)
    except Exception as exc:
        logger.warning("Failed to save progress checkpoint: %s", exc)


def clear_progress(logger: logging.Logger) -> None:
    """
    Delete the progress checkpoint file after a complete, successful run.

    Parameters
    ----------
    logger : logging.Logger
    """
    try:
        prog_path = Path(PROGRESS_FILE)
        if prog_path.exists():
            prog_path.unlink()
            logger.info("Progress checkpoint cleared.")
    except Exception as exc:
        logger.warning("Could not clear progress file: %s", exc)


# ── Timing helpers ─────────────────────────────────────────────────────────────

def human_delay(
    min_s: float = MIN_TYPING_DELAY,
    max_s: float = MAX_TYPING_DELAY,
) -> None:
    """
    Sleep for a uniformly random duration in [min_s, max_s] seconds.

    Mimics human reaction time to reduce bot-detection risk.

    Parameters
    ----------
    min_s : float
        Minimum sleep duration in seconds.
    max_s : float
        Maximum sleep duration in seconds.
    """
    time.sleep(random.uniform(min_s, max_s))


# ── Name helper ────────────────────────────────────────────────────────────────

def get_display_name(row: dict) -> str:
    """
    Build a human-readable "Firstname Lastname" string from the data row.

    Falls back gracefully if only one name field is available, using
    'email' as a last resort identifier.

    Parameters
    ----------
    row : dict
        A single data record from the input DataFrame.

    Returns
    -------
    str
        Display name for logging and reporting.
    """
    first = row.get("firstname", "").strip()
    last  = row.get("lastname",  "").strip()

    if first and last:
        return f"{first} {last}"
    if first:
        return first
    if last:
        return last

    # Ultimate fallback — use the email or a placeholder.
    return row.get("email", "<unknown>").strip() or "<unknown>"
