# 🤖 Form Auto-Filler Bot v2

A production-ready Python automation bot that reads contact data from an Excel or CSV file and fills, submits, and verifies web forms using **Selenium 4** — with support for every HTML form element type, automatic retry, screenshot capture on failure, crash-resume capability, and a live CSV submission report.

> **Portfolio note** — This project showcases: multi-type Selenium automation, pandas data pipelines, configurable nested-selector architecture, anti-detection techniques, retry/resume patterns, structured logging, and clean Python packaging.

---

## ✨ What's New in v2

| Feature | Details |
|---|---|
| **All field types** | Text, textarea, radio, checkbox (multi-value), dropdown `<select>`, file upload |
| **Nested selectors** | `FIELD_SELECTORS` organized by type — no code changes needed for new forms |
| **Auto retry** | Configurable retry count (default 3 attempts) before marking a row failed |
| **Screenshot on failure** | PNG saved to `screenshots/row_NNNN_error.png` for every failed attempt |
| **Submit verification** | Waits for URL change or success element — catches silent failures |
| **Resume after crash** | `progress.json` checkpoint lets you pick up exactly where you left off |
| **Smart name logging** | Logs "Firstname Lastname" instead of raw field names |
| **Dynamic column validation** | Required columns derived from `config.py` — one source of truth |

---

## 📁 Project Structure

```
form_filler_bot/
│
├── main.py              # Entry point — orchestrates the full pipeline
├── config.py            # ⬅ EDIT THIS to target your website & fields
├── form_bot.py          # Selenium engine — all field handlers + retry logic
├── utils.py             # Logging, data loading, reporting, checkpoint system
│
├── requirements.txt
├── README.md
├── sample_input.xlsx    # 5-row demo dataset with all field types
├── progress.json        # Auto-created; tracks resume position (delete to reset)
│
├── logs/
│   ├── bot_run_YYYYMMDD_HHMMSS.log   # Full debug log per run
│   └── output_report.csv             # Live per-row submission results
│
└── screenshots/
    └── row_0001_error.png            # Auto-saved on any failed attempt
```

---

## 🚀 Installation

### Prerequisites
- Python **3.10+**
- Google **Chrome** browser

### Clone & install

```bash
git clone https://github.com/your-username/form-filler-bot.git
cd form-filler-bot

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

---

## ▶️ Running the Bot

```bash
python main.py
```

If a previous run was interrupted, you will be asked:

```
  ⚡ Checkpoint found: last completed row = 3.
  Resume from that point? [Y/n]:
```

Press **Enter** (or type `Y`) to skip already-submitted rows. Type `n` to start over.

---

## ⚙️ Configuration (`config.py`)

### Change the target URL

```python
TARGET_URL = "https://your-site.com/contact"
```

### Change the input file

```python
INPUT_FILE_PATH = "my_leads.xlsx"   # or "leads.csv"
```

### Modify field selectors

`FIELD_SELECTORS` uses a nested structure. The **outer key** tells the bot which interaction method to use. The **inner key** matches the Excel column header.

```python
FIELD_SELECTORS = {

    # Text inputs, textareas, date fields → CSS selector string
    "text_fields": {
        "firstname": "input[name='firstName']",
        "email":     "input[id='userEmail']",
        "message":   "textarea[id='currentAddress']",
    },

    # Radio buttons → { "VisibleLabel": "css_selector" }
    "radio_fields": {
        "gender": {
            "Male":   "input[id='gender-radio-1']",
            "Female": "input[id='gender-radio-2']",
        },
    },

    # Checkboxes → { "VisibleLabel": "css_selector" }
    # Excel value may be comma-separated: "QTP,Selenium Webdriver"
    "checkbox_fields": {
        "tools": {
            "QTP":                "input[id='tool-0']",
            "Selenium Webdriver": "input[id='tool-2']",
        },
    },

    # <select> dropdowns → CSS selector string
    "dropdown_fields": {
        "continent": "select[id='continents']",
    },

    # File uploads → CSS selector string
    "file_fields": {
        "photo": "input[id='uploadFile']",
    },
}
```

To find any selector: open Chrome DevTools (`F12`) → right-click the element → **Copy → Copy selector**.

### Retry settings

```python
MAX_ATTEMPTS = 3     # total attempts (1 original + 2 retries)
RETRY_DELAY  = 3.0   # seconds to wait before each retry
```

### Submit verification

```python
# Selectors for elements that appear after a successful submit.
SUBMIT_SUCCESS_SELECTORS = [
    ".modal-content",
    "#confirmationMessage",
    "[class*='success']",
]
SUBMIT_VERIFY_TIMEOUT = 10   # seconds to wait for verification
```

### Timing (anti-detection)

```python
MIN_TYPING_DELAY = 0.05   # between keystrokes
MAX_TYPING_DELAY = 0.18
MIN_FIELD_DELAY  = 0.4    # between form fields
MAX_FIELD_DELAY  = 1.2
MIN_SUBMIT_DELAY = 2.0    # after clicking submit
MAX_SUBMIT_DELAY = 4.0
```

### Run headless

```python
HEADLESS = True
```

---

## 📊 Input File Format

Excel / CSV must contain columns matching the keys inside each `FIELD_SELECTORS` section. Extra columns are ignored.

| firstname | lastname | email | phone | message | gender | experience | date | profession | tools | continent | photo |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Noor | Khan | noor@test.com | 1234567890 | Testing… | Male | 3 | 05/20/2026 | Manual Tester | Selenium Webdriver | Asia | |
| Sara | Ahmed | sara@test.com | 0987654321 | Looking… | Female | 5 | 06/15/2026 | Automation Tester | QTP,Selenium IDE | Europe | |

**Multi-value checkboxes**: separate labels with a comma in the same cell.

---

## 📋 Output Report (`logs/output_report.csv`)

| row | fullname | email | attempts | status | error_message | timestamp |
|---|---|---|---|---|---|---|
| 1 | Noor Khan | noor@test.com | 1 | SUCCESS | | 2025-01-01 10:00:05 |
| 2 | Sara Ahmed | sara@test.com | 3 | FAILED | Timeout: … | 2025-01-01 10:00:22 |

---

## 📸 Screenshots

Every failed attempt saves a screenshot:

```
screenshots/
└── row_0002_error.png
```

Useful for debugging selector mismatches, CAPTCHAs, or unexpected page states.

---

## ♻️ Resume After Crash

After each successful submission, `progress.json` is updated:

```json
{
  "last_completed_row": 3,
  "saved_at": "2025-01-01T10:01:45"
}
```

Re-run `python main.py` and confirm the resume prompt to skip already-processed rows. Delete `progress.json` to start over.

---

## 🛠 Troubleshooting

| Problem | Solution |
|---|---|
| ChromeDriver version error | `pip install -U webdriver-manager` |
| Element not found | Update the CSS selector in `config.py` |
| Radio/checkbox not clickable | The bot uses JS click — check selector targets `<input>`, not `<label>` |
| Dropdown option not found | Ensure the visible text in Excel exactly matches the `<option>` text |
| CAPTCHA triggered | Increase delay values or set `HEADLESS = False` to debug visually |
| Submit verification always fails | Add the correct success element to `SUBMIT_SUCCESS_SELECTORS` |

---

## 🔒 Ethical Use

Use this tool only against forms you own or have explicit permission to automate. Always respect a site's Terms of Service and `robots.txt`.

---

## 📄 License

MIT — free to use, modify, and distribute.
