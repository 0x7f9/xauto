from xauto.utils.config import Config
from xauto.utils.injection import XAUTO_GET_USER_AGENT
from xauto.utils.logging import debug_bot_detection, debug_logger
from xauto.utils.setup import get_random_user_agent

import re
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.remote.webdriver import WebDriver
import time
import urllib3
import requests
import threading

def get_regex(pattern, flags=0):
    return re.compile(pattern, flags)

SELECTORS_MAP = {
    'bot': (
        "iframe[src*=recaptcha],iframe[src*=turnstile],iframe[src*=hcaptcha],"
        "div[id*=captcha],div[class*=captcha],input[id*=captcha],input[class*=captcha],"
        "div#cf-browser-verification,div[class*=cf-challenge],div[class*=challenge],"
        "div[class*=verification],div[class*=human-verification]"
    ),
    # 'default': ("")
}

CF_TITLE = get_regex(r'(just a moment|attention required|checking your browser).+cloudflare', re.I)

CF_CHALLENGE_INDICATORS = [
    "checking your browser",
    "please wait while we verify",
    "cloudflare is checking your browser",
    "ddos protection by cloudflare",
    "ray id:",
    "cf-ray:"
]

BROWSER_ERROR_TITLES = [
    "Server Not Found",
    "Problem loading page",
    "This site can't be reached",
    "Hmm. We're having trouble finding that site."
]

CONNECTION_ERROR_KEYWORDS = [
    "connection refused",
    "connection error",
    "max retries exceeded",
    "newconnectionerror",
    "httpconnectionpool",
]

BOT_WORDS = {
    "rc-imageselect", "hcaptcha-frame", "h-recaptcha", "captcha_login", "CaptchaSecurityImages",
    "createCaptcha", "form-control captcha", "rc-imageselect-payload", "rc-anchor-alert",
    "rc-anchor-container", "challenge-prompt", "h-captcha", "challenge-container",
    "rc-anchor-content", "grecaptcha-badge", "logInForm__captcha", "google-recaptcha",
    "google-captcha-wrap", "cb-i", "cb-lb-t", "recaptcha-token", "recaptcha-anchor-label",
    "imagenCaptcha", "frmCaptcha", "recaptcha-anchor", "cf-link", "rc-imageselect-tile",
    "human-verification-modal", "verification-modal", "human-verification", "modal-two",
    "cf-turnstile", "cf-turnstile-response", "captcha-container", "rc-imageselect-challenge",
    "rc-image-tile", "login-captcha", "captchaimglogin"
}
bot_patterns = [(kw, get_regex(rf"{re.escape(kw.lower()).replace(' ', '.*?')}", re.I)) for kw in BOT_WORDS]

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_tls = threading.local()

def get_session():
    if not hasattr(_tls, "session"):
        s = requests.Session()
        s.verify = False
        _tls.session = s
    return _tls.session

REQUEST_BASE_HEADERS = {
    "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

def is_up(url, driver=None):
    headers = REQUEST_BASE_HEADERS.copy()
    if driver:
        try:
            headers["User-Agent"] = driver.execute_script(XAUTO_GET_USER_AGENT)
        except Exception:
            headers["User-Agent"] = get_random_user_agent()

    start = time.monotonic()
    try:
        session = get_session()
        resp = session.get(
            url, 
            headers=headers, 
            timeout=Config.get("misc.timeouts.max_http_request_wait")
        )

        elapsed = time.monotonic() - start
        if resp.status_code < 400:
            debug_logger.info(f"[IS_UP] check time {elapsed:.2f}s")

        if resp.status_code == 403:
            return True, resp.status_code

        return resp.status_code < 400, resp.status_code

    except requests.RequestException:
        debug_logger.warning(f"Page is down {url}")
        return False, 404

def is_browser_error_page(driver: WebDriver) -> bool:
    try:
        title = driver.title.lower()
        return any(title == err for err in BROWSER_ERROR_TITLES)
    except Exception:
        return False

def is_connection_error(error: str) -> bool:
    try:
        err_str = str(error).lower()
        return any(keyword in err_str for keyword in CONNECTION_ERROR_KEYWORDS)
    except Exception:
        return False

def _is_cloudflare_challenge(driver: WebDriver) -> bool:
    try:
        title = (driver.title or "").lower()
        page = (driver.page_source or "").lower()

        if CF_TITLE.search(title):
            debug_bot_detection.debug(f"[BOT DETECTION] Cloudflare challenge via title: '{title[:100]}...'")
            return True
        for indicator in CF_CHALLENGE_INDICATORS:
            if indicator in page:
                debug_bot_detection.debug(f"[BOT DETECTION] Cloudflare challenge via indicator: '{indicator}'")
                return True
        return False
    except Exception as e:
        debug_bot_detection.debug(f"[BOT DETECTION] Cloudflare check error: {e}")
        return False

def is_bot_page(driver: WebDriver, url: str) -> bool:
    if _is_cloudflare_challenge(driver):
        debug_bot_detection.debug(f"[BOT DETECTION] Cloudflare on {url}")
        return True

    selectors = SELECTORS_MAP['bot']
    for elem in driver.find_elements(By.CSS_SELECTOR, selectors):
        try:
            # note: this is bot detection on main page elements, not iframe or DOM elements
            outer = (elem.get_attribute('outerHTML') or "").lower()
            
            # ignore false positives from boilerplate code on sites
            if 'grecaptcha-badge' in outer and 'data-style="bottomright"' in outer:
                continue

            for keyword, pattern in bot_patterns:
                if pattern.search(outer):
                    debug_bot_detection.debug(f"[BOT DETECTION] Matched '{keyword}' on {url}")
                    return True

        except StaleElementReferenceException:
            continue

    return False

