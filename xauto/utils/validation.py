from xauto.utils.logging import debug_bot_detection

import re
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException

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

def is_browser_error_page(driver):
    try:
        title = driver.title.lower()
        return any(err.lower() in title for err in BROWSER_ERROR_TITLES)
    except Exception:
        return False

def is_connection_error(error):
    try:
        err_str = str(error).lower()
        return any(keyword in err_str for keyword in CONNECTION_ERROR_KEYWORDS)
    except Exception:
        return False

def _is_cloudflare_challenge(driver):
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

def is_bot_page(driver, url):
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