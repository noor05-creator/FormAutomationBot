"""
config.py — Central configuration for the Form Auto-Filler Bot v2.

This is the ONLY file you need to edit when targeting a new website.
All selectors, paths, timing, and retry settings live here.

Field selector structure
────────────────────────
FIELD_SELECTORS is organized by field *type*.  Each type section maps a
column name (matching your Excel header) to either:
  • a plain CSS selector string  (text / textarea / date / file fields)
  • a dict of { "value": "css_selector" }  (radio / checkbox / dropdown)

The bot reads the section key to know which interaction method to use.
"""

# ── Target website ─────────────────────────────────────────────────────────────
# URL of the page that contains the form you want to fill.
TARGET_URL = "https://www.techlistic.com/p/selenium-practice-form.html"


# ── Form field selectors (nested by type) ─────────────────────────────────────
FIELD_SELECTORS = {

    # ── Plain text inputs, textareas, and date pickers ─────────────────────────
    # Value: a CSS selector string.
    "text_fields": {
        "firstname": "[name='firstname']",
        "lastname":  "[name='lastname']",
        "date":      "#datepicker",
    },

    "radio_fields": {
        "gender": {
            "Male":   "#sex-0",
            "Female": "#sex-1",
        },
        "experience": {
            "1": "#exp-0",
            "2": "#exp-1",
            "3": "#exp-2",
            "4": "#exp-3",
            "5": "#exp-4",
            "6": "#exp-5",
            "7": "#exp-6",
        },
    },

    "checkbox_fields": {
        "profession": {
            "Manual Tester":     "#profession-0",
            "Automation Tester": "#profession-1",
        },
        "tools": {
            "QTP":                "#tool-0",
            "Selenium IDE":       "#tool-1",
            "Selenium Webdriver": "#tool-2",
        },
    },

    "dropdown_fields": {
        "continent":        "#continents",
        "selenium_command": "#selenium_commands",
    },

    "file_fields": {
        "photo": "#photo",
    },
}


# ── Submit button ─────────────────────────────────────────────────────────────
# CSS selector for the form's submit button.
SUBMIT_BUTTON_SELECTOR = "#submit"

# ── Submit verification ───────────────────────────────────────────────────────
# Selectors / patterns used to verify a successful submission.
# The bot checks for a URL change OR any of these element selectors becoming
# visible after the click.
SUBMIT_SUCCESS_SELECTORS = [
    ".modal-content",          # modal confirmation dialog
    ".success-message",        # generic success class
    "#confirmationMessage",    # explicit confirmation element
    "[class*='success']",      # any element whose class contains 'success'
]

# Seconds to wait for a success indicator after clicking submit.
SUBMIT_VERIFY_TIMEOUT = 10

# Set to False for demo/static forms that show no success message or URL
# change after submission (e.g. techlistic.com practice form).
# Set to True for real production forms that redirect or show confirmation.
VERIFY_SUBMISSION = False


# ── File paths ────────────────────────────────────────────────────────────────
INPUT_FILE_PATH       = "sample_input.xlsx"
LOG_DIR               = "logs"
SCREENSHOTS_DIR       = "screenshots"
OUTPUT_REPORT_FILENAME = "output_report.csv"

# JSON file used to track the last successfully submitted row (resume feature).
PROGRESS_FILE         = "progress.json"


# ── Browser settings ──────────────────────────────────────────────────────────
HEADLESS             = False      # True = no visible window (good for servers)
IMPLICIT_WAIT_SECONDS = 30        # increased: ad-heavy page with 15 iframes needs more time
PAGE_LOAD_TIMEOUT    = 60         # increased: give Chrome enough time on slow ad pages


# ── Retry settings ────────────────────────────────────────────────────────────
# Total number of attempts per row (1 original + N retries).
MAX_ATTEMPTS = 3

# Pause (seconds) before each retry attempt.
RETRY_DELAY  = 3.0


# ── Anti-detection timing ─────────────────────────────────────────────────────
MIN_TYPING_DELAY = 0.05    # seconds between keystrokes (min)
MAX_TYPING_DELAY = 0.18    # seconds between keystrokes (max)

MIN_FIELD_DELAY  = 0.4     # pause between filling fields (min)
MAX_FIELD_DELAY  = 1.2     # pause between filling fields (max)

MIN_SUBMIT_DELAY = 2.0     # pause after submitting a form (min)
MAX_SUBMIT_DELAY = 4.0     # pause after submitting a form (max)

MIN_ROW_DELAY    = 1.5     # pause between data rows (min)
MAX_ROW_DELAY    = 3.0     # pause between data rows (max)