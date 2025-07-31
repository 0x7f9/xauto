#!/usr/bin/env python3

from xauto.utils.config import Config

import random
import os
import sys
import tempfile
import logging
import urllib.request
import tarfile
from selenium.webdriver.firefox.options import Options

def check_python_version(required_version_str):
    current_version = sys.version_info
    version_str = str(required_version_str)
    required_version = tuple(map(int, version_str.split('.')))
    
    if current_version < required_version:
        print(f"Python {version_str} or higher is required. Current version: {current_version.major}.{current_version.minor}.{current_version.micro}")
        sys.exit(1)

def download_geckodriver(version):
    geckodriver_path = "xauto/internal/geckodriver/geckodriver"
    
    if os.path.exists(geckodriver_path):
        # print(f"Geckodriver already exists at {geckodriver_path}")
        return
    
    url = f"https://github.com/mozilla/geckodriver/releases/download/v{version}/geckodriver-v{version}-linux64.tar.gz"
    download_path = f"xauto/internal/geckodriver/geckodriver-v{version}-linux64.tar.gz"
    
    print(f"Downloading geckodriver v{version}...")
    urllib.request.urlretrieve(url, download_path)
    
    with tarfile.open(download_path, 'r:gz') as tar:
        tar.extractall("xauto/internal/geckodriver/")
    
    os.chmod(geckodriver_path, 0o755)
    os.remove(download_path)
    print("Geckodriver downloaded and extracted successfully.")

USER_AGENTS = {
    "windows_chrome_125": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.78 Safari/537.36",
    "windows_chrome_124": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.91 Safari/537.36",
    "windows_firefox_127": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "windows_firefox_126": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "windows_edge_125": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.78 Safari/537.36 Edg/125.0.2535.67",
    "windows_edge_124": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.91 Safari/537.36 Edg/124.0.2478.67",

    "mac_safari_17": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5.1 Safari/605.1.15",
    "mac_safari_16": "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_6_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    "mac_chrome_125": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.78 Safari/537.36",
    "mac_firefox_127": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13.4; rv:127.0) Gecko/20100101 Firefox/127.0",
}

def get_text_colors():
    color_config = Config.get("colors", {})
    if color_config:
        return {
            "text_colour": color_config.get("normal", "white"),
            "error_text_colour": color_config.get("error", "light_grey"),
            "keyword_colour": color_config.get("keyword", "magenta"),
            "loading_keyword_colour": color_config.get("loading", "magenta"),
            "success_colour": color_config.get("success", "green"),
            "failure_colour": color_config.get("failure", "red"),
            "warning_colour": color_config.get("warning", "yellow"),
            "light_grey_text_colour": color_config.get("hint", "light_grey")
        }
    return {
        "text_colour": "white",
        "error_text_colour": "light_grey",
        "keyword_colour": "magenta",
        "loading_keyword_colour": "magenta",
        "success_colour": "green",
        "failure_colour": "red",
        "warning_colour": "yellow",
        "light_grey_text_colour": "light_grey"
    }

text_colors = get_text_colors()
text_colour = text_colors["text_colour"]
error_text_colour = text_colors["error_text_colour"]
keyword_colour = text_colors["keyword_colour"]
loading_keyword_colour = text_colors["loading_keyword_colour"]
success_colour = text_colors["success_colour"]
failure_colour = text_colors["failure_colour"]
warning_colour = text_colors["warning_colour"]
light_grey_text_colour = text_colors["light_grey_text_colour"]

debug = Config.get("misc.debug_mode", True)

def _create_ephemeral_profile():
    try:
        profile_dir = tempfile.mkdtemp(prefix="ff_profile_")
        return profile_dir
    except Exception as e:
        logging.getLogger(__name__).warning(f"Failed to create ephemeral profile: {e}")
        return None

def get_options():
    options = Options()
    
    headless = Config.get("system.headless", False)
    if headless:
        options.add_argument("--headless")
    
    profile_dir = _create_ephemeral_profile()
    if profile_dir:
        options.profile = profile_dir
        options.add_argument("-private")
        options.set_preference("browser.privatebrowsing.autostart", True)
    
    options.set_preference("browser.toolbars.bookmarks.visibility", "never")
    options.add_argument("--disable-gpu")
    # options.add_argument("--no-sandbox")
    # options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.set_preference("browser.cache.disk.enable", False)
    options.set_preference("browser.cache.memory.enable", False)
    options.set_preference("browser.cache.offline.enable", False)
    options.set_preference("network.http.use-cache", False)
    options.set_preference("browser.tabs.warnOnClose", False)
    options.set_preference("dom.webdriver.enabled", False)
    options.set_preference("useAutomationExtension", False)
    options.set_preference("privacy.resistFingerprinting", True)
    options.set_preference("dom.webnotifications.enabled", False)
    options.set_preference("media.peerconnection.enabled", False)
    options.set_preference("geo.enabled", False)
    options.set_preference("geo.provider.use_corelocation", False)
    options.set_preference("geo.provider.use_gpsd", False)
    options.set_preference("geo.provider.use_geoclue", False)
    options.set_preference("permissions.default.geo", 2)
    options.set_preference("intl.accept_languages", "en-US, en")
    options.set_preference("intl.locale.requested", "en-US")
    options.set_preference("layout.css.devPixelsPerPx", "0.5")
    options.set_preference("app.update.enabled", False)
    options.set_preference("datareporting.healthreport.uploadEnabled", False)
    options.set_preference("datareporting.policy.dataSubmissionEnabled", False)
    options.set_preference("toolkit.telemetry.enabled", False)
    options.set_preference("toolkit.telemetry.server", "")
    options.set_preference("toolkit.telemetry.unified", False)
    options.set_preference("browser.formfill.enable", False)
    options.set_preference("browser.shell.checkDefaultBrowser", False)
    options.set_preference("image.animation_mode", "none")
    options.set_preference("browser.startup.page", 0)
    options.set_preference("browser.tabs.drawInTitlebar", False)
    options.set_preference("browser.download.folderList", 2)
    options.set_preference("browser.download.useDownloadDir", True)
    options.set_preference("browser.helperApps.alwaysAsk.force", False)
    options.set_preference("dom.ipc.processCount", 1)
    options.set_preference("browser.tabs.remote.autostart", False)
    options.set_preference("browser.tabs.remote.autostart.2", False)
    options.set_preference("places.history.enabled", False)
    options.set_preference("browser.sessionstore.interval", 999999999)
    options.set_preference("plugin.state.flash", 0)
    options.set_preference("plugin.scan.plid.all", False)
    options.set_preference("security.mixed_content.block_active_content", False)
    options.set_preference("javascript.options.gc_on_memory_pressure", True)
    options.set_preference("network.prefetch-next", False)
    options.set_preference("network.dns.disablePrefetch", True)
    options.set_preference("network.http.speculative-parallel-limit", 0)
    options.set_preference("network.predictor.enabled", False)
    options.set_preference("privacy.trackingprotection.enabled", True)
    options.set_preference("network.cookie.cookieBehavior", 1)
    options.set_preference("network.cookie.lifetimePolicy", 2)
    options.set_preference("network.http.referer.XOriginPolicy", 2)
    options.set_preference("network.http.referer.XOriginTrimmingPolicy", 2)
    options.set_preference("network.http.connection-retry-timeout", 0)
    options.set_preference("network.http.max-connections", 48)
    options.set_preference("network.http.max-persistent-connections-per-server", 32)
    options.set_preference("gfx.webrender.enabled", False)
    options.set_preference("layers.acceleration.disabled", True)
    options.set_preference("devtools.jsonview.enabled", False)
    return options

def get_random_user_agent():
    return random.choice(list(USER_AGENTS.values()))