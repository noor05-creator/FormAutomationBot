"""
form_bot.py — Core Selenium automation engine for the Form Auto-Filler Bot v2.

New in v2:
  • Handles all form element types: text / textarea / date, radio buttons,
    checkboxes (multi-value), <select> dropdowns, and file uploads.
  • Reads the nested FIELD_SELECTORS structure from config.py.
  • Automatic retry with configurable attempt count.
  • Screenshot capture on failure (saved to SCREENSHOTS_DIR).
  • Submit verification: waits for URL change or success element.
  • Human-like delays throughout.
"""

import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Optional

from selenium import webdriver
from selenium.common.exceptions import (
    ElementNotInteractableException,
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from config import (
    FIELD_SELECTORS,
    HEADLESS,
    IMPLICIT_WAIT_SECONDS,
    MAX_ATTEMPTS,
    MAX_FIELD_DELAY,
    MAX_ROW_DELAY,
    MAX_SUBMIT_DELAY,
    MAX_TYPING_DELAY,
    MIN_FIELD_DELAY,
    MIN_ROW_DELAY,
    MIN_SUBMIT_DELAY,
    MIN_TYPING_DELAY,
    PAGE_LOAD_TIMEOUT,
    RETRY_DELAY,
    SCREENSHOTS_DIR,
    SUBMIT_BUTTON_SELECTOR,
    SUBMIT_SUCCESS_SELECTORS,
    SUBMIT_VERIFY_TIMEOUT,
    TARGET_URL,
    VERIFY_SUBMISSION,
)
from utils import human_delay


class FormBot:
    """
    Selenium-powered bot that reads nested field selectors from config.py,
    detects each field's interaction type, and fills / submits a web form
    for every data row supplied by the caller.

    Supported field types
    ─────────────────────
    text_fields     → clear + human-like typing
    radio_fields    → JS-assisted click on the correct option
    checkbox_fields → comma-separated multi-value, click each option
    dropdown_fields → Selenium Select.select_by_visible_text()
    file_fields     → send_keys(absolute_path)

    Usage
    ─────
    bot = FormBot(logger)
    bot.start()
    for row_number, row_dict in enumerate(rows, 1):
        success, error, attempts = bot.fill_and_submit(row_dict, row_number)
    bot.quit()
    """

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.driver: Optional[webdriver.Chrome] = None
        self.wait:   Optional[WebDriverWait]    = None

    # ══════════════════════════════════════════════════════════════════════════
    # Browser lifecycle
    # ══════════════════════════════════════════════════════════════════════════

    def start(self) -> None:
        """
        Initialise a Chrome browser instance with anti-detection options.

        Uses webdriver-manager to auto-download the matching ChromeDriver.
        Falls back to a system-level chromedriver if webdriver-manager fails.
        """
        self.logger.info("Starting Chrome browser …")

        options = Options()

        if HEADLESS:
            options.add_argument("--headless=new")
            self.logger.info("Headless mode ON")

        # Anti-detection flags
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-infobars")
        options.add_argument("--start-maximized")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # IMPORTANT: "eager" stops Selenium waiting as soon as the DOM is
        # interactive — it no longer waits for ads/trackers to finish loading.
        # This fixes the renderer timeout on ad-heavy pages like techlistic.com
        # where background scripts never fully complete.
        options.page_load_strategy = "eager"

        try:
            from webdriver_manager.chrome import ChromeDriverManager
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options,
            )
        except Exception:
            self.logger.warning(
                "webdriver-manager failed; using system chromedriver."
            )
            self.driver = webdriver.Chrome(options=options)

        # Remove the Selenium navigator.webdriver fingerprint at runtime.
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', "
                       "{get: () => undefined})"},
        )

        self.driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        self.driver.implicitly_wait(IMPLICIT_WAIT_SECONDS)
        self.wait = WebDriverWait(self.driver, IMPLICIT_WAIT_SECONDS)

        self.logger.info("Browser ready.")

    def quit(self) -> None:
        """Close the browser and release all WebDriver resources."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.logger.info("Browser closed.")

    # ══════════════════════════════════════════════════════════════════════════
    # Internal navigation
    # ══════════════════════════════════════════════════════════════════════════

    def _navigate_to_form(self) -> None:
        """
        Load TARGET_URL, wait for the first form field to appear in the DOM,
        then scroll it into the centre of the viewport so that ad banners
        at the top of the page are no longer covering it.
        """
        self.logger.debug("Navigating to %s", TARGET_URL)
        self.driver.get(TARGET_URL)

        # Wait for the first text field to exist in the DOM.
        text_fields = FIELD_SELECTORS.get("text_fields", {})
        first_selector = next(iter(text_fields.values()), "input")
        self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, first_selector))
        )

        # Extra settle time — this page loads 15 ad iframes which saturate
        # CPU/memory. Without this pause ChromeDriver times out trying to
        # send commands while the browser is still busy with ads.
        time.sleep(4.0)

        # Scroll the first field into the centre of the viewport so ad
        # banners at the top of the page are above the visible area.
        first_el = self.driver.find_element(By.CSS_SELECTOR, first_selector)
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", first_el
        )
        time.sleep(random.uniform(1.0, 1.5))
        self.logger.debug("Form is ready — scrolled to first field.")

    # ══════════════════════════════════════════════════════════════════════════
    # Human-like typing
    # ══════════════════════════════════════════════════════════════════════════

    def _type_like_human(self, element: Any, text: str) -> None:
        """
        Send each character of *text* to *element* one at a time, inserting a
        random inter-keystroke delay to mimic realistic typing speed.

        Parameters
        ----------
        element : WebElement
            The focused input or textarea to type into.
        text : str
            The string to enter.
        """
        for char in str(text):
            element.send_keys(char)
            human_delay(MIN_TYPING_DELAY, MAX_TYPING_DELAY)

    # ══════════════════════════════════════════════════════════════════════════
    # Field-type handlers
    # ══════════════════════════════════════════════════════════════════════════

    def _scroll_into_view(self, element: Any) -> None:
        """Scroll *element* to the centre of the viewport."""
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', inline:'nearest'});",
            element,
        )
        time.sleep(0.2)

    def _fill_text_field(self, selector: str, value: str) -> None:
        """
        Locate a text input or textarea by CSS *selector*, clear it, and type
        *value* character-by-character with human-like delays.

        Parameters
        ----------
        selector : str
            CSS selector pointing to the <input> or <textarea>.
        value : str
            Text to enter.
        """
        element = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
        )
        self._scroll_into_view(element)
        element.click()
        element.clear()
        self._type_like_human(element, value)
        self.logger.debug("  text field '%s' ← '%s'", selector, value)

    def _select_radio_option(
        self,
        field_name: str,
        options_map: dict[str, str],
        value: str,
    ) -> None:
        """
        Click the radio button whose label matches *value*.

        Radio buttons are often styled so the <input> is hidden; we click via
        JavaScript to bypass visibility constraints.

        Parameters
        ----------
        field_name : str
            Logical field name (used in log messages).
        options_map : dict[str, str]
            Mapping of { label: css_selector } from FIELD_SELECTORS.
        value : str
            The label to select (e.g. "Male").
        """
        value = value.strip()
        selector = options_map.get(value)
        if not selector:
            self.logger.warning(
                "  radio '%s': no selector for value '%s'. "
                "Valid options: %s", field_name, value, list(options_map.keys())
            )
            return

        element = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
        self._scroll_into_view(element)

        # JavaScript click bypasses "element not interactable" on hidden radios.
        self.driver.execute_script("arguments[0].click();", element)
        self.logger.debug("  radio '%s' ← '%s'", field_name, value)

    def _select_checkbox_option(
        self,
        field_name: str,
        options_map: dict[str, str],
        value: str,
    ) -> None:
        """
        Tick one or more checkboxes based on the comma-separated *value*.

        For each token in *value*, the corresponding checkbox is checked if it
        is not already selected.

        Parameters
        ----------
        field_name : str
            Logical field name (used in log messages).
        options_map : dict[str, str]
            Mapping of { label: css_selector }.
        value : str
            Comma-separated labels (e.g. "QTP,Selenium Webdriver").
        """
        # Split on commas, strip whitespace from each token.
        chosen = [v.strip() for v in value.split(",") if v.strip()]

        for label in chosen:
            selector = options_map.get(label)
            if not selector:
                self.logger.warning(
                    "  checkbox '%s': no selector for value '%s'. "
                    "Valid options: %s", field_name, label, list(options_map.keys())
                )
                continue

            element = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            self._scroll_into_view(element)

            # Only click if not already checked.
            if not element.is_selected():
                self.driver.execute_script("arguments[0].click();", element)
                self.logger.debug(
                    "  checkbox '%s' ← '%s' checked", field_name, label
                )
            else:
                self.logger.debug(
                    "  checkbox '%s' ← '%s' already checked — skipping",
                    field_name, label,
                )
            human_delay(0.1, 0.3)

    def _select_dropdown_option(self, selector: str, value: str) -> None:
        """
        Open a <select> dropdown and choose the option whose visible text
        matches *value* (case-sensitive, using Selenium's Select class).

        Parameters
        ----------
        selector : str
            CSS selector for the <select> element.
        value : str
            Visible option text to select (e.g. "Asia").
        """
        element = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
        )
        self._scroll_into_view(element)

        select = Select(element)
        try:
            select.select_by_visible_text(value.strip())
            self.logger.debug("  dropdown '%s' ← '%s'", selector, value)
        except NoSuchElementException:
            # Fallback: try partial / case-insensitive match.
            opts = [o.text for o in select.options]
            match = next(
                (o for o in opts if o.strip().lower() == value.strip().lower()),
                None,
            )
            if match:
                select.select_by_visible_text(match)
                self.logger.debug(
                    "  dropdown '%s' ← '%s' (fuzzy match)", selector, match
                )
            else:
                self.logger.warning(
                    "  dropdown '%s': option '%s' not found. "
                    "Available: %s", selector, value, opts
                )

    def _upload_file(self, selector: str, file_path: str) -> None:
        """
        Interact with a file-upload input by sending the absolute file path
        directly via send_keys().  No browser dialog is opened.

        Parameters
        ----------
        selector : str
            CSS selector for the <input type="file"> element.
        file_path : str
            Absolute or relative path to the file to upload.
        """
        abs_path = str(Path(file_path).resolve())
        if not Path(abs_path).exists():
            self.logger.warning(
                "  file upload '%s': file not found at '%s'", selector, abs_path
            )
            return

        # File inputs must be visible for send_keys; use JS to unhide if needed.
        element = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
        self.driver.execute_script(
            "arguments[0].style.display='block'; "
            "arguments[0].style.visibility='visible';",
            element,
        )
        element.send_keys(abs_path)
        self.logger.debug("  file upload '%s' ← '%s'", selector, abs_path)

    # ══════════════════════════════════════════════════════════════════════════
    # Field dispatcher
    # ══════════════════════════════════════════════════════════════════════════

    def _fill_field(self, field_type: str, field_name: str, field_config: Any, value: str) -> None:
        """
        Route a single field-filling operation to the correct handler based on
        *field_type* (the key of the outer dict in FIELD_SELECTORS).

        Parameters
        ----------
        field_type : str
            One of: "text_fields", "radio_fields", "checkbox_fields",
            "dropdown_fields", "file_fields".
        field_name : str
            Column name from the input file (e.g. "gender").
        field_config : str | dict
            For text / dropdown / file types: a CSS selector string.
            For radio / checkbox types: a dict of { label: selector }.
        value : str
            The raw cell value from the data row.
        """
        if not value:
            self.logger.debug("  field '%s' is empty — skipping.", field_name)
            return

        if field_type == "text_fields":
            self._fill_text_field(field_config, value)

        elif field_type == "radio_fields":
            self._select_radio_option(field_name, field_config, value)

        elif field_type == "checkbox_fields":
            self._select_checkbox_option(field_name, field_config, value)

        elif field_type == "dropdown_fields":
            self._select_dropdown_option(field_config, value)

        elif field_type == "file_fields":
            self._upload_file(field_config, value)

        else:
            self.logger.warning(
                "Unknown field type '%s' for field '%s' — skipping.",
                field_type, field_name,
            )

        # Brief inter-field pause to appear human.
        human_delay(MIN_FIELD_DELAY, MAX_FIELD_DELAY)

    # ══════════════════════════════════════════════════════════════════════════
    # Form filling
    # ══════════════════════════════════════════════════════════════════════════

    def _fill_all_fields(self, row: dict) -> None:
        """
        Iterate over every section and every field in FIELD_SELECTORS and
        call the appropriate handler for each field whose column is present
        in *row*.

        Parameters
        ----------
        row : dict
            One data record from the input DataFrame.
        """
        for field_type, fields in FIELD_SELECTORS.items():
            for field_name, field_config in fields.items():
                value = row.get(field_name, "").strip()
                self.logger.debug(
                    "Processing field_type='%s'  field='%s'  value='%s'",
                    field_type, field_name, value,
                )
                self._fill_field(field_type, field_name, field_config, value)

    # ══════════════════════════════════════════════════════════════════════════
    # Submit & verify
    # ══════════════════════════════════════════════════════════════════════════

    def _dismiss_overlays(self) -> None:
        """
        Attempt to close any popup ads or overlay dialogs that might be
        covering the submit button.

        Strategy:
          1. Press Escape — closes most modal/interstitial ads.
          2. Look for common ad close-button selectors and click them.
          3. If an iframe ad is focused, switch back to the main document.

        This method never raises — if dismissal fails it logs a warning and
        lets the submit attempt proceed anyway (JS click bypasses overlays).
        """
        from selenium.webdriver.common.keys import Keys

        try:
            # Step 1: Press Escape to dismiss modal-style ads.
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.5)
            self.logger.debug("Escape sent to dismiss potential overlays.")
        except Exception:
            pass

        # Step 2: Try clicking common ad close / dismiss buttons.
        close_selectors = [
            "[id*='dismiss']", "[class*='dismiss']",
            "[id*='close']",   "[class*='close-btn']",
            "[aria-label='Close']", "[aria-label='close']",
            "button[class*='modal']",
        ]
        for sel in close_selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    btn.click()
                    self.logger.debug("Closed overlay via selector: %s", sel)
                    time.sleep(0.4)
                    break
            except Exception:
                continue

        # Step 3: Switch back to default content in case an iframe is focused.
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass

    def _submit_form(self) -> None:
        """
        Dismiss any overlay ads, then click the submit button using a
        JavaScript click so that popup overlays cannot intercept it.

        JavaScript click bypasses the "element click intercepted" error that
        occurs when an ad or modal sits on top of the submit button — as seen
        on techlistic.com where a full-screen ad appears near the bottom of
        the page.
        """
        # Attempt to close any overlay ads before clicking submit.
        self._dismiss_overlays()

        btn = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, SUBMIT_BUTTON_SELECTOR))
        )
        self._scroll_into_view(btn)

        # JS click bypasses any remaining overlay that normal click cannot.
        self.driver.execute_script("arguments[0].click();", btn)
        self.logger.debug("Submit button clicked via JavaScript.")
        human_delay(MIN_SUBMIT_DELAY, MAX_SUBMIT_DELAY)

    def _verify_submission(self, url_before: str) -> bool:
        """
        Determine whether the form submission succeeded by checking for:
          1. A URL change (navigated away from the form page).
          2. A success element matching any of SUBMIT_SUCCESS_SELECTORS.

        Parameters
        ----------
        url_before : str
            The page URL captured immediately before clicking submit.

        Returns
        -------
        bool
            True if submission appears successful, False otherwise.
        """
        try:
            verify_wait = WebDriverWait(self.driver, SUBMIT_VERIFY_TIMEOUT)

            # Check 1: URL changed — most reliable indicator of a page submit.
            try:
                verify_wait.until(EC.url_changes(url_before))
                self.logger.debug(
                    "Submit verified via URL change: %s → %s",
                    url_before, self.driver.current_url,
                )
                return True
            except TimeoutException:
                pass   # URL did not change within timeout; try next check.

            # Check 2: A success element appeared on the page.
            for sel in SUBMIT_SUCCESS_SELECTORS:
                try:
                    verify_wait.until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, sel))
                    )
                    self.logger.debug(
                        "Submit verified via success element: '%s'", sel
                    )
                    return True
                except TimeoutException:
                    continue

            self.logger.warning(
                "Submit verification failed: no URL change or success element "
                "detected within %ds.", SUBMIT_VERIFY_TIMEOUT
            )
            return False

        except Exception as exc:
            self.logger.warning("Submit verification error: %s", exc)
            return False

    # ══════════════════════════════════════════════════════════════════════════
    # Screenshot on failure
    # ══════════════════════════════════════════════════════════════════════════

    def _save_screenshot(self, row_number: int) -> Optional[str]:
        """
        Capture the current browser viewport and save it to SCREENSHOTS_DIR.

        Parameters
        ----------
        row_number : int
            1-based row index used in the filename.

        Returns
        -------
        str | None
            Absolute path of the saved PNG, or None if capture failed.
        """
        try:
            Path(SCREENSHOTS_DIR).mkdir(parents=True, exist_ok=True)
            filename = Path(SCREENSHOTS_DIR) / f"row_{row_number:04d}_error.png"
            self.driver.save_screenshot(str(filename))
            self.logger.info("Screenshot saved → %s", filename)
            return str(filename)
        except Exception as exc:
            self.logger.warning("Failed to capture screenshot: %s", exc)
            return None

    # ══════════════════════════════════════════════════════════════════════════
    # Single-attempt submission
    # ══════════════════════════════════════════════════════════════════════════

    def _attempt_submission(self, row: dict, row_number: int) -> tuple[bool, str]:
        """
        Perform one full form-fill-and-submit cycle for the given *row*.

        Returns
        -------
        (success: bool, error_message: str)
        """
        self._navigate_to_form()

        # Record URL before submit for change-detection.
        url_before = self.driver.current_url

        self._fill_all_fields(row)
        self._submit_form()

        # Verify submission outcome.
        # VERIFY_SUBMISSION=False skips verification for static/demo forms
        # that give no feedback (no URL change, no success element).
        if not VERIFY_SUBMISSION:
            self.logger.debug(
                "Verification skipped (VERIFY_SUBMISSION=False) — "
                "treating successful click as success."
            )
            return True, ""

        verified = self._verify_submission(url_before)
        if not verified:
            return False, "Submit verification failed (no URL change or success element)."

        return True, ""

    # ══════════════════════════════════════════════════════════════════════════
    # Public API — fill_and_submit with retry
    # ══════════════════════════════════════════════════════════════════════════

    def fill_and_submit(
        self,
        row: dict,
        row_number: int,
        display_name: str = "",
    ) -> tuple[bool, str, int]:
        """
        Fill and submit the form for one data row, retrying up to MAX_ATTEMPTS
        times on failure.  A screenshot is saved after each failed attempt.

        Parameters
        ----------
        row : dict
            A single data record from the input DataFrame.
        row_number : int
            1-based row index (for logging and screenshot naming).
        display_name : str
            Human-readable name for log messages (e.g. "Alice Johnson").

        Returns
        -------
        (success: bool, final_error: str, attempts_made: int)
        """
        label = display_name or f"Row {row_number}"
        self.logger.info(
            "─── Row %d: %s ───────────────────────────────────",
            row_number, label,
        )

        last_error = ""

        for attempt in range(1, MAX_ATTEMPTS + 1):
            if attempt > 1:
                self.logger.info(
                    "  ↩ Retry %d/%d for row %d …", attempt, MAX_ATTEMPTS, row_number
                )
                time.sleep(RETRY_DELAY)

            try:
                success, error = self._attempt_submission(row, row_number)

                if success:
                    self.logger.info(
                        "✔ Row %d (%s) succeeded on attempt %d/%d.",
                        row_number, label, attempt, MAX_ATTEMPTS,
                    )
                    human_delay(MIN_ROW_DELAY, MAX_ROW_DELAY)
                    return True, "", attempt

                # Submission detected but verify step failed.
                last_error = error
                self.logger.warning(
                    "  Attempt %d/%d — verification failed: %s",
                    attempt, MAX_ATTEMPTS, error,
                )
                self._save_screenshot(row_number)

            except TimeoutException as exc:
                last_error = f"Timeout: {exc.msg}"
                self.logger.error(
                    "  Attempt %d/%d — %s", attempt, MAX_ATTEMPTS, last_error
                )
                self._save_screenshot(row_number)

            except NoSuchElementException as exc:
                last_error = f"Element not found: {exc.msg}"
                self.logger.error(
                    "  Attempt %d/%d — %s", attempt, MAX_ATTEMPTS, last_error
                )
                self._save_screenshot(row_number)

            except ElementNotInteractableException as exc:
                last_error = f"Element not interactable: {exc.msg}"
                self.logger.error(
                    "  Attempt %d/%d — %s", attempt, MAX_ATTEMPTS, last_error
                )
                self._save_screenshot(row_number)

            except ElementClickInterceptedException as exc:
                last_error = f"Click intercepted: {exc.msg}"
                self.logger.error(
                    "  Attempt %d/%d — %s", attempt, MAX_ATTEMPTS, last_error
                )
                self._save_screenshot(row_number)

            except StaleElementReferenceException as exc:
                last_error = f"Stale element: {exc.msg}"
                self.logger.error(
                    "  Attempt %d/%d — %s", attempt, MAX_ATTEMPTS, last_error
                )
                self._save_screenshot(row_number)

            except WebDriverException as exc:
                last_error = f"WebDriver error: {exc.msg}"
                self.logger.error(
                    "  Attempt %d/%d — %s", attempt, MAX_ATTEMPTS, last_error
                )
                self._save_screenshot(row_number)

            except Exception as exc:   # noqa: BLE001 — broad catch so run continues
                last_error = f"Unexpected error: {exc}"
                self.logger.exception(
                    "  Attempt %d/%d — %s", attempt, MAX_ATTEMPTS, last_error
                )
                self._save_screenshot(row_number)

                # ConnectionResetError / ConnectionRefusedError means Chrome
                # crashed or ChromeDriver died.  Restart the browser so the
                # remaining attempts and rows can still be processed.
                err_str = str(exc).lower()
                if "connection" in err_str and attempt < MAX_ATTEMPTS:
                    self.logger.warning(
                        "Browser connection lost — restarting Chrome for retry …"
                    )
                    try:
                        self.quit()
                    except Exception:
                        pass
                    time.sleep(2)
                    self.start()

        # All attempts exhausted.
        self.logger.error(
            "✘ Row %d (%s) FAILED after %d attempt(s). Last error: %s",
            row_number, label, MAX_ATTEMPTS, last_error,
        )
        return False, last_error, MAX_ATTEMPTS