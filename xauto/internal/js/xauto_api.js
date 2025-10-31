(function () {

  function stealthPatches() {
    const stealthPatches = {
      webdriver: () => false,

      plugins: () => [
        { name: "Widevine Content Decryption Module", filename: "libwidevinecdm.so", description: "Enables Widevine licenses" },
        { name: "OpenH264 Video Codec", filename: "openh264.xpt", description: "H.264 support from Cisco" }
      ],

      languages: () => ['en-US', 'en']
    };

    Object.freeze(stealthPatches); 
    stealthPatches.plugins().forEach(Object.freeze);

    try { delete Navigator.prototype.webdriver; } catch (e) {}

    Object.entries(stealthPatches).forEach(([key, getter]) => {
      Object.defineProperty(navigator, key, {
        get: getter,
        configurable: true
      });
    });

    for (const prop of [
      '__driver_evaluate',
      '__$webdriverAsyncExecutor',
      '__webdriver_script_fn',
      '__lastWatirAlert'
    ]) {
      try { delete window[prop]; } catch (e) {}
    }
  }

  function setupUtils() {
    const API = {};

    API.enableDebug = () => {
      window._xautoDebug = true;
      console.log('[XAUTO_DEBUG] Debug mode enabled');
    };

    API.disableDebug = () => {
      window._xautoDebug = false;
      console.log('[XAUTO_DEBUG] Debug mode disabled');
    };

    let totalRequests = 0;
    let completedRequests = 0;

    function recordRequest(started, url) {
      try {
        // if (pageInteractive) return;
        
        const sameOrigin = url && url.startsWith(location.origin);
        if (!sameOrigin) return;

      if (started) totalRequests++;
      else completedRequests++;
      } catch (_) {}
    }

    if (typeof window.fetch === 'function') {
      const origFetch = window.fetch;
      window.fetch = new Proxy(origFetch, {
        apply(target, thisArg, args) {
          recordRequest(true);
          return Reflect.apply(target, thisArg, args).finally(() => recordRequest(false));
        }
      });
    }

    const xhrs = new WeakMap();
    const origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function() {
      xhrs.set(this, true);
      return origOpen.apply(this, arguments);
    };

    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function() {
      if (xhrs.get(this)) recordRequest(true);
      this.addEventListener("loadend", () => {
        if (xhrs.get(this)) recordRequest(false);
      });
      return origSend.apply(this, arguments);
    };

    API.waitForReady = (maxWait = 10000, idleWindow = 200, threshold = 0.7) => {
      return new Promise(resolve => {
        const start = Date.now();

        function checkReady() {
          const readyState = document.readyState;
          const percentDone = totalRequests === 0 ? 1 : completedRequests / totalRequests;

          const domReady = readyState === 'interactive' || readyState === 'complete';
          const netReady = percentDone >= threshold;

          if (domReady && netReady) {
            const idleStart = Date.now();

            function confirmIdle() {
              const percent = totalRequests === 0 ? 1 : completedRequests / totalRequests;
              const idleTime = Date.now() - idleStart;

              if (percent >= threshold && idleTime >= idleWindow) {
                totalRequests = 0;
                completedRequests = 0;
                return resolve(true);
              }

              if (Date.now() - start < maxWait) {
                (window.requestIdleCallback || window.requestAnimationFrame)(confirmIdle);
              } else {
                resolve(false);
              }
            }

            return (window.requestIdleCallback || window.requestAnimationFrame)(confirmIdle);
          }

          if (Date.now() - start < maxWait) {
            setTimeout(checkReady, 100);
          } else {
          resolve(false);
          }
        }

        checkReady();
      });
    };

    API.closePopups = () => {
      const closed = [];
      const openedWindows = window.openedWindows || [];

      for (const h of openedWindows) {
        try {
          h.close();
          closed.push(h);
        } catch (e) {}
      }

      if (window.openedWindows) {
        window.openedWindows = window.openedWindows.filter(w => !closed.includes(w));
      }

      return closed.length;
    };

    window._popupCount ??= 0;
    window.openedWindows ??= [];
    window._xautoDebug ??= false;

    if (!window.__xautoOpenHooked) {
      const origWindowOpen = window.open;
      window.open = function (...args) {
        window._popupCount++;
        const popup = origWindowOpen.apply(this, args);
        if (popup) {
          window.openedWindows.push(popup);
        }
        return popup;
      };
      window.__xautoOpenHooked = true;
    }

    Object.freeze(API);
    Object.freeze(window.openedWindows);

    if (!window._xautoAPI) {
      Object.defineProperty(window, '_xautoAPI', {
        value: API,
        configurable: false,
        writable: false,
        enumerable: false
      });
    }

    window._injectionTime ??= performance.now();
    document.documentElement.setAttribute("data-injected", "1");
  }

  stealthPatches();
  setupUtils();
})();
