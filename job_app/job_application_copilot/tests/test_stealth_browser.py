"""
test_stealth_browser.py — Unit tests for stealth_browser helpers.

We never launch a real browser in CI.  Instead we test:
 - human_delay() calls asyncio.sleep with a value in the expected range
 - human_type() sends one keyboard.type call per character
 - scroll_to_bottom() stops when page height stops changing
 - stealth_page() raises RuntimeError when Playwright is not available
 - uc_stealth_driver() raises RuntimeError when UC is not available
 - human_delay_sync() sleeps for approximately the right duration
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backend.services.stealth_browser as sb


# ---------------------------------------------------------------------------
# human_delay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_human_delay_sleeps_within_range():
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    page = MagicMock()
    page.viewport_size = {"width": 1280, "height": 800}
    page.mouse.move = AsyncMock()

    with patch("asyncio.sleep", side_effect=fake_sleep):
        await sb.human_delay(page, min_s=1.0, max_s=2.0)

    assert len(slept) == 1
    assert 1.0 <= slept[0] <= 2.0


# ---------------------------------------------------------------------------
# human_type
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_human_type_sends_one_call_per_char():
    page = MagicMock()
    page.click = AsyncMock()
    page.keyboard.type = AsyncMock()

    text = "hello"
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await sb.human_type(page, "#input", text)

    assert page.keyboard.type.call_count == len(text)
    # Every call used the correct character
    called_chars = [call.args[0] for call in page.keyboard.type.call_args_list]
    assert called_chars == list(text)


# ---------------------------------------------------------------------------
# scroll_to_bottom
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scroll_to_bottom_stops_when_height_unchanged():
    page = MagicMock()
    evaluate_results = [1000, 1000]  # height unchanged after first scroll
    page.evaluate = AsyncMock(side_effect=lambda expr: evaluate_results.pop(0)
                              if evaluate_results else 1000)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await sb.scroll_to_bottom(page, pause_s=0.1, max_scrolls=10)

    # evaluate called at most a small number of times
    assert page.evaluate.call_count <= 4


# ---------------------------------------------------------------------------
# stealth_page raises when Playwright missing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stealth_page_raises_when_playwright_unavailable():
    original = sb.PLAYWRIGHT_AVAILABLE
    sb.PLAYWRIGHT_AVAILABLE = False
    try:
        with pytest.raises(RuntimeError, match="playwright not installed"):
            async with sb.stealth_page():
                pass
    finally:
        sb.PLAYWRIGHT_AVAILABLE = original


# ---------------------------------------------------------------------------
# uc_stealth_driver raises when UC missing
# ---------------------------------------------------------------------------

def test_uc_stealth_driver_raises_when_uc_unavailable():
    original = sb.UC_AVAILABLE
    sb.UC_AVAILABLE = False
    try:
        with pytest.raises(RuntimeError, match="undetected-chromedriver not installed"):
            with sb.uc_stealth_driver():
                pass
    finally:
        sb.UC_AVAILABLE = original


# ---------------------------------------------------------------------------
# human_delay_sync
# ---------------------------------------------------------------------------

def test_human_delay_sync_sleeps():
    slept: list[float] = []
    with patch("time.sleep", side_effect=lambda s: slept.append(s)):
        sb.human_delay_sync(min_s=0.5, max_s=1.0)
    assert len(slept) == 1
    assert 0.5 <= slept[0] <= 1.0
