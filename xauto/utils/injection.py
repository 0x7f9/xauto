from xauto.utils.logging import debug_logger
from selenium.common.exceptions import WebDriverException

_XAUTO_API_JS = """
(function() {
  const API = {};

  API.waitForReady = (maxWait = 10000, idleWindow = 200) => {
    return new Promise(resolve => {
      const start = Date.now();

      function checkReady() {
        const ready = document.readyState === 'complete';
        const pending = typeof window.__pendingRequests === 'number' ? window.__pendingRequests : 0;

        if (ready && pending === 0) {
          const idleStart = Date.now();

          (function idleCheck() {
            const stillPending = typeof window.__pendingRequests === 'number' ? window.__pendingRequests : 0;
            const idleTime = Date.now() - idleStart;

            if (stillPending === 0 && idleTime >= idleWindow) {
              return resolve(true);
            }

            if (Date.now() - start < maxWait) {
              return setTimeout(idleCheck, 50);
            }

            return resolve(false); // timeout fallback
          })();

          return;
        }

        if (Date.now() - start < maxWait) {
          return setTimeout(checkReady, 100);
        }

        resolve(false);
      }

      checkReady();
    });
  };

  // Object.freeze(stealthPatches);
  Object.freeze(API);
  // Object.freeze(window.openedWindows);

  Object.defineProperty(window, '_xautoAPI', {
    value: API,
    configurable: false,
    writable: false,
    enumerable: false
  });

  window._injectionTime = performance.now();
  document.documentElement.setAttribute("data-injected", "1");
})();
"""

def ensure_injected(driver):
    curr = driver.current_url
    if curr != getattr(driver, "_last_url", None):
        driver._is_injected = False
        driver._last_url = curr
    else:
        try:
            dirty = driver.execute_script("return window._pageDirty === true")
            if dirty:
                driver._is_injected = False
                driver.execute_script("window._pageDirty = false")
        except WebDriverException:
            driver._is_injected = False

    injected = bool(driver.execute_script(
        "return document.documentElement.getAttribute('data-injected')"))

    if not injected and not getattr(driver, "_is_injected", False):
        _inject_api(driver)

def _inject_api(driver):
    try:
        exe = driver.execute_script
        exe(_XAUTO_API_JS)

        injected = bool(driver.execute_script(
            "return document.documentElement.getAttribute('data-injected')")
        )

        if not injected:
            driver._is_injected = False
            return False

        driver._is_injected = True
        driver._last_url = driver.current_url

        return True
    except Exception as e:
        debug_logger.debug(f"[JS_INJECTION] Failed to inject: {e}")
        driver._is_injected = False
        return False
