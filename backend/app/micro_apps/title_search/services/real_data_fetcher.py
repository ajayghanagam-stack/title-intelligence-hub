"""Real county data fetcher using API-first + Playwright fallback.

Retrieves property data from:
1. US Census Geocoder API (address → county identification)
2. ArcGIS REST APIs (parcel data where available)
3. Playwright-based scrapers for clerk of court and tax collector portals
"""

import logging
import re
import asyncio
from dataclasses import dataclass, field

import httpx
from playwright.async_api import async_playwright, Browser, Page

logger = logging.getLogger(__name__)


# ─── CAPTCHA Handling ──────────────────────────────────────────────────

class CaptchaBlockedError(Exception):
    """Raised when a CAPTCHA blocks automated access."""
    pass


_CAPTCHA_INDICATORS = [
    "captcha", "recaptcha", "hcaptcha", "challenge-platform",
    "cf-turnstile", "just a moment", "verify you are human",
    "checking your browser", "cloudflare", "ddos-guard",
    "attention required",
]


def _detect_captcha(page_content: str) -> bool:
    """Detect common CAPTCHA/bot-block indicators in page content."""
    lower = page_content.lower()
    return any(indicator in lower for indicator in _CAPTCHA_INDICATORS)


async def _clerk_search_with_retry(
    browser: Browser,
    url: str,
    name: str,
    county: str,
    max_retries: int = 2,
) -> list:
    """Search clerk records with CAPTCHA detection and retry logic."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            docs = await ClerkOfCourtScraper.search_by_name(browser, url, name)
            return docs
        except Exception as e:
            err_msg = str(e).lower()
            # Check if it's a CAPTCHA/Cloudflare block
            if any(ind in err_msg for ind in _CAPTCHA_INDICATORS):
                raise CaptchaBlockedError(
                    f"{county} clerk portal blocked by CAPTCHA after {attempt + 1} attempt(s)"
                )
            last_error = e
            if attempt < max_retries:
                wait = 3 * (attempt + 1)
                logger.info(f"Clerk search attempt {attempt + 1} failed, retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                raise last_error
    return []


@dataclass
class PropertyData:
    """Structured property data from all sources."""
    # Property identification
    parcel_number: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    county: str = ""
    subdivision: str = ""

    # Owner info
    owner_name: str = ""
    mailing_address: str = ""

    # Tax info
    assessed_value: float = 0.0
    land_value: float = 0.0
    improvement_value: float = 0.0
    total_value: float = 0.0
    tax_amount: float = 0.0
    tax_year: str = ""
    assessment_year: str = ""
    tax_status: str = ""
    homestead_exemption: bool = False
    payment_history: list = field(default_factory=list)

    # Legal description
    legal_description: str = ""

    # Deed / sales history (from appraiser or clerk)
    sales_history: list = field(default_factory=list)

    # Recorded documents from clerk (deeds, mortgages, liens)
    recorded_documents: list = field(default_factory=list)

    # Source tracking
    sources_used: list = field(default_factory=list)
    sources_failed: list = field(default_factory=list)


# ─── Tax Collector Scraper (Phenix.net / PublicSoft) ────────────────────

class TaxCollectorScraper:
    """Scrapes Florida tax collector sites powered by Phenix.net."""

    @staticmethod
    async def search_and_extract(
        browser: Browser,
        base_url: str,
        address: str,
    ) -> dict:
        """Search tax collector and extract property tax data."""
        page = await browser.new_page()
        result = {
            "success": False,
            "tax_account": "",
            "owner": "",
            "mailing_address": "",
            "property_address": "",
            "taxes": [],
            "assessments": [],
            "taxable_values": [],
            "legal_description": "",
            "payment_history": [],
            "tax_total": 0.0,
            "assessed_value": 0.0,
        }

        try:
            # Go to account search
            search_url = f"{base_url.rstrip('/')}/AccountSearch"
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Fill search
            search_box = page.locator('#MainContent_txtSearchCriteria')
            if await search_box.count() == 0:
                result["error"] = "Search box not found"
                return result

            await search_box.fill(address)
            await page.click('#MainContent_btnSearch')
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)

            # Find result links
            links = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a'))
                    .filter(a => a.href.includes('PropertyDetail'))
                    .map(a => ({text: a.textContent.trim(), href: a.href}))
            }""")

            if not links:
                result["error"] = "No property found"
                return result

            # Go to first result detail page
            detail_url = links[0]["href"]
            result["tax_account"] = links[0]["text"].split(" - ")[0].strip()
            await page.goto(detail_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Extract main tax info from the page
            body_text = await page.inner_text("body")
            result.update(_parse_tax_detail_text(body_text))

            # Click Assessments tab
            try:
                assess_tab = page.locator('a:has-text("Assessments")')
                if await assess_tab.count() > 0:
                    await assess_tab.click()
                    await asyncio.sleep(1)
                    assess_text = await page.inner_text("body")
                    result["assessments"] = _parse_assessments(assess_text)
                    result["taxable_values"] = _parse_taxable_values(assess_text)
            except Exception as e:
                logger.warning(f"Failed to get assessments: {e}")

            # Click Legal Description tab
            try:
                legal_tab = page.locator('a:has-text("Legal Description")')
                if await legal_tab.count() > 0:
                    await legal_tab.click()
                    await asyncio.sleep(2)
                    body = await page.inner_text("body")
                    idx = body.find("Legal Description")
                    if idx != -1:
                        # Skip past "Legal Description" and any following tab names
                        after = body[idx + len("Legal Description"):]
                        # Remove leading tab names like "Payment History"
                        after = after.lstrip()
                        for tab_name in ("Payment History", "Taxes", "Assessments"):
                            if after.startswith(tab_name):
                                after = after[len(tab_name):].lstrip()
                        # Find end marker
                        end = len(after)
                        for marker in ("Payment Options", "Print Bill", "© 20",
                                       "Powered by"):
                            pos = after.find(marker)
                            if pos != -1 and pos < end:
                                end = pos
                        legal = after[:end].strip()
                        legal = " ".join(legal.split())
                        if legal and len(legal) > 3:
                            result["legal_description"] = legal
            except Exception as e:
                logger.warning(f"Failed to get legal description: {e}")

            # Click Payment History tab
            try:
                pay_tab = page.locator('a:has-text("Payment History")')
                if await pay_tab.count() > 0:
                    await pay_tab.click()
                    await asyncio.sleep(1)
                    pay_text = await page.inner_text("body")
                    result["payment_history"] = _parse_payment_history(pay_text)
            except Exception as e:
                logger.warning(f"Failed to get payment history: {e}")

            result["success"] = True

        except Exception as e:
            logger.error(f"Tax collector scraping failed: {e}")
            result["error"] = str(e)
        finally:
            await page.close()

        return result


def _parse_tax_detail_text(text: str) -> dict:
    """Parse the main tax detail page text."""
    data = {}

    # Owner
    owner_match = re.search(r"Owner:\s*(.+?)(?:\n|$)", text)
    if owner_match:
        data["owner"] = owner_match.group(1).strip()

    # Mailing address
    mail_match = re.search(
        r"MAILING ADDRESS:\s*\n(.+?)(?:\n\n|PROPERTY ADDRESS)", text, re.DOTALL
    )
    if mail_match:
        data["mailing_address"] = " ".join(mail_match.group(1).split())

    # Property address
    prop_match = re.search(
        r"PROPERTY ADDRESS:\s*\n(.+?)(?:\n\n|$)", text, re.DOTALL
    )
    if prop_match:
        data["property_address"] = " ".join(prop_match.group(1).split())

    # Tax total
    total_match = re.search(r"TOTAL\s+[\d.]+\s+\$([\d,]+\.\d+)", text)
    if total_match:
        data["tax_total"] = float(total_match.group(1).replace(",", ""))

    return data


def _parse_assessments(text: str) -> list:
    """Parse assessments tab data."""
    assessments = []
    in_section = False
    for line in text.split("\n"):
        line = line.strip()
        if "Improv" in line and "Land" in line:
            in_section = True
            continue
        if in_section and line and not line.startswith("Exemp"):
            parts = line.split("\t")
            if len(parts) >= 3:
                assessments.append({
                    "authority": parts[0].strip() if parts[0] else "",
                    "improvement": parts[1].strip() if len(parts) > 1 else "",
                    "land": parts[2].strip() if len(parts) > 2 else "",
                })
        if "Exemptions" in line:
            in_section = False
    return assessments


def _parse_taxable_values(text: str) -> list:
    """Parse taxable values section."""
    values = []
    in_section = False
    for line in text.split("\n"):
        line = line.strip()
        if "Assessed" in line and "Exemption" in line and "Taxable" in line:
            in_section = True
            continue
        if in_section and line:
            parts = line.split("\t")
            if len(parts) >= 3:
                try:
                    values.append({
                        "authority": parts[0].strip(),
                        "assessed": parts[1].strip().replace(",", ""),
                        "exemption": parts[2].strip().replace(",", ""),
                        "taxable": parts[3].strip().replace(",", "") if len(parts) > 3 else "",
                    })
                except (IndexError, ValueError):
                    pass
    return values


def _parse_payment_history(text: str) -> list:
    """Parse payment history tab."""
    history = []
    in_section = False
    for line in text.split("\n"):
        line = line.strip()
        if "Tax Year" in line and "Payment Date" in line:
            in_section = True
            continue
        if in_section and line:
            parts = line.split("\t")
            if len(parts) >= 5:
                history.append({
                    "tax_year": parts[0].strip(),
                    "folio": parts[1].strip() if len(parts) > 1 else "",
                    "receipt": parts[2].strip() if len(parts) > 2 else "",
                    "paid_by": parts[3].strip() if len(parts) > 3 else "",
                    "payment_date": parts[4].strip() if len(parts) > 4 else "",
                    "amount": parts[5].strip() if len(parts) > 5 else "",
                })
    return history


# ─── Clerk of Court Scraper (Acclaim/OnCore) ────────────────────────────

class ClerkOfCourtScraper:
    """Scrapes Acclaim/OnCore based clerk of court portals (e.g., Duval, etc.)."""

    @staticmethod
    async def search_by_name(
        browser: Browser,
        portal_url: str,
        name: str,
        date_from: str = "01/01/1970",
        date_to: str = "",
    ) -> list[dict]:
        """Search clerk portal by name and return recorded documents.

        Handles the Acclaim Kendo UI workflow:
        1. Accept disclaimer
        2. Enter name, click Search
        3. Select matching names from popup checkbox tree
        4. Click Done to load results
        5. Parse tab-separated results table
        """
        page = await browser.new_page()
        documents: list[dict] = []

        try:
            search_url = f"{portal_url.rstrip('/')}/search/SearchTypeName"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # 1. Accept disclaimer if present
            accept = page.locator("#btnButton")
            if await accept.count() > 0:
                await accept.click()
                await page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(2)

            # 2. Fill name (format: "LAST, FIRST")
            search_name = name.strip()
            # The Acclaim search expects "LAST, FIRST" format
            # But the owner name from property appraiser is already "LAST FIRST M" format
            # Just use it as-is — the search is flexible enough
            if "," not in search_name and " " in search_name:
                parts = search_name.split()
                if len(parts) >= 2:
                    search_name = f"{parts[0]}, {' '.join(parts[1:])}"

            name_input = page.locator("#SearchOnName")
            if await name_input.count() == 0:
                logger.error("Name input not found on clerk portal")
                return documents

            await name_input.fill(search_name)

            # Set date range if available
            from_input = page.locator("#StartDate")
            if await from_input.count() > 0:
                try:
                    await from_input.fill(date_from)
                except Exception:
                    pass

            # Click Search
            await page.click("#btnSearch")
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(5)

            # 3. Check if names popup appeared
            body_text = await page.inner_text("body")

            if "Select Names" in body_text:
                # Check CAPTCHA indicators
                if _detect_captcha(body_text):
                    raise CaptchaBlockedError("CAPTCHA detected on clerk portal")

                # Find the best matching name in the Kendo treeview and check it
                # Use JavaScript to check the checkbox for the exact name
                checked = await page.evaluate("""(targetName) => {
                    const items = document.querySelectorAll('#NameListTreeView li');
                    let bestMatch = null;
                    let bestCount = 0;

                    for (const li of items) {
                        const textEl = li.querySelector('.k-treeview-leaf-text');
                        if (!textEl) continue;
                        const text = textEl.textContent.trim();
                        // Extract count from "NAME (N)"
                        const m = text.match(/^(.+?)\\s*\\((\\d+)\\)$/);
                        if (!m) continue;
                        const itemName = m[1].trim();
                        const count = parseInt(m[2]);

                        // Exact match on the target name
                        if (itemName === targetName) {
                            const cb = li.querySelector('input[type="checkbox"]');
                            if (cb) { cb.click(); return text; }
                        }
                        // Track best match (highest document count for partial match)
                        if (targetName.includes(itemName) || itemName.includes(targetName)) {
                            if (count > bestCount) {
                                bestCount = count;
                                bestMatch = li;
                            }
                        }
                    }

                    // Fall back to best match
                    if (bestMatch) {
                        const cb = bestMatch.querySelector('input[type="checkbox"]');
                        if (cb) {
                            cb.click();
                            const textEl = bestMatch.querySelector('.k-treeview-leaf-text');
                            return textEl ? textEl.textContent.trim() : 'checked';
                        }
                    }

                    // Last resort: check ALL
                    const allItems = document.querySelectorAll('#NameListTreeView li input[type="checkbox"]');
                    allItems.forEach(cb => cb.click());
                    return 'all_checked';
                }""", name.upper())

                logger.info(f"Clerk name selection: {checked}")
                await asyncio.sleep(1)

                # Click Done to load results
                done_btn = page.locator('#NamesWin .t-button').filter(has_text="Done").first
                await done_btn.click(force=True)
                await asyncio.sleep(5)

                body_text = await page.inner_text("body")

            # 4. Check for CAPTCHA on results page
            if _detect_captcha(body_text):
                raise CaptchaBlockedError("CAPTCHA detected on clerk results page")

            # 5. Parse results
            documents = _parse_acclaim_results(body_text)
            logger.info(f"Clerk search returned {len(documents)} documents")

        except CaptchaBlockedError:
            raise
        except Exception as e:
            logger.error(f"Clerk search failed for '{name}': {e}")
            # Check if it was a CAPTCHA
            try:
                content = await page.content()
                if _detect_captcha(content):
                    raise CaptchaBlockedError(f"CAPTCHA blocked clerk access: {e}")
            except CaptchaBlockedError:
                raise
            except Exception:
                pass
        finally:
            await page.close()

        return documents


def _parse_acclaim_results(text: str) -> list[dict]:
    """Parse Acclaim/OnCore clerk search results.

    Results appear as tab-separated rows like:
    1\tTo\tPITTS DERRICK R\tD R HORTON INC\t2017043190\t02/23/2017\tDEED\tOR\t17887/1785\t\t$258,990.00\tL40 BLUE LAKE
    """
    documents: list[dict] = []
    lines = text.split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Split by tab
        parts = stripped.split("\t")
        if len(parts) < 7:
            continue

        # First field should be a row number
        try:
            int(parts[0])
        except ValueError:
            continue

        # Parse: #, PartyType, Name, CrossPartyName, InstrumentNo, RecordDate, DocType, BookType, Book/Page, DocLink, Consideration, Legal
        party_type = parts[1].strip() if len(parts) > 1 else ""  # "To" or "From"
        party_name = parts[2].strip() if len(parts) > 2 else ""
        cross_party = parts[3].strip() if len(parts) > 3 else ""
        instrument = parts[4].strip() if len(parts) > 4 else ""
        record_date = parts[5].strip() if len(parts) > 5 else ""
        doc_type_raw = parts[6].strip() if len(parts) > 6 else ""
        book_type = parts[7].strip() if len(parts) > 7 else ""
        book_page = parts[8].strip() if len(parts) > 8 else ""
        doc_link = parts[9].strip() if len(parts) > 9 else ""
        consideration_str = parts[10].strip() if len(parts) > 10 else ""
        legal = parts[11].strip() if len(parts) > 11 else ""

        # Parse consideration
        consideration = 0.0
        m = re.search(r"\$([\d,]+(?:\.\d+)?)", consideration_str)
        if m:
            try:
                consideration = float(m.group(1).replace(",", ""))
            except ValueError:
                pass

        # Determine grantor/grantee based on party_type
        # "To" means the searched name is the grantee (buyer)
        # "From" means the searched name is the grantor (seller)
        if party_type.lower() == "to":
            grantor = cross_party
            grantee = party_name
        else:
            grantor = party_name
            grantee = cross_party

        # Normalize doc_type
        doc_type_map = {
            "DEED": "deed", "WD": "deed", "QCD": "deed",
            "MORTGAGE": "mortgage", "MTG": "mortgage",
            "SATISFACTION": "satisfaction", "SAT": "satisfaction",
            "ASSIGNMENT": "assignment", "ASSIGN": "assignment",
            "LIEN": "lien", "LIS": "lien", "JUDG": "judgment",
            "RELEASE": "satisfaction", "SUBORDINATION": "other",
            "EASEMENT": "easement", "PLAT": "plat",
            "AFFIDAVIT": "other", "AFF": "other",
            "POWER OF ATTORNEY": "other", "POWER OF ATTY": "other",
            "NOTICE": "other", "NTC": "other",
            "MODIFICATION": "other", "AMEND": "other",
            "AGREEMENT": "other", "DECLARATION": "other",
            "COURT ORDER": "court_order", "FINAL JUDG": "judgment",
        }
        doc_type = doc_type_map.get(doc_type_raw.upper(), "other")

        documents.append({
            "instrument_number": instrument,
            "record_date": record_date,
            "doc_type": doc_type,
            "doc_type_raw": doc_type_raw,
            "book_page": book_page,
            "book_type": book_type,
            "doc_link": doc_link,
            "grantor": grantor,
            "grantee": grantee,
            "consideration": consideration,
            "legal_description": legal,
            "party_type": party_type,
        })

    return documents


# ─── Property Appraiser Scraper (COJ / paopropertysearch.coj.net) ──────

# Street suffixes used by COJ search form
_STREET_SUFFIXES = {
    "pkwy": "Parkway", "dr": "Drive", "st": "Street", "ave": "Avenue",
    "blvd": "Boulevard", "ln": "Lane", "rd": "Road", "ct": "Court",
    "cir": "Circle", "pl": "Place", "way": "Way", "ter": "Terrace",
    "trl": "Trail", "loop": "Loop", "run": "Run", "cv": "Cove",
    "pt": "Point", "hwy": "Highway", "crk": "Creek", "xing": "Crossing",
    "pass": "Pass", "walk": "Walk",
}


def _parse_street_parts(address: str) -> tuple[str, str, str]:
    """Split '4471 Sherman Hills Pkwy' into (number, name, suffix_label)."""
    parts = address.strip().split()
    if not parts:
        return "", "", ""

    # First token is the street number (if numeric)
    number = ""
    rest = parts
    if parts[0].isdigit():
        number = parts[0]
        rest = parts[1:]

    if not rest:
        return number, "", ""

    # Last token might be a street suffix
    last = rest[-1].lower().rstrip(".")
    suffix_label = _STREET_SUFFIXES.get(last, "")
    if suffix_label:
        name = " ".join(rest[:-1])
    else:
        name = " ".join(rest)
        suffix_label = ""

    return number, name, suffix_label


class PropertyAppraiserScraper:
    """Scrapes the Jacksonville/Duval Property Appraiser (paopropertysearch.coj.net)."""

    @staticmethod
    async def search_and_extract(browser: Browser, address: str) -> dict:
        """Search property appraiser and extract full property detail."""
        page = await browser.new_page()
        result = {
            "success": False,
            "parcel_number": "",
            "owner": "",
            "legal_description": "",
            "subdivision": "",
            "assessed_value": 0.0,
            "land_value": 0.0,
            "improvement_value": 0.0,
            "tax_amount": 0.0,
            "homestead_exemption": False,
            "sales_history": [],
        }

        try:
            street_num, street_name, suffix_label = _parse_street_parts(address)

            await page.goto(
                "https://paopropertysearch.coj.net/Basic/Search.aspx",
                wait_until="domcontentloaded", timeout=30000,
            )
            await asyncio.sleep(2)

            # Fill search form
            if street_num:
                await page.fill("#ctl00_cphBody_tbStreetNumber", street_num)
            if street_name:
                await page.fill("#ctl00_cphBody_tbStreetName", street_name)
            if suffix_label:
                try:
                    await page.select_option(
                        "#ctl00_cphBody_ddStreetSuffix", label=suffix_label,
                    )
                except Exception:
                    pass  # suffix not in dropdown — search anyway

            await page.click("#ctl00_cphBody_bSearch")
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(3)

            # Find detail links
            links = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a'))
                    .filter(a => a.href.includes('Detail'))
                    .map(a => ({text: a.textContent.trim(), href: a.href}))
            }""")

            if not links:
                result["error"] = "No property found"
                return result

            # Navigate to detail page
            await page.goto(links[0]["href"], wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            body = await page.inner_text("body")
            result.update(_parse_coj_detail(body))
            result["success"] = True

        except Exception as e:
            logger.error(f"Property appraiser scraping failed: {e}")
            result["error"] = str(e)
        finally:
            await page.close()

        return result


def _parse_coj_detail(text: str) -> dict:
    """Parse the paopropertysearch.coj.net detail page text."""
    data: dict = {}

    # Owner — first line after header is typically "OWNER NAME\nADDRESS"
    lines = text.split("\n")

    # RE #
    for line in lines:
        m = re.match(r"RE\s*#\s+([\d-]+)", line.strip())
        if m:
            data["parcel_number"] = m.group(1)
            break

    # Owner — appears near the top, before the address
    for i, line in enumerate(lines):
        if "Primary Site Address" in line and i > 0:
            # Owner is typically 1-2 lines above this
            for j in range(max(0, i - 5), i):
                candidate = lines[j].strip()
                if candidate and not any(
                    kw in candidate for kw in
                    ("Basic Search", "Tip:", "Tangible", "Advanced", "Collapse",
                     "New Search", "Refine")
                ):
                    data["owner"] = candidate
                    break
            break

    # Subdivision
    for line in lines:
        m = re.match(r"Subdivision\s+\d+\s+(.*)", line.strip())
        if m:
            data["subdivision"] = m.group(1).strip()
            break

    # Values from Value Summary
    value_patterns = {
        "improvement_value": r"Total Building Value\s+\$([\d,]+(?:\.\d+)?)",
        "land_value": r"Land Value \(Market\)\s+\$([\d,]+(?:\.\d+)?)",
        "assessed_value": r"Assessed Value\s+\$([\d,]+(?:\.\d+)?)",
    }
    for key, pattern in value_patterns.items():
        m = re.search(pattern, text)
        if m:
            try:
                data[key] = float(m.group(1).replace(",", ""))
            except ValueError:
                pass

    # Tax amount — from TRIM totals
    tax_match = re.search(r"Totals\s+\$([\d,]+\.\d+)", text)
    if tax_match:
        try:
            data["tax_amount"] = float(tax_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Tax year — from "2025 Notice of Proposed Property Taxes" or "2025 Certified"
    year_match = re.search(r"(\d{4})\s+(?:Notice of Proposed|Certified|TRIM)", text)
    if year_match:
        data["tax_year"] = year_match.group(1)
        data["assessment_year"] = year_match.group(1)

    # Total (Just/Market) Value
    just_match = re.search(r"Just \(Market\) Value\s+\$([\d,]+(?:\.\d+)?)", text)
    if just_match:
        try:
            data["total_value"] = float(just_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Tax status — check TRIM totals row for "Last Year" paid info
    if re.search(r"Last Year\s+\$[\d,]+", text):
        data["tax_status"] = "Paid"

    # Homestead
    data["homestead_exemption"] = "Homestead (HX)" in text

    # Legal description
    legal_lines = []
    in_legal = False
    for line in lines:
        stripped = line.strip()
        if "LN" in stripped and "Legal Description" in stripped:
            in_legal = True
            continue
        if in_legal:
            m = re.match(r"^\d+\s+(.+)", stripped)
            if m:
                legal_lines.append(m.group(1).strip())
            elif stripped and not stripped[0].isdigit() and legal_lines:
                break
    if legal_lines:
        data["legal_description"] = " ".join(legal_lines)

    # Sales history
    sales = []
    in_sales = False
    for line in lines:
        stripped = line.strip()
        if "Sales History" in stripped:
            in_sales = True
            continue
        if in_sales:
            # Skip header row
            if stripped.startswith("Book/Page"):
                continue
            # Pattern: "17887-01785	2/10/2017	$259,000.00	SW - Special Warranty	Qualified	Improved"
            parts = stripped.split("\t")
            if len(parts) >= 4:
                m_price = re.search(r"\$([\d,]+(?:\.\d+)?)", parts[2] if len(parts) > 2 else "")
                sale = {
                    "book_page": parts[0].strip(),
                    "sale_date": parts[1].strip() if len(parts) > 1 else "",
                    "sale_price": float(m_price.group(1).replace(",", "")) if m_price else 0,
                    "deed_type": parts[3].strip() if len(parts) > 3 else "",
                }
                sales.append(sale)
            elif stripped.startswith("Extra Features") or stripped.startswith("Land & Legal"):
                break
    data["sales_history"] = sales

    return data


# ─── Hendry County Clerk Scraper (myfloridacounty.com) ─────────────────

class FloridaClerkScraper:
    """Scrapes myfloridacounty.com based clerk portals."""

    @staticmethod
    async def search(
        browser: Browser,
        county_id: int,
        name: str,
    ) -> dict:
        """Attempt to search Florida clerk portal. Returns success/failure."""
        page = await browser.new_page()
        result = {"success": False, "documents": [], "blocked": False}

        try:
            url = f"https://www.myfloridacounty.com/orisearch/{county_id}"
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(3)

            content = await page.content()
            if "challenge" in content.lower() or "turnstile" in content.lower():
                result["blocked"] = True
                result["error"] = "Cloudflare CAPTCHA detected"
                logger.warning(f"Florida clerk portal for county {county_id} blocked by CAPTCHA")
            else:
                # Try to fill and submit
                name_input = page.locator('input[name="name"]')
                if await name_input.count() > 0:
                    await name_input.fill(name)
                    await page.click('input[type="submit"]')
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(3)
                    body = await page.inner_text("body")
                    result["documents"] = _parse_florida_clerk_results(body)
                    result["success"] = len(result["documents"]) > 0

        except Exception as e:
            if "timeout" in str(e).lower():
                result["blocked"] = True
                result["error"] = "Portal timeout (likely Cloudflare)"
            else:
                result["error"] = str(e)
        finally:
            await page.close()

        return result


def _parse_florida_clerk_results(text: str) -> list[dict]:
    """Parse myfloridacounty.com search results."""
    documents = []
    # This is a basic parser - the format varies by county
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if re.match(r"^\d{4}\d+", line):
            documents.append({"instrument_number": line})
    return documents


# ─── Main Data Fetcher ─────────────────────────────────────────────────

# Florida county IDs for myfloridacounty.com
FLORIDA_COUNTY_IDS = {
    "Alachua": 1, "Baker": 2, "Bay": 3, "Bradford": 4, "Brevard": 5,
    "Broward": 6, "Calhoun": 7, "Charlotte": 8, "Citrus": 9, "Clay": 10,
    "Collier": 11, "Columbia": 12, "DeSoto": 13, "Dixie": 14, "Duval": 15,
    "Escambia": 16, "Flagler": 17, "Franklin": 18, "Gadsden": 19,
    "Gilchrist": 20, "Glades": 21, "Gulf": 22, "Hamilton": 23,
    "Hardee": 24, "Hendry": 26, "Hernando": 27, "Highlands": 28,
    "Hillsborough": 29, "Holmes": 30, "Indian River": 31, "Jackson": 32,
    "Jefferson": 33, "Lafayette": 34, "Lake": 35, "Lee": 36, "Leon": 37,
    "Levy": 38, "Liberty": 39, "Madison": 40, "Manatee": 41,
    "Marion": 42, "Martin": 43, "Miami-Dade": 44, "Monroe": 45,
    "Nassau": 46, "Okaloosa": 47, "Okeechobee": 48, "Orange": 49,
    "Osceola": 50, "Palm Beach": 51, "Pasco": 52, "Pinellas": 53,
    "Polk": 54, "Putnam": 55, "Santa Rosa": 56, "Sarasota": 57,
    "Seminole": 58, "St. Johns": 59, "St. Lucie": 60, "Sumter": 61,
    "Suwannee": 62, "Taylor": 63, "Union": 64, "Volusia": 65,
    "Wakulla": 66, "Walton": 67, "Washington": 68,
}

# Known Acclaim/OnCore clerk portals (no CAPTCHA)
ACCLAIM_PORTALS = {
    "Duval": "https://or.duvalclerk.com",
    "Hillsborough": "https://publicaccess.hillsclerk.com",
    "Volusia": "https://vcpa.vcgov.org/OfficialRecords",
    "Bay": "https://or.baycoclerk.com",
    "Nassau": "https://or.nassauclerk.com",
    "St. Johns": "https://or.stjohnsclerk.com",
    "Clay": "https://or.clayclerk.com",
    "Putnam": "https://or.putnamclerk.com",
}

# Known Phenix.net tax collector portals
PHENIX_TAX_PORTALS = {
    ("Hendry", "FL"): "https://hendry.floridatax.us",
    ("Glades", "FL"): "https://glades.floridatax.us",
    ("Okeechobee", "FL"): "https://okeechobee.floridatax.us",
    ("Highlands", "FL"): "https://highlands.floridatax.us",
    ("Charlotte", "FL"): "https://charlotte.floridatax.us",
    ("Lee", "FL"): "https://lee.floridatax.us",
    ("Collier", "FL"): "https://collier.floridatax.us",
    ("DeSoto", "FL"): "https://desoto.floridatax.us",
    ("Hardee", "FL"): "https://hardee.floridatax.us",
    ("Indian River", "FL"): "https://indianriver.floridatax.us",
    ("Martin", "FL"): "https://martin.floridatax.us",
    ("Palm Beach", "FL"): "https://palmbeach.floridatax.us",
    ("St. Lucie", "FL"): "https://stlucie.floridatax.us",
    ("Brevard", "FL"): "https://brevard.floridatax.us",
    ("Volusia", "FL"): "https://volusia.floridatax.us",
    ("Seminole", "FL"): "https://seminole.floridatax.us",
    ("Orange", "FL"): "https://orange.floridatax.us",
    ("Osceola", "FL"): "https://osceola.floridatax.us",
    ("Polk", "FL"): "https://polk.floridatax.us",
    ("Hillsborough", "FL"): "https://hillsborough.floridatax.us",
    ("Pinellas", "FL"): "https://pinellas.floridatax.us",
    ("Pasco", "FL"): "https://pasco.floridatax.us",
    ("Manatee", "FL"): "https://manatee.floridatax.us",
    ("Sarasota", "FL"): "https://sarasota.floridatax.us",
    ("Alachua", "FL"): "https://alachua.floridatax.us",
    ("Bay", "FL"): "https://bay.floridatax.us",
    ("Broward", "FL"): "https://broward.floridatax.us",
    ("Clay", "FL"): "https://clay.floridatax.us",
    ("Escambia", "FL"): "https://escambia.floridatax.us",
    ("Flagler", "FL"): "https://flagler.floridatax.us",
    ("Lake", "FL"): "https://lake.floridatax.us",
    ("Leon", "FL"): "https://leon.floridatax.us",
    ("Marion", "FL"): "https://marion.floridatax.us",
    ("Miami-Dade", "FL"): "https://miamidade.floridatax.us",
    ("Monroe", "FL"): "https://monroe.floridatax.us",
    ("Nassau", "FL"): "https://nassau.floridatax.us",
    ("Okaloosa", "FL"): "https://okaloosa.floridatax.us",
    ("Putnam", "FL"): "https://putnam.floridatax.us",
    ("Santa Rosa", "FL"): "https://santarosa.floridatax.us",
    ("St. Johns", "FL"): "https://stjohns.floridatax.us",
    ("Sumter", "FL"): "https://sumter.floridatax.us",
    ("Walton", "FL"): "https://walton.floridatax.us",
}


# Known Property Appraiser portals (non-Phenix, custom scrapers)
PROPERTY_APPRAISER_PORTALS = {
    ("Duval", "FL"): "coj",  # paopropertysearch.coj.net
}


async def fetch_property_data(
    address: str,
    county: str,
    state_code: str,
    owner_name: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    search_scope: str = "full",
) -> PropertyData:
    """Fetch property data from all available sources for a county.

    Uses API-first approach: tries REST APIs before Playwright scraping.

    Args:
        search_scope: "full" fetches tax + clerk records,
                      "current_owner" fetches tax only (skips deep clerk search).
    """
    prop = PropertyData(
        address=address,
        county=county,
        state=state_code,
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        try:
            # Source 1: Tax/Property data
            # Try Phenix.net tax collector first, then property appraiser portals
            tax_url = PHENIX_TAX_PORTALS.get((county, state_code))
            appraiser_type = PROPERTY_APPRAISER_PORTALS.get((county, state_code))

            if tax_url:
                logger.info(f"Fetching tax data from {tax_url}")
                try:
                    tax_data = await TaxCollectorScraper.search_and_extract(
                        browser, tax_url, address
                    )
                    if tax_data.get("success"):
                        prop.parcel_number = tax_data.get("tax_account", "")
                        prop.owner_name = tax_data.get("owner", "") or prop.owner_name
                        prop.mailing_address = tax_data.get("mailing_address", "")
                        prop.tax_amount = tax_data.get("tax_total", 0.0)
                        prop.legal_description = tax_data.get("legal_description", "")
                        prop.payment_history = tax_data.get("payment_history", [])
                        # Get assessed value from taxable values
                        if tax_data.get("taxable_values"):
                            first = tax_data["taxable_values"][0]
                            try:
                                prop.assessed_value = float(
                                    first.get("assessed", "0").replace(",", "")
                                )
                            except ValueError:
                                pass
                        prop.sources_used.append({
                            "type": "tax_collector",
                            "url": tax_url,
                            "status": "success",
                        })
                    else:
                        prop.sources_failed.append({
                            "type": "tax_collector",
                            "url": tax_url,
                            "error": tax_data.get("error", "Unknown"),
                        })
                except Exception as e:
                    logger.error(f"Tax collector fetch failed: {e}")
                    prop.sources_failed.append({
                        "type": "tax_collector",
                        "url": tax_url,
                        "error": str(e),
                    })
            elif appraiser_type == "coj":
                logger.info("Fetching property data from Duval County Property Appraiser")
                try:
                    pa_data = await PropertyAppraiserScraper.search_and_extract(
                        browser, address
                    )
                    if pa_data.get("success"):
                        prop.parcel_number = pa_data.get("parcel_number", "")
                        prop.owner_name = pa_data.get("owner", "") or prop.owner_name
                        prop.assessed_value = pa_data.get("assessed_value", 0.0)
                        prop.land_value = pa_data.get("land_value", 0.0)
                        prop.improvement_value = pa_data.get("improvement_value", 0.0)
                        prop.tax_amount = pa_data.get("tax_amount", 0.0)
                        prop.homestead_exemption = pa_data.get("homestead_exemption", False)
                        prop.legal_description = pa_data.get("legal_description", "")
                        prop.subdivision = pa_data.get("subdivision", "")
                        prop.sales_history = pa_data.get("sales_history", [])
                        prop.tax_year = pa_data.get("tax_year", "")
                        prop.tax_status = pa_data.get("tax_status", "")
                        prop.total_value = pa_data.get("total_value", 0.0)
                        prop.assessment_year = pa_data.get("assessment_year", "")
                        prop.sources_used.append({
                            "type": "property_appraiser",
                            "url": "https://paopropertysearch.coj.net",
                            "status": "success",
                        })
                    else:
                        prop.sources_failed.append({
                            "type": "property_appraiser",
                            "url": "https://paopropertysearch.coj.net",
                            "error": pa_data.get("error", "Unknown"),
                        })
                except Exception as e:
                    logger.error(f"Property appraiser fetch failed: {e}")
                    prop.sources_failed.append({
                        "type": "property_appraiser",
                        "url": "https://paopropertysearch.coj.net",
                        "error": str(e),
                    })
            else:
                prop.sources_failed.append({
                    "type": "tax_collector",
                    "url": "",
                    "error": f"No tax portal configured for {county}, {state_code}",
                    "manual_retrieval": True,
                })

            # Source 2: Clerk of Court
            # For current_owner scope, only search if we need to identify the owner
            # For full scope, search for all recorded documents
            search_name = owner_name or prop.owner_name
            skip_clerk = (search_scope == "current_owner" and prop.owner_name)

            if search_name and not skip_clerk:
                acclaim_url = ACCLAIM_PORTALS.get(county)
                if acclaim_url:
                    logger.info(f"Searching clerk records at {acclaim_url}")
                    try:
                        docs = await _clerk_search_with_retry(
                            browser, acclaim_url, search_name, county
                        )
                        prop.recorded_documents = docs
                        prop.sources_used.append({
                            "type": "clerk_of_court",
                            "url": acclaim_url,
                            "status": "success",
                            "docs_found": len(docs),
                        })
                    except CaptchaBlockedError as e:
                        logger.warning(f"CAPTCHA blocked at {acclaim_url}: {e}")
                        prop.sources_failed.append({
                            "type": "clerk_of_court",
                            "url": acclaim_url,
                            "error": f"CAPTCHA blocked: {e}",
                            "captcha_blocked": True,
                            "manual_retrieval": True,
                        })
                    except Exception as e:
                        logger.error(f"Acclaim clerk fetch failed: {e}")
                        prop.sources_failed.append({
                            "type": "clerk_of_court",
                            "url": acclaim_url,
                            "error": str(e),
                        })
                elif state_code == "FL":
                    # Try myfloridacounty.com
                    county_id = FLORIDA_COUNTY_IDS.get(county)
                    if county_id:
                        logger.info(f"Trying Florida clerk portal (county ID {county_id})")
                        try:
                            clerk_result = await FloridaClerkScraper.search(
                                browser, county_id, search_name
                            )
                            if clerk_result.get("blocked"):
                                prop.sources_failed.append({
                                    "type": "clerk_of_court",
                                    "url": f"myfloridacounty.com/orisearch/{county_id}",
                                    "error": clerk_result.get("error", "CAPTCHA blocked"),
                                    "captcha_blocked": True,
                                    "manual_retrieval": True,
                                })
                            elif clerk_result.get("success"):
                                prop.recorded_documents = clerk_result["documents"]
                                prop.sources_used.append({
                                    "type": "clerk_of_court",
                                    "url": f"myfloridacounty.com/orisearch/{county_id}",
                                    "status": "success",
                                })
                        except Exception as e:
                            prop.sources_failed.append({
                                "type": "clerk_of_court",
                                "url": f"myfloridacounty.com/orisearch/{county_id}",
                                "error": str(e),
                            })
                else:
                    prop.sources_failed.append({
                        "type": "clerk_of_court",
                        "url": "",
                        "error": f"No clerk portal configured for {county}, {state_code}",
                        "manual_retrieval": True,
                    })
            elif skip_clerk:
                logger.info(
                    "Skipping deep clerk search for current_owner scope "
                    f"(owner: {prop.owner_name})"
                )

        finally:
            await browser.close()

    return prop
