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
    let totalRequests = 0;
    let completedRequests = 0;

    function recordRequest(started) {
      if (started) totalRequests++;
      else completedRequests++;
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
          const ready = document.readyState === 'complete';
          const percentDone = totalRequests === 0 ? 1 : completedRequests / totalRequests;

          if (ready && percentDone >= threshold) {
            const idleStart = Date.now();

            (function idleCheck() {
              const idleTime = Date.now() - idleStart;
              const percent = totalRequests === 0 ? 1 : completedRequests / totalRequests;

              if (percent >= threshold && idleTime >= idleWindow) return resolve(true);
              if (Date.now() - start < maxWait) return setTimeout(idleCheck, 50);
              return resolve(false);
            })();

            return;
          }

          if (Date.now() - start < maxWait) return setTimeout(checkReady, 100);
          resolve(false);
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
