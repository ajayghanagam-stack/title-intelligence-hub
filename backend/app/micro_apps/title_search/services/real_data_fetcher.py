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
    tax_amount: float = 0.0
    tax_year: str = ""
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
        """Search clerk portal by name and return recorded documents."""
        page = await browser.new_page()
        documents = []

        try:
            search_url = f"{portal_url.rstrip('/')}/search/SearchTypeName"
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Accept disclaimer if present
            accept = page.locator('#btnButton')
            if await accept.count() > 0:
                await accept.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)

            # Fill name search
            name_input = page.locator('#SearchOnName')
            if await name_input.count() == 0:
                logger.error("Name input not found on clerk portal")
                return documents

            await name_input.fill(name)

            # Set date range
            from_input = page.locator('#StartDate')
            if await from_input.count() > 0:
                await from_input.fill(date_from)
            if date_to:
                to_input = page.locator('#EndDate')
                if await to_input.count() > 0:
                    await to_input.fill(date_to)

            await page.click('input[value="Search"]')
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)

            # Parse the name list that appears
            body_text = await page.inner_text("body")

            # Check if we got name matches
            if "Select Names" in body_text:
                # Select all names and search
                select_all = page.locator('a:has-text("All")')
                if await select_all.count() > 0:
                    await select_all.first.click()
                    await asyncio.sleep(1)

                # Submit the selected names
                search_btn = page.locator('#btnSearch, input[value="Search"]')
                if await search_btn.count() > 0:
                    await search_btn.first.click()
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(3)

                # Now parse the results table
                body_text = await page.inner_text("body")

            documents = _parse_clerk_results(body_text)

        except Exception as e:
            logger.error(f"Clerk search failed for '{name}': {e}")
        finally:
            await page.close()

        return documents


def _parse_clerk_results(text: str) -> list[dict]:
    """Parse Acclaim/OnCore clerk search results."""
    documents = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Look for document type patterns (e.g. "WD", "QCD", "MTG", "SAT", "ASSIGN")
        if re.match(r"^\d{4}\d+$", line):
            doc = {"instrument_number": line}
            # Next lines typically: book/page, record date, doc type, parties
            for j in range(1, min(6, len(lines) - i)):
                next_line = lines[i + j].strip() if i + j < len(lines) else ""
                if re.match(r"^\d{2}/\d{2}/\d{4}$", next_line):
                    doc["record_date"] = next_line
                elif "/" in next_line and re.match(r"^\d+/\d+$", next_line):
                    doc["book_page"] = next_line
                elif next_line in ("WD", "QCD", "MTG", "SAT", "ASSIGN", "DEED",
                                   "NTC", "LIS", "JUDG", "RELEASE", "EASEMENT",
                                   "AFFIDAVIT", "AFF", "AMENDMENT", "AMEND",
                                   "AGREEMENT", "ASSIGN MTG", "COURT ORDER",
                                   "FINAL JUDG", "SUBORDINATION", "POWER OF ATTY",
                                   "DECLARATION", "PLAT", "SURVEY", "NOTICE",
                                   "SATISFACTION", "MODIFICATION"):
                    doc["doc_type"] = next_line
            if doc.get("record_date") or doc.get("doc_type"):
                documents.append(doc)
        i += 1
    return documents


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
}


async def fetch_property_data(
    address: str,
    county: str,
    state_code: str,
    owner_name: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
) -> PropertyData:
    """Fetch property data from all available sources for a county.

    Uses API-first approach: tries REST APIs before Playwright scraping.
    """
    prop = PropertyData(
        address=address,
        county=county,
        state=state_code,
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        try:
            # Source 1: Tax Collector (Phenix.net) - highest success rate
            tax_url = PHENIX_TAX_PORTALS.get((county, state_code))
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
            else:
                prop.sources_failed.append({
                    "type": "tax_collector",
                    "url": "",
                    "error": f"No tax portal configured for {county}, {state_code}",
                    "manual_retrieval": True,
                })

            # Source 2: Clerk of Court - try Acclaim portals first, then Florida clerk
            search_name = owner_name or prop.owner_name
            if search_name:
                acclaim_url = ACCLAIM_PORTALS.get(county)
                if acclaim_url:
                    logger.info(f"Searching clerk records at {acclaim_url}")
                    try:
                        docs = await ClerkOfCourtScraper.search_by_name(
                            browser, acclaim_url, search_name
                        )
                        prop.recorded_documents = docs
                        prop.sources_used.append({
                            "type": "clerk_of_court",
                            "url": acclaim_url,
                            "status": "success",
                            "docs_found": len(docs),
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

        finally:
            await browser.close()

    return prop
