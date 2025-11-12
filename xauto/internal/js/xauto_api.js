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
        if (!url) return;

      if (started) totalRequests++;
      else completedRequests++;
      } catch (_) {}
    }

    if (typeof window.fetch === 'function') {
      const origFetch = window.fetch;
      window.fetch = function(input, _init) {
        const url = typeof input === 'string' ? input : (input?.url ?? '');
        recordRequest(true, url);
        return origFetch.apply(this, arguments).finally(() => recordRequest(false, url));
      };
    }

    const xhrs = new WeakMap();
    const origOpen = XMLHttpRequest.prototype.open;

    XMLHttpRequest.prototype.open = function(_method, url) {
      xhrs.set(this, { url: String(url) });
      return origOpen.apply(this, arguments);
    };

    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function() {
      const meta = xhrs.get(this);
      if (meta) recordRequest(true, meta.url);

      const onEnd = () => {
        if (meta) recordRequest(false, meta.url);
        xhrs.delete(this);               
        this.removeEventListener('loadend', onEnd);
      };
      this.addEventListener('loadend', onEnd);

      return origSend.apply(this, arguments);
    };

    API.waitForReady = (maxWait = 15000, idleWindow = 500, threshold = 0.8) => {
      return new Promise(resolve => {
        const start = Date.now();
        const deadline = start + maxWait;
        let idleStart     = 0;
        let pendingId     = null;             

        const cancel = () => {
          if (pendingId !== null) {
            clearTimeout(pendingId);
            pendingId = null;
          }
        };

        const checkReady = () => {
          if (Date.now() >= deadline) {
            cancel();
            return resolve(false);
          }

          const readyState = document.readyState;
          const percentDone = totalRequests === 0 ? 1 : completedRequests / totalRequests;
          const domReady = readyState === 'interactive' || readyState === 'complete';
          const netReady = percentDone >= threshold;

          if (domReady && netReady) {
            idleStart = idleStart || Date.now();   

            const confirmIdle = () => {
              if (Date.now() >= deadline) {
                cancel();
                return resolve(false);
              }

              const percent = totalRequests === 0 ? 1 : completedRequests / totalRequests;
              const idleTime = Date.now() - idleStart;

              if (percent >= threshold && idleTime >= idleWindow) {
                totalRequests = 0;
                completedRequests = 0;
                cancel();
                return resolve(true);
              }

              pendingId = (window.requestIdleCallback || window.requestAnimationFrame)(confirmIdle);
            };
            
            pendingId = (window.requestIdleCallback || window.requestAnimationFrame)(confirmIdle);
            return;
          }

          pendingId = setTimeout(checkReady, 50);
        };

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
      const orig = window.open;
      window.open = function(url, name, specs) {
        window._popupCount++;
        const win = orig.call(this, url, name, specs);
        if (win) window.openedWindows.push(win);
        return win;
      };
      window.__xautoOpenHooked = true;
    }

    Object.freeze(API);

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
