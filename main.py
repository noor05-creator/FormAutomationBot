"""
main.py — Entry point for the Form Auto-Filler Bot v2.

Pipeline
────────
1.  Set up logging.
2.  Load & validate the input data file.
3.  Check for a resume checkpoinat (progress.json) and ask the user
    whether to resume or start fresh.
4.  Initialise the output CSV report.
5.  Launch Chrome.
6.  Iterate over every pending data row:
      a. Fill & submit the form (with automatic retry).
      b. Record the result to the CSV report immediately.
      c. Save a checkpoint on success so a crash can be resumed.
7.  Print a run summary.
8.  Clear the checkpoint if all rows completed successfully.

Run
───
    python main.py
"""

import sys

from config import INPUT_FILE_PATH
from form_bot import FormBot
from utils import (
    append_to_report,
    clear_progress,
    get_display_name,
    init_report,
    load_input_data,
    load_progress,
    save_progress,
    setup_logging,
)


def _ask_resume(last_row: int, logger) -> bool:
    """
    Prompt the user (interactive) to resume from *last_row* or start fresh.

    If stdin is not a tty (e.g. CI / cron), automatically resumes.

    Parameters
    ----------
    last_row : int
        Row number of the last successfully completed submission.
    logger : logging.Logger

    Returns
    -------
    bool
        True = resume from last_row + 1; False = start from row 1.
    """
    if not sys.stdin.isatty():
        logger.info("Non-interactive mode — resuming automatically from row %d.", last_row + 1)
        return True

    print(f"\n  ⚡ Checkpoint found: last completed row = {last_row}.")
    answer = input("  Resume from that point? [Y/n]: ").strip().lower()
    return answer not in {"n", "no"}


def main() -> int:
    """
    Orchestrate the full bot run.

    Returns
    -------
    int
        0 — all rows succeeded.
        1 — fatal startup error (no rows processed).
        2 — partial failure (at least one row failed).
    """
    # ── 1. Logging ─────────────────────────────────────────────────────────────
    logger = setup_logging()
    logger.info("══════════════════════════════════════════════")
    logger.info("      Form Auto-Filler Bot v2 — START        ")
    logger.info("══════════════════════════════════════════════")

    # ── 2. Load data ────────────────────────────────────────────────────────────
    df = load_input_data(INPUT_FILE_PATH, logger)
    if df is None:
        logger.error("Aborting: could not load valid input data.")
        return 1

    total_rows = len(df)
    logger.info("Input file contains %d row(s).", total_rows)

    # ── 3. Resume checkpoint ────────────────────────────────────────────────────
    start_from_row = 1   # 1-based; rows with index < this are skipped.

    last_completed = load_progress(logger)
    if last_completed > 0 and last_completed < total_rows:
        if _ask_resume(last_completed, logger):
            start_from_row = last_completed + 1
            logger.info("Resuming from row %d.", start_from_row)
        else:
            logger.info("Starting fresh from row 1.")
    elif last_completed >= total_rows:
        logger.info(
            "All %d rows were already completed in a previous run. "
            "Delete progress.json to run again.", total_rows
        )
        return 0

    # ── 4. Initialise report ────────────────────────────────────────────────────
    report_path = init_report(logger)

    # ── 5. Launch browser ───────────────────────────────────────────────────────
    bot = FormBot(logger)
    try:
        bot.start()
    except Exception as exc:
        logger.error("Failed to start Chrome: %s", exc)
        logger.error("Ensure Google Chrome is installed and in PATH.")
        return 1

    # ── 6. Process rows ─────────────────────────────────────────────────────────
    success_count = 0
    failure_count = 0

    try:
        for idx, row in df.iterrows():
            row_number = idx + 1   # Convert 0-based DataFrame index → 1-based.

            # Skip rows already handled in a previous (resumed) run.
            if row_number < start_from_row:
                logger.debug("Skipping row %d (already processed).", row_number)
                continue

            row_dict     = row.to_dict()
            display_name = get_display_name(row_dict)
            email        = row_dict.get("email", "")

            # ── Fill & submit (with retry) ─────────────────────────────────
            success, error_msg, attempts = bot.fill_and_submit(
                row_dict, row_number, display_name
            )

            # ── Record result ───────────────────────────────────────────────
            append_to_report(
                report_path  = report_path,
                row_number   = row_number,
                fullname     = display_name,
                email        = email,
                attempts     = attempts,
                status       = "SUCCESS" if success else "FAILED",
                error_message= error_msg,
            )

            if success:
                success_count += 1
                # Save checkpoint so a crash later doesn't re-submit this row.
                save_progress(row_number, logger)
            else:
                failure_count += 1
                # Continue to the next row — one failure must not abort the run.

    finally:
        # Always close the browser, even if an unhandled exception occurs.
        bot.quit()

    # ── 7. Summary ──────────────────────────────────────────────────────────────
    processed = success_count + failure_count
    logger.info("══════════════════════════════════════════════")
    logger.info("      Form Auto-Filler Bot v2 — DONE         ")
    logger.info("  Rows processed : %d / %d", processed, total_rows)
    logger.info("  Succeeded      : %d", success_count)
    logger.info("  Failed         : %d", failure_count)
    logger.info("  Report         : %s", report_path)
    logger.info("══════════════════════════════════════════════")

    # ── 8. Clear checkpoint on full success ─────────────────────────────────────
    if failure_count == 0 and processed == total_rows:
        clear_progress(logger)
        return 0

    return 2 if failure_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
