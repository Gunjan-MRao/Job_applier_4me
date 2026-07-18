"""
stealth_browser.py  — Cloudflare / anti-bot hardened browser factory

Primary path: Playwright + playwright-stealth
  - Removes navigator.webdriver, spoofs Chrome runtime, overrides permissions
  - Randomised User-Agent, viewport, locale
  - Human-like mouse jitter, variable delays, keystroke timing

Fallback path: undetected-chromedriver (Selenium)
  - Used automatically when Playwright is not installed
  - uc.Chrome bypasses Cloudflare JS challenges that standard selenium cannot
  - Exposes the same helper surface (human_delay_sync, human_type_sync)

Usage (async / Playwright):
    async with stealth_page() as page:
        await page.goto(url)
        await human_delay(page, 1.5, 3.0)
        await human_type(page, "#search", "supply chain")
        await scroll_to_bottom(page)

Usage (sync / undetected-chromedriver fallback):
    with uc_stealth_driver() as driver:
        driver.get(url)
        human_delay_sync(1.5, 3.0)
"""
from __future__ import annotations

import asyncio
import random
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

# ── Playwright (primary) ────────────────────────────────────────────────────
try:
    from playwright.async_api import async_playwright, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    async_playwright = None  # type: ignore
    PLAYWRIGHT_AVAILABLE = False

try:
    from playwright_stealth import stealth_async
except ImportError:
    async def stealth_async(page):  # type: ignore
        """No-op fallback if playwright-stealth not installed."""
        pass

# ── undetected-chromedriver (Selenium fallback) ──────────────────────────────
try:
    import undetected_chromedriver as uc  # type: ignore
    UC_AVAILABLE = True
except ImportError:
    uc = None  # type: ignore
    UC_AVAILABLE = False


_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

_LOCALES = ["en-GB", "en-US", "en-GB"]


# ===========================================================================
# PRIMARY PATH — Playwright async
# ===========================================================================

@asynccontextmanager
async def stealth_page(headless: bool = True, proxy: Optional[str] = None):
    """
    Async context manager — yields a stealth-hardened Playwright Page.
    Raises RuntimeError if neither Playwright nor UC is available.
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(
            "playwright not installed. Run:\n"
            "  pip install playwright playwright-stealth\n"
            "  playwright install chromium\n"
            "Or install the Selenium fallback: pip install undetected-chromedriver"
        )

    ua       = random.choice(_USER_AGENTS)
    viewport = random.choice(_VIEWPORTS)
    locale   = random.choice(_LOCALES)

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-infobars",
        "--disable-extensions",
        f"--window-size={viewport['width']},{viewport['height']}",
    ]

    proxy_cfg = {"server": proxy} if proxy else None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=launch_args,
            proxy=proxy_cfg,
        )
        ctx: BrowserContext = await browser.new_context(
            user_agent=ua,
            viewport=viewport,
            locale=locale,
            timezone_id="Europe/London",
            java_script_enabled=True,
            ignore_https_errors=False,
        )
        # Block obvious telemetry / tracking to reduce bot fingerprint
        await ctx.route(
            "**/(analytics|telemetry|tracking|ads|doubleclick)/**",
            lambda route, _: route.abort(),
        )
        page: Page = await ctx.new_page()
        await stealth_async(page)
        try:
            yield page
        finally:
            await browser.close()


async def human_delay(page, min_s: float = 0.8, max_s: float = 2.5) -> None:
    """Wait a random human-like interval, optionally moving the mouse."""
    delay = random.uniform(min_s, max_s)
    try:
        vp = page.viewport_size or {"width": 1280, "height": 800}
        x  = random.randint(100, vp["width"]  - 100)
        y  = random.randint(100, vp["height"] - 100)
        await page.mouse.move(x, y)
    except Exception:
        pass
    await asyncio.sleep(delay)


async def human_type(page, selector: str, text: str) -> None:
    """Click a field and type text with randomised per-keystroke delays."""
    await page.click(selector)
    await asyncio.sleep(random.uniform(0.2, 0.6))
    for char in text:
        await page.keyboard.type(char, delay=random.uniform(40, 130))
    await asyncio.sleep(random.uniform(0.3, 0.8))


async def scroll_to_bottom(page, pause_s: float = 1.2, max_scrolls: int = 20) -> None:
    """Gradually scroll to the bottom of the page to trigger lazy-loaded content."""
    for _ in range(max_scrolls):
        prev_height = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
        await asyncio.sleep(random.uniform(pause_s * 0.8, pause_s * 1.3))
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == prev_height:
            break


async def wait_for_selector(
    page, selector: str, timeout_ms: int = 10_000, state: str = "visible"
) -> bool:
    """Wait for a CSS selector and return True if found, False on timeout."""
    try:
        await page.wait_for_selector(selector, timeout=timeout_ms, state=state)
        return True
    except Exception:
        return False


# ===========================================================================
# FALLBACK PATH — undetected-chromedriver (Selenium)
# ===========================================================================

@contextmanager
def uc_stealth_driver(headless: bool = True, proxy: Optional[str] = None):
    """
    Sync context manager that yields an undetected-chromedriver Chrome instance.
    Use this when Playwright is unavailable or when a site blocks headless Chromium
    but not uc.Chrome (common with older Cloudflare versions).

    Raises RuntimeError if undetected-chromedriver is not installed.
    """
    if not UC_AVAILABLE:
        raise RuntimeError(
            "undetected-chromedriver not installed. Run:\n"
            "  pip install undetected-chromedriver"
        )
    ua       = random.choice(_USER_AGENTS)
    viewport = random.choice(_VIEWPORTS)

    options = uc.ChromeOptions()
    options.add_argument(f"--window-size={viewport['width']},{viewport['height']}")
    options.add_argument(f"--user-agent={ua}")
    options.add_argument("--lang=en-GB")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")

    driver = uc.Chrome(headless=headless, options=options)
    try:
        yield driver
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def human_delay_sync(min_s: float = 0.8, max_s: float = 2.5) -> None:
    """Synchronous random human-like delay for Selenium paths."""
    time.sleep(random.uniform(min_s, max_s))


def human_type_sync(driver, xpath: str, text: str) -> None:
    """Click an element by XPath and type text with per-keystroke delays."""
    from selenium.webdriver.common.by import By  # type: ignore
    el = driver.find_element(By.XPATH, xpath)
    el.click()
    time.sleep(random.uniform(0.2, 0.6))
    for char in text:
        el.send_keys(char)
        time.sleep(random.uniform(0.04, 0.13))
    time.sleep(random.uniform(0.3, 0.8))
