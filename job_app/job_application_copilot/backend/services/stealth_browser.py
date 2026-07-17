"""
stealth_browser.py  — Cloudflare/anti-bot hardened browser factory

Provides a single async context manager `stealth_page()` that yields a
Playwright page with:
  - playwright-stealth applied (removes navigator.webdriver, spoofs
    Chrome runtime, overrides permissions etc.)
  - Randomised User-Agent, viewport, and locale
  - Human-like mouse jitter helper
  - Variable delay helper

Usage:
    async with stealth_page() as page:
        await page.goto(url)
        await human_delay(page, 1.5, 3.0)
"""
from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager
from typing import Optional

try:
    from playwright.async_api import async_playwright, Page, BrowserContext
except ImportError:
    async_playwright = None  # type: ignore

try:
    from playwright_stealth import stealth_async
except ImportError:
    async def stealth_async(page):  # type: ignore
        """No-op fallback if playwright-stealth not installed."""
        pass


_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

_LOCALES = ["en-GB", "en-US", "en-GB"]


@asynccontextmanager
async def stealth_page(headless: bool = True, proxy: Optional[str] = None):
    """Async context manager — yields a stealth-hardened Playwright Page."""
    if async_playwright is None:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright playwright-stealth "
            "&& playwright install chromium"
        )

    ua       = random.choice(_USER_AGENTS)
    viewport = random.choice(_VIEWPORTS)
    locale   = random.choice(_LOCALES)

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
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
        # Block obvious telemetry / tracking domains
        await ctx.route(
            "**/(analytics|telemetry|tracking|ads)/**",
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
    # Small random mouse jitter so the page sees pointer activity
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
