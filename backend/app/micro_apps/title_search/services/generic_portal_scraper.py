"""Generic portal scraper using Playwright + AI-guided navigation.

Handles any county property appraiser, tax collector, or clerk of court portal
by using AI to understand the page layout, find search inputs, and extract data.

This is the fallback when no specialized scraper (Phenix, Acclaim, COJ) exists.
"""

import logging
import re

from playwright.async_api import Browser, Page

logger = logging.getLogger(__name__)

# Common search input selectors (ordered by likelihood)
_SEARCH_SELECTORS = [
    'input[name*="address" i]',
    'input[name*="search" i]',
    'input[id*="address" i]',
    'input[id*="search" i]',
    'input[placeholder*="address" i]',
    'input[placeholder*="search" i]',
    'input[aria-label*="address" i]',
    'input[aria-label*="search" i]',
    'input[type="search"]',
    'input[type="text"]',
]

_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Search")',
    'button:has-text("Go")',
    'button:has-text("Find")',
    'button:has-text("Lookup")',
    'a:has-text("Search")',
]

_CAPTCHA_INDICATORS = [
    "captcha", "recaptcha", "hcaptcha", "challenge-platform",
    "cf-turnstile", "just a moment", "verify you are human",
    "checking your browser", "cloudflare", "ddos-guard",
]

# Max HTML size to send to AI (chars) — truncate large pages
_MAX_HTML_FOR_AI = 80_000


def _detect_captcha(content: str) -> bool:
    lower = content.lower()
    return any(ind in lower for ind in _CAPTCHA_INDICATORS)


def _clean_html_for_ai(html: str) -> str:
    """Strip scripts, styles, and excessive whitespace to reduce token usage."""
    # Remove script and style blocks
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    # Collapse whitespace
    html = re.sub(r'\s+', ' ', html)
    # Truncate if still too large
    if len(html) > _MAX_HTML_FOR_AI:
        html = html[:_MAX_HTML_FOR_AI] + "\n[TRUNCATED]"
    return html


class GenericPortalScraper:
    """Scrapes any property/clerk portal using Playwright with heuristic navigation."""

    @staticmethod
    async def scrape_property_portal(
        browser: Browser,
        portal_url: str,
        address: str,
        timeout_ms: int = 30_000,
    ) -> dict:
        """Navigate to a property/tax portal, search for the address, return page HTML.

        Returns:
            dict with keys: success, html, source_url, error
        """
        page = await browser.new_page()
        try:
            logger.info(f"Generic scraper: navigating to {portal_url}")
            await page.goto(portal_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(2000)

            content = await page.content()
            if _detect_captcha(content):
                return {
                    "success": False,
                    "error": "CAPTCHA detected on portal",
                    "captcha_blocked": True,
                    "html": "",
                    "source_url": portal_url,
                }

            # Try to find and fill a search input
            searched = await _try_search(page, address)
            if searched:
                await page.wait_for_timeout(3000)
                content = await page.content()
                # Check for CAPTCHA after search
                if _detect_captcha(content):
                    return {
                        "success": False,
                        "error": "CAPTCHA detected after search",
                        "captcha_blocked": True,
                        "html": "",
                        "source_url": page.url,
                    }

                # Try clicking on the first result link if we're on a search results page
                await _try_click_first_result(page, address)
                await page.wait_for_timeout(2000)
                content = await page.content()

            cleaned = _clean_html_for_ai(content)
            return {
                "success": True,
                "html": cleaned,
                "source_url": page.url,
            }

        except Exception as e:
            logger.warning(f"Generic scraper failed for {portal_url}: {e}")
            return {
                "success": False,
                "error": str(e),
                "html": "",
                "source_url": portal_url,
            }
        finally:
            await page.close()

    @staticmethod
    async def scrape_clerk_portal(
        browser: Browser,
        portal_url: str,
        owner_name: str,
        timeout_ms: int = 30_000,
    ) -> dict:
        """Navigate to a clerk/recorder portal, search by name, return page HTML.

        Returns:
            dict with keys: success, html, source_url, error
        """
        page = await browser.new_page()
        try:
            logger.info(f"Generic clerk scraper: navigating to {portal_url}")
            await page.goto(portal_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(2000)

            content = await page.content()
            if _detect_captcha(content):
                return {
                    "success": False,
                    "error": "CAPTCHA detected on clerk portal",
                    "captcha_blocked": True,
                    "html": "",
                    "source_url": portal_url,
                }

            # Try to dismiss common disclaimers/agreements
            await _try_dismiss_disclaimer(page)

            # Try to search by name
            searched = await _try_search(page, owner_name)
            if searched:
                await page.wait_for_timeout(3000)
                content = await page.content()
                if _detect_captcha(content):
                    return {
                        "success": False,
                        "error": "CAPTCHA detected after clerk search",
                        "captcha_blocked": True,
                        "html": "",
                        "source_url": page.url,
                    }

            cleaned = _clean_html_for_ai(content)
            return {
                "success": True,
                "html": cleaned,
                "source_url": page.url,
            }

        except Exception as e:
            logger.warning(f"Generic clerk scraper failed for {portal_url}: {e}")
            return {
                "success": False,
                "error": str(e),
                "html": "",
                "source_url": portal_url,
            }
        finally:
            await page.close()


async def _try_dismiss_disclaimer(page: Page) -> None:
    """Try to click common disclaimer/agreement buttons."""
    dismiss_selectors = [
        'button:has-text("Agree")',
        'button:has-text("Accept")',
        'button:has-text("I Agree")',
        'button:has-text("Continue")',
        'input[value*="Agree" i]',
        'a:has-text("I Agree")',
        'button:has-text("OK")',
    ]
    for sel in dismiss_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                await page.wait_for_timeout(1500)
                return
        except Exception:
            continue


async def _try_search(page: Page, query: str) -> bool:
    """Try to find a search input, fill it, and submit.
    Returns True if a search was submitted.
    """
    for sel in _SEARCH_SELECTORS:
        try:
            input_el = page.locator(sel).first
            if await input_el.is_visible(timeout=1000):
                await input_el.click()
                await input_el.fill(query)
                await page.wait_for_timeout(500)

                # Try to submit
                for submit_sel in _SUBMIT_SELECTORS:
                    try:
                        btn = page.locator(submit_sel).first
                        if await btn.is_visible(timeout=500):
                            await btn.click()
                            return True
                    except Exception:
                        continue

                # Fallback: press Enter
                await input_el.press("Enter")
                return True
        except Exception:
            continue

    return False


async def _try_click_first_result(page: Page, address: str) -> None:
    """On a search results page, try to click the first result that matches."""
    # Common patterns for result links
    addr_parts = address.lower().split()
    # Look for links/rows containing part of the address
    try:
        links = page.locator("a")
        count = await links.count()
        for i in range(min(count, 50)):
            link = links.nth(i)
            text = (await link.text_content() or "").lower()
            # Check if the link text contains address keywords
            if any(part in text for part in addr_parts[:2] if len(part) > 2):
                try:
                    if await link.is_visible(timeout=500):
                        await link.click()
                        return
                except Exception:
                    continue
    except Exception:
        pass
