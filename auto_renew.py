"""Read-only TickHosting session and verification diagnostic.

This script NEVER clicks the Renew Server button or attempts to solve a CAPTCHA.
Configure PTERODACTYL_SESSION in GitHub repository Actions secrets.
"""

import os
import sys
import time
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "https://tickhosting.com"
SERVER_URL = "https://tickhosting.com/server/1f3d4eea/info"
SESSION_COOKIE = os.getenv("PTERODACTYL_SESSION", "").strip()
WAIT_SECONDS = int(os.getenv("CHECK_WAIT_SECONDS", "35"))


def make_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,1000")
    options.add_argument("--disable-gpu")
    return webdriver.Chrome(options=options)


def safe_url(driver):
    """Print only the URL path, never tokens or query parameters."""
    parsed = urlparse(driver.current_url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def visible_text(driver):
    try:
        return driver.find_element(By.TAG_NAME, "body").text.lower()
    except WebDriverException:
        return ""


def inspect(driver):
    """Observe visible UI only; does not manipulate verification."""
    text = visible_text(driver)
    frames = driver.find_elements(By.CSS_SELECTOR, "iframe")
    turnstile_frames = [
        frame for frame in frames
        if any(word in ((frame.get_attribute("src") or "") + " " +
                        (frame.get_attribute("title") or "")).lower()
               for word in ("challenges.cloudflare.com", "turnstile", "cloudflare"))
    ]
    renew_buttons = [
        el for el in driver.find_elements(By.CSS_SELECTOR, "button")
        if el.is_displayed() and "renew server" in el.text.lower()
    ]
    renew_enabled = any(el.is_enabled() for el in renew_buttons)
    return {
        "login_redirect": "/auth/login" in urlparse(driver.current_url).path,
        "renew_button_visible": bool(renew_buttons),
        "renew_button_enabled": renew_enabled,
        "turnstile_iframes": len(turnstile_frames),
        "verification_success_text": ("success!" in text or "verification successful" in text),
        "verification_prompt_text": any(p in text for p in (
            "verify you are human", "checking your browser", "verify that you are human"
        )),
        "page_has_renewal_section": "renew server" in text,
    }


def main():
    if not SESSION_COOKIE:
        print("ERROR: Add PTERODACTYL_SESSION in GitHub Actions repository secrets.")
        return 1

    driver = None
    try:
        driver = make_driver()
        driver.set_page_load_timeout(40)
        # Must first visit the domain before Selenium will accept its cookie.
        driver.get(BASE_URL)
        driver.add_cookie({
            "name": "pterodactyl_panel_session",
            "value": SESSION_COOKIE,
            "domain": "tickhosting.com",
            "path": "/",
            "secure": True,
        })
        driver.get(SERVER_URL)
        try:
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            print("Page load did not fully complete; checking visible state anyway.")

        # Allow automatic Cloudflare verification to occur on its own.
        deadline = time.monotonic() + max(0, WAIT_SECONDS)
        result = inspect(driver)
        while time.monotonic() < deadline and not result["renew_button_visible"]:
            time.sleep(3)
            result = inspect(driver)

        print("Page:", safe_url(driver))
        print("Renewal section detected:", result["page_has_renewal_section"])
        print("Renew Server button visible:", result["renew_button_visible"])
        print("Renew Server button enabled:", result["renew_button_enabled"])
        print("Cloudflare-related frames observed:", result["turnstile_iframes"])
        print("Visible verification-success text:", result["verification_success_text"])
        print("Visible verification-prompt text:", result["verification_prompt_text"])

        if result["login_redirect"]:
            print("RESULT: Not authenticated. Cookie may have expired or apply to another site/session.")
            return 2
        if result["renew_button_visible"]:
            print("RESULT: Renewal UI accessible. CAPTCHA acceptance is NOT confirmed by button visibility.")
            return 0
        print("RESULT: Renewal UI not found. Could be login, Cloudflare, page changes, or loading.")
        return 3
    except WebDriverException as exc:
        print("Browser error:", type(exc).__name__)
        return 4
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    sys.exit(main())

