"""Outlook Account Batch Registrar

Automates Outlook/Hotmail account creation via signup.live.com using DrissionPage.
Uses cloud FunCaptcha solver (YesCaptcha/CapSolver) for Arkose Labs captcha.

Flow:
  1. Open https://signup.live.com/signup
  2. Choose outlook.com domain, enter desired username
  3. Enter password, first name, last name, birth date
  4. Detect FunCaptcha iframe, solve via cloud API, inject token
  5. Save email:password to output

Usage:
    python -m register.outlook_register --count 5 --threads 1
    python -m register.outlook_register --count 10 --proxy "http://user:pass@host:port"

Requires:
  - CAPTCHA_CLIENT_KEY for FunCaptcha cloud solving
  - Chrome/Chromium
  - Xvfb on headless servers (export DISPLAY=:99)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import secrets
import string
import threading
import time
import traceback
import urllib.parse
import zipfile
from datetime import datetime, timezone
from typing import Optional

try:
    from DrissionPage import Chromium, ChromiumOptions
except ImportError:
    Chromium = None
    ChromiumOptions = None

import requests

from register.captcha import FunCaptchaService

SITE_URL = "https://signup.live.com/signup"
_STAGING_DIR = "output/.staging_outlook"
_output_lock = threading.Lock()

DEFAULT_FUNCAPTCHA_PK = os.environ.get(
    "FUNCAPTCHA_PUBLIC_KEY", "B7D8911C-5CC8-A9A3-35B0-554ACEE604DA"
)

FIRST_NAMES = [
    "Alex", "Chris", "Jordan", "Taylor", "Morgan", "Sam", "Casey",
    "Riley", "Quinn", "Avery", "Drew", "Blake", "Parker", "Reese",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson", "Thomas",
]


def _random_name() -> tuple[str, str]:
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)


def _random_password() -> str:
    """Generate password meeting Microsoft requirements (8+ chars, upper, lower, digit, symbol)."""
    upper = "".join(random.choices(string.ascii_uppercase, k=2))
    lower = "".join(random.choices(string.ascii_lowercase, k=4))
    digit = "".join(random.choices(string.digits, k=2))
    sym = random.choice("!@#$%&*")
    return "".join(random.sample(upper + lower + digit + sym, 9))


def _random_username() -> str:
    return secrets.token_hex(6) + str(random.randint(100, 999))


def _check_email_available(email: str) -> bool:
    """Check if email is available via Microsoft's API."""
    try:
        r = requests.post(
            "https://signup.live.com/API/CheckAvailableSigninName",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://signup.live.com",
                "Referer": SITE_URL,
            },
            json={"signInName": email, "includeSuggestions": False},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("isAvailable", False)
    except Exception:
        pass
    return False


def _setup_proxy_auth(tab, username: str, password: str) -> None:
    """Register CDP Fetch.authRequired handler for proxy authentication.

    Uses Chrome DevTools Protocol instead of MV2 extensions (deprecated in Chrome 127+).
    Fetch.enable intercepts all requests; we must handle both requestPaused (continue)
    and authRequired (provide credentials).
    """
    def _on_request_paused(**kwargs):
        request_id = kwargs.get("requestId")
        if not request_id:
            return
        try:
            tab.run_cdp("Fetch.continueRequest", requestId=request_id)
        except Exception:
            pass

    def _on_auth_required(**kwargs):
        request_id = kwargs.get("requestId")
        if not request_id:
            return
        try:
            tab.run_cdp("Fetch.continueWithAuth", requestId=request_id,
                        authChallengeResponse={
                            "response": "ProvideCredentials",
                            "username": username,
                            "password": password,
                        })
        except Exception:
            try:
                tab.run_cdp("Fetch.continueWithAuth", requestId=request_id,
                            authChallengeResponse={"response": "CancelAuth"})
            except Exception:
                pass

    tab._driver.set_callback("Fetch.requestPaused", _on_request_paused, immediate=True)
    tab._driver.set_callback("Fetch.authRequired", _on_auth_required, immediate=True)
    tab.run_cdp("Fetch.enable", handleAuthRequests=True)


def _save_staged(content: str) -> str:
    os.makedirs(_STAGING_DIR, exist_ok=True)
    fname = os.path.join(_STAGING_DIR, f"outlook_{int(time.time())}_{secrets.token_hex(4)}.json")
    with _output_lock:
        with open(fname, "w", encoding="utf-8") as f:
            f.write(content)
    return fname


def _detect_funcaptcha_iframe(page) -> Optional[str]:
    """Detect FunCaptcha iframe and extract public key from its src URL.

    Returns the public key if found, else None.
    """
    try:
        html = page.html
        # Look for Arkose Labs iframe src containing pk= parameter
        m = re.search(
            r'src="[^"]*(?:arkoselabs\.com|funcaptcha\.com)[^"]*[?&]pk=([A-F0-9-]+)',
            html, re.IGNORECASE,
        )
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _inject_funcaptcha_token(page, token: str) -> bool:
    """Inject solved FunCaptcha token via JS callback."""
    try:
        page.run_js(f"""
            // Try standard Arkose callback
            if (typeof window.ArkoseEnforcement !== 'undefined' &&
                typeof window.ArkoseEnforcement.setToken === 'function') {{
                window.ArkoseEnforcement.setToken('{token}');
            }}
            // Try enforcement callback
            if (typeof window.parent !== 'undefined') {{
                try {{
                    var frames = document.querySelectorAll('iframe');
                    frames.forEach(function(f) {{
                        try {{ f.contentWindow.postMessage(JSON.stringify({{
                            eventId: 'challenge-complete',
                            payload: {{ sessionToken: '{token}' }}
                        }}), '*'); }} catch(e) {{}}
                    }});
                }} catch(e) {{}}
            }}
            // Direct callback approach
            if (typeof window.setupEnforcementCallback === 'function') {{
                window.setupEnforcementCallback({{ token: '{token}' }});
            }}
            // Generic arkose completed callback
            var callbacks = ['arkoseCallback', 'onCompleted', 'arkose_callback',
                           'enforcement_callback', 'captchaCallback'];
            for (var i = 0; i < callbacks.length; i++) {{
                if (typeof window[callbacks[i]] === 'function') {{
                    window[callbacks[i]]({{ token: '{token}' }});
                    break;
                }}
            }}
        """)
        return True
    except Exception as exc:
        print(f"[Captcha] Token injection error: {exc}")
        return False


def register_one(tid: int, proxy: Optional[str] = None, captcha_svc: Optional[FunCaptchaService] = None) -> Optional[str]:
    """Register one Outlook account. Returns JSON string with email, password on success."""
    if not Chromium or not ChromiumOptions:
        print("[Error] DrissionPage not installed. pip install DrissionPage")
        return None

    proxy_user = ""
    proxy_pass = ""
    co = ChromiumOptions()
    co.auto_port()
    co.set_timeouts(base=10)
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--window-size=1920,1080")
    co.set_argument("--lang=en")

    if proxy:
        try:
            parsed = urllib.parse.urlparse(proxy)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8080
            proxy_user = parsed.username or ""
            proxy_pass = parsed.password or ""
            scheme = parsed.scheme or "http"
            co.set_proxy(f"{scheme}://{host}:{port}")
        except Exception as exc:
            print(f"[T{tid}] Proxy parse error: {exc}")

    browser = None
    try:
        browser = Chromium(co)
        page = browser.get_tabs()[-1]

        # Set up CDP proxy authentication if needed
        if proxy_user and proxy_pass:
            _setup_proxy_auth(page, proxy_user, proxy_pass)
            print(f"[T{tid}] Proxy auth configured via CDP")

        page.get(SITE_URL)
        time.sleep(4)

        # Debug: save page state for troubleshooting
        try:
            os.makedirs("output", exist_ok=True)
            page.get_screenshot(path="output/debug_signup_page.png", full_page=True)
            with open("output/debug_signup_page.html", "w", encoding="utf-8") as f:
                f.write(page.html or "")
            print(f"[T{tid}] Page URL: {page.url}")
            print(f"[T{tid}] Page title: {page.title}")
        except Exception as dbg_exc:
            print(f"[T{tid}] Debug screenshot failed: {dbg_exc}")

        # --- Helper: set input value via React-safe setter ---
        def _set_input(selector: str, value: str) -> bool:
            return page.run_js(f"""
                const el = document.querySelector('{selector}');
                if (!el) return false;
                el.focus();
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(el, '{value}');
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            """)

        def _click_next() -> None:
            btn = page.ele('css:button[data-testid="primaryButton"]', timeout=15)
            btn.click()

        # --- Step 1: Enter full email address ---
        email_available = False
        for _ in range(10):
            username = _random_username()
            email_addr = f"{username}@outlook.com"
            if _check_email_available(email_addr):
                email_available = True
                print(f"[T{tid}] Email {email_addr} available")
                break
            time.sleep(2)

        if not email_available:
            username = _random_username()
            email_addr = f"{username}@outlook.com"
            print(f"[T{tid}] Using {email_addr} (availability check skipped)")

        _set_input('input[name="Email"], input[type="email"]', email_addr)
        time.sleep(0.5)
        _click_next()
        time.sleep(3)

        # Debug: screenshot after email step
        try:
            page.get_screenshot(path="output/debug_step2.png", full_page=True)
            with open("output/debug_step2.html", "w", encoding="utf-8") as f:
                f.write(page.html or "")
            print(f"[T{tid}] Step 2 URL: {page.url}")
        except Exception:
            pass

        # --- Step 2: Enter password ---
        password = _random_password()
        _set_input('input[name="Password"], input[type="password"]', password)
        time.sleep(0.5)
        _click_next()
        time.sleep(3)

        # Handle password rejection — retry with new password
        try:
            err = page.ele('css:[data-testid="errorMessage"], [role="alert"]', timeout=2)
            if err and err.text:
                print(f"[T{tid}] Password rejected: {err.text[:60]}. Retrying...")
                password = _random_password()
                page.run_js("document.querySelector('input[type=\"password\"]').value = ''")
                time.sleep(0.3)
                _set_input('input[name="Password"], input[type="password"]', password)
                time.sleep(0.5)
                _click_next()
                time.sleep(3)
        except Exception:
            pass

        # Debug: screenshot after password step
        try:
            page.get_screenshot(path="output/debug_step3.png", full_page=True)
            with open("output/debug_step3.html", "w", encoding="utf-8") as f:
                f.write(page.html or "")
            print(f"[T{tid}] Step 3 URL: {page.url}")
        except Exception:
            pass

        # --- Step 3: Birth date (new Fluent UI combines country + DOB, no name step) ---
        year = random.randint(1975, 2000)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        # New Fluent UI uses select dropdowns or input fields with name attributes
        page.run_js(f"""
            (function() {{
                function setSelect(sel, val) {{
                    var el = document.querySelector(sel);
                    if (el) {{
                        el.value = String(val);
                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                        el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    }}
                }}
                setSelect('#BirthMonth, select[name="BirthMonth"]', '{month}');
                setSelect('#BirthDay, select[name="BirthDay"]', '{day}');
                setSelect('#BirthYear, select[name="BirthYear"]', '{year}');
                var yearInput = document.querySelector('input[name="BirthYear"]');
                if (yearInput) {{
                    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(yearInput, '{year}');
                    yearInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                    yearInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }})();
        """)
        time.sleep(0.5)
        _click_next()
        time.sleep(3)

        # Debug: screenshot after birth date step
        try:
            page.get_screenshot(path="output/debug_step5.png", full_page=True)
            with open("output/debug_step5.html", "w", encoding="utf-8") as f:
                f.write(page.html or "")
            print(f"[T{tid}] Step 5 URL: {page.url}")
        except Exception:
            pass

        # Check for SMS verification wall
        try:
            sms_el = page.ele('css:input[name="PhoneNumber"], input[type="tel"]', timeout=5)
            if sms_el:
                print(f"[T{tid}] SMS verification required - try different proxy")
                return None
        except Exception:
            pass

        # === FunCaptcha solving via cloud API ===
        if captcha_svc:
            print(f"[T{tid}] Detecting FunCaptcha...")
            pk = None
            for attempt in range(15):
                pk = _detect_funcaptcha_iframe(page)
                if pk:
                    break
                # Check if already past captcha
                body = page.html
                if "Account successfully created" in body or "outlook.live.com" in page.url:
                    break
                time.sleep(2)

            if pk:
                print(f"[T{tid}] FunCaptcha detected, pk={pk[:12]}... Solving via cloud API...")
                token = captcha_svc.solve(
                    website_url=SITE_URL,
                    public_key=pk,
                )
                if token:
                    print(f"[T{tid}] Captcha solved, injecting token...")
                    _inject_funcaptcha_token(page, token)
                    time.sleep(5)
                else:
                    print(f"[T{tid}] Captcha solve failed")
                    return None
            else:
                # No captcha detected — might have been skipped or already done
                print(f"[T{tid}] No FunCaptcha iframe detected, continuing...")
        else:
            # No captcha service — wait and hope (legacy behavior without solver)
            print(f"[T{tid}] No captcha service configured, waiting...")
            for wait in range(120):
                body = page.html
                if "Account successfully created" in body or "outlook.live.com" in page.url:
                    break
                time.sleep(1)

        # Wait for completion
        for wait in range(30):
            try:
                # Try clicking any "Next" or "Continue" button that appears
                btn = page.ele('css:button[data-testid="primaryButton"]', timeout=3)
                if btn and btn.states.is_displayed:
                    btn.click()
                    break
            except Exception:
                pass
            body = page.html
            if "Account successfully created" in body or "outlook.live.com" in page.url:
                break
            time.sleep(1)

        time.sleep(5)
        try:
            page = browser.get_tabs()[-1]
        except Exception:
            pass

        result = json.dumps({"email": email_addr, "password": password})
        print(f"[T{tid}] SUCCESS: {email_addr}")
        return result

    except Exception as exc:
        print(f"[T{tid}] Error: {exc}")
        traceback.print_exc()
        return None
    finally:
        if browser:
            try:
                browser.quit()
            except Exception:
                pass


def bundle_output(output_dir: str = "output") -> Optional[str]:
    """Bundle staged files into MMDDOutlook.zip."""
    import shutil
    if not os.path.isdir(_STAGING_DIR):
        return None
    files = sorted(
        os.path.join(_STAGING_DIR, f)
        for f in os.listdir(_STAGING_DIR)
        if f.startswith("outlook_")
    )
    if not files:
        shutil.rmtree(_STAGING_DIR, ignore_errors=True)
        return None

    accounts = []
    for fp in files:
        try:
            data = json.loads(open(fp, encoding="utf-8").read())
            email_addr = data.get("email", "").strip()
            password = data.get("password", "").strip()
            if email_addr and password:
                accounts.append(f"{email_addr}:{password}")
        except Exception:
            pass

    if not accounts:
        shutil.rmtree(_STAGING_DIR, ignore_errors=True)
        return None

    os.makedirs(output_dir, exist_ok=True)
    date_tag = datetime.now(timezone.utc).strftime("%m%d")
    zip_path = os.path.join(output_dir, f"{date_tag}Outlook.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("accounts.txt", "\n".join(accounts) + "\n")

    shutil.rmtree(_STAGING_DIR, ignore_errors=True)
    return zip_path


class TaskCounter:
    def __init__(self, total: int):
        self._lock = threading.Lock()
        self._remaining = total
        self.successes = []

    @property
    def remaining(self) -> int:
        with self._lock:
            return self._remaining

    def acquire(self) -> bool:
        with self._lock:
            if self._remaining <= 0:
                return False
            self._remaining -= 1
            return True

    def record(self, data: str, fp: str) -> None:
        with self._lock:
            self.successes.append((data, fp))


def worker(tid: int, counter: Optional[TaskCounter], proxy: Optional[str],
           captcha_svc: Optional[FunCaptchaService], sleep_min: int, sleep_max: int) -> None:
    time.sleep(random.uniform(0, 3))
    while True:
        if counter and not counter.acquire():
            break
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{ts}] [T{tid}] Attempt")
        result = register_one(tid, proxy, captcha_svc)
        if result:
            fp = _save_staged(result)
            if counter:
                counter.record(result, fp)
        if counter and counter.remaining <= 0:
            break
        time.sleep(random.randint(sleep_min, sleep_max))


def main() -> None:
    parser = argparse.ArgumentParser(description="Outlook batch account registrar")
    parser.add_argument("--count", type=int, default=5, help="Number of accounts")
    parser.add_argument("--threads", type=int, default=1, help="Concurrent threads")
    parser.add_argument("--proxy", default=os.environ.get("PROXY_URL", ""), help="HTTP proxy")
    parser.add_argument("--sleep-min", type=int, default=5)
    parser.add_argument("--sleep-max", type=int, default=15)
    args = parser.parse_args()

    captcha_key = os.environ.get("CAPTCHA_CLIENT_KEY", "")
    captcha_svc = FunCaptchaService(client_key=captcha_key) if captcha_key else None
    if not captcha_key:
        print("[Warn] CAPTCHA_CLIENT_KEY not set - captcha will not be solved automatically")

    counter = TaskCounter(args.count)
    proxy = args.proxy or None

    print(f"[Main] count={args.count} threads={args.threads}")

    threads = []
    for i in range(1, args.threads + 1):
        t = threading.Thread(
            target=worker,
            args=(i, counter, proxy, captcha_svc, args.sleep_min, args.sleep_max),
            daemon=True,
        )
        t.start()
        threads.append(t)

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Main] Interrupted")

    for t in threads:
        t.join(timeout=5)

    zip_path = bundle_output()
    success_count = len(counter.successes)
    print(f"\n[Main] Done. Success: {success_count} | Output: {zip_path or 'none'}")


if __name__ == "__main__":
    main()
