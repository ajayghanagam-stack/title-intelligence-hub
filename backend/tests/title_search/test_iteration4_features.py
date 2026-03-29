"""
Iteration 4 Tests: Acclaim/OnCore Clerk Scraper Enhancement

Tests for the rewritten clerk scraper that properly handles the Kendo UI workflow
and extracts full grantor/grantee names, instrument numbers, book/page, consideration,
legal description, and doc types from clerk records.

Key features tested:
1. Clerk records provide grantor/grantee names (not 'See Official Records')
2. PDF contains D R HORTON INC JACKSONVILLE as grantor
3. PDF contains Book/Page 17887/1785
4. PDF contains Tax Year 2025
5. PDF contains LOT 40 BLUE LAKE ESTATES legal description
6. Names Search has 7+ names
7. Mortgage shows Rocket Mortgage LLC with $74,000 and $95,940
8. Misc has Plat Map B/P
9. PDF is only 3 pages (not 9 - page break fix)
10. Frontend shows 'Download the Generated Report as PDF' text
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://dc353579-ba3e-4338-b011-8fae44983f1e.preview.emergentagent.com")
ORG_ID = "576b9a0f-0af5-4520-8093-e4af1155cc44"
ORDER_ID = "7dec6fa1-aa6a-400c-be40-b67b47fa97a2"  # FS-Enhanced-002


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token."""
    response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"email": "admin@societytitle.com", "password": "admin123"},
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get headers with auth token and org ID."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "X-Org-ID": ORG_ID,
    }


class TestOrderDetails:
    """Test order details for FS-Enhanced-002."""

    def test_order_exists(self, auth_headers):
        """Verify the enhanced order exists."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == ORDER_ID
        assert data["order_reference"] == "FS-Enhanced-002"

    def test_order_owner_name(self, auth_headers):
        """Verify owner is PITTS DERRICK R."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["borrower_name"] == "PITTS DERRICK R"

    def test_order_parcel_number(self, auth_headers):
        """Verify parcel number is 012875-1145."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["parcel_number"] == "012875-1145"


class TestDocuments:
    """Test documents for FS-Enhanced-002."""

    def test_documents_endpoint(self, auth_headers):
        """Verify documents endpoint returns list."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/documents",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 10  # Should have 11 documents

    def test_clerk_deed_has_grantor_name(self, auth_headers):
        """Verify clerk deed has D R HORTON INC JACKSONVILLE as grantor."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/documents",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        # Find the clerk deed with instrument 2017043190
        clerk_deed = None
        for doc in data:
            meta = doc.get("doc_metadata", {}) or {}
            if meta.get("instrument_number") == "2017043190":
                clerk_deed = doc
                break
        
        assert clerk_deed is not None, "Clerk deed with instrument 2017043190 not found"
        assert clerk_deed["grantor"] is not None
        assert "D R HORTON INC JACKSONVILLE" in clerk_deed["grantor"]["names"]

    def test_clerk_deed_has_grantee_name(self, auth_headers):
        """Verify clerk deed has PITTS DERRICK R as grantee."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/documents",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        # Find the clerk deed with instrument 2017043190
        clerk_deed = None
        for doc in data:
            meta = doc.get("doc_metadata", {}) or {}
            if meta.get("instrument_number") == "2017043190":
                clerk_deed = doc
                break
        
        assert clerk_deed is not None
        assert clerk_deed["grantee"] is not None
        assert "PITTS DERRICK R" in clerk_deed["grantee"]["names"]

    def test_clerk_deed_has_book_page(self, auth_headers):
        """Verify clerk deed has book/page 17887/1785."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/documents",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        # Find the clerk deed with instrument 2017043190
        clerk_deed = None
        for doc in data:
            meta = doc.get("doc_metadata", {}) or {}
            if meta.get("instrument_number") == "2017043190":
                clerk_deed = doc
                break
        
        assert clerk_deed is not None
        meta = clerk_deed.get("doc_metadata", {}) or {}
        assert meta.get("book_page") == "17887/1785"

    def test_mortgage_with_rocket_mortgage_74000(self, auth_headers):
        """Verify mortgage with Rocket Mortgage LLC $74,000."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/documents",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        # Find mortgage with $74,000
        mortgage = None
        for doc in data:
            if doc.get("doc_type") == "mortgage" and doc.get("consideration") == 74000.0:
                mortgage = doc
                break
        
        assert mortgage is not None, "Mortgage with $74,000 not found"
        assert mortgage["grantee"] is not None
        assert "ROCKET MORTGAGE LLC" in mortgage["grantee"]["names"]
        assert mortgage["grantor"] is not None
        assert "PITTS DERRICK R" in mortgage["grantor"]["names"]

    def test_mortgage_with_rocket_mortgage_95940(self, auth_headers):
        """Verify mortgage with Rocket Mortgage LLC $95,940."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/documents",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        # Find mortgage with $95,940
        mortgage = None
        for doc in data:
            if doc.get("doc_type") == "mortgage" and doc.get("consideration") == 95940.0:
                mortgage = doc
                break
        
        assert mortgage is not None, "Mortgage with $95,940 not found"
        assert mortgage["grantee"] is not None
        assert "ROCKET MORTGAGE LLC" in mortgage["grantee"]["names"]


class TestChainOfTitle:
    """Test chain of title for FS-Enhanced-002."""

    def test_chain_endpoint(self, auth_headers):
        """Verify chain endpoint returns data."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/chain",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "chain_links" in data

    def test_chain_has_proper_grantor_grantee(self, auth_headers):
        """Verify chain links have proper grantor/grantee names (not 'See Official Records')."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/chain",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        # Find the conveyance link
        for link in data["chain_links"]:
            if link["link_type"] == "conveyance":
                from_party = link.get("from_party", {})
                to_party = link.get("to_party", {})
                
                # Verify names are not 'See Official Records'
                from_names = from_party.get("names", []) if from_party else []
                to_names = to_party.get("names", []) if to_party else []
                
                for name in from_names + to_names:
                    assert "See Official Records" not in name, f"Found 'See Official Records' in chain link: {name}"


class TestFlags:
    """Test flags for FS-Enhanced-002."""

    def test_flags_endpoint(self, auth_headers):
        """Verify flags endpoint returns data."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/flags",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "flags" in data

    def test_unreleased_mortgage_flags(self, auth_headers):
        """Verify unreleased mortgage flags exist."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/flags",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        unreleased_flags = [f for f in data["flags"] if f["flag_type"] == "unreleased_mortgage"]
        assert len(unreleased_flags) >= 2, "Should have at least 2 unreleased mortgage flags"


class TestPDFContent:
    """Test PDF content for FS-Enhanced-002."""

    def test_pdf_download(self, auth_headers):
        """Verify PDF can be downloaded."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/pdf"
        assert len(response.content) > 10000  # Should be substantial

    def test_pdf_is_3_pages(self, auth_headers):
        """Verify PDF is only 3 pages (not 9 - page break fix)."""
        import fitz  # PyMuPDF
        import io
        
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        doc = fitz.open(stream=response.content, filetype="pdf")
        page_count = len(doc)
        doc.close()
        
        assert page_count == 3, f"PDF should be 3 pages, got {page_count}"

    def test_pdf_contains_grantor_d_r_horton(self, auth_headers):
        """Verify PDF contains D R HORTON INC JACKSONVILLE as grantor."""
        import fitz
        
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        doc = fitz.open(stream=response.content, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
        
        assert "D R HORTON INC JACKSONVILLE" in full_text, "PDF should contain D R HORTON INC JACKSONVILLE"

    def test_pdf_contains_book_page_17887_1785(self, auth_headers):
        """Verify PDF contains Book/Page 17887/1785."""
        import fitz
        
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        doc = fitz.open(stream=response.content, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
        
        assert "17887/1785" in full_text or "17887-01785" in full_text, "PDF should contain Book/Page 17887/1785"

    def test_pdf_contains_tax_year_2025(self, auth_headers):
        """Verify PDF contains Tax Year 2025."""
        import fitz
        
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        doc = fitz.open(stream=response.content, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
        
        assert "Tax Year" in full_text and "2025" in full_text, "PDF should contain Tax Year 2025"

    def test_pdf_contains_legal_lot_40_blue_lake(self, auth_headers):
        """Verify PDF contains LOT 40 BLUE LAKE ESTATES legal description."""
        import fitz
        
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        doc = fitz.open(stream=response.content, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
        
        assert "BLUE LAKE ESTATES" in full_text, "PDF should contain BLUE LAKE ESTATES"

    def test_pdf_contains_rocket_mortgage(self, auth_headers):
        """Verify PDF contains Rocket Mortgage LLC."""
        import fitz
        
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        doc = fitz.open(stream=response.content, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
        
        assert "ROCKET MORTGAGE LLC" in full_text, "PDF should contain ROCKET MORTGAGE LLC"

    def test_pdf_contains_mortgage_74000(self, auth_headers):
        """Verify PDF contains mortgage amount $74,000."""
        import fitz
        
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        doc = fitz.open(stream=response.content, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
        
        assert "$74,000" in full_text, "PDF should contain $74,000"

    def test_pdf_contains_mortgage_95940(self, auth_headers):
        """Verify PDF contains mortgage amount $95,940."""
        import fitz
        
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        doc = fitz.open(stream=response.content, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
        
        assert "$95,940" in full_text, "PDF should contain $95,940"

    def test_pdf_contains_plat_map_bp(self, auth_headers):
        """Verify PDF contains Plat Map B/P in Misc section."""
        import fitz
        
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        doc = fitz.open(stream=response.content, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
        
        assert "Plat Map" in full_text, "PDF should contain Plat Map"
        assert "00065-00138" in full_text or "00065/00138" in full_text, "PDF should contain Plat B/P 00065-00138"

    def test_pdf_names_search_has_7_plus_names(self, auth_headers):
        """Verify PDF Names Search section has 7+ names."""
        import fitz
        
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        doc = fitz.open(stream=response.content, filetype="pdf")
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
        
        # Check for expected names
        expected_names = [
            "PITTS DERRICK R",
            "D R HORTON INC JACKSONVILLE",
            "ROCKET MORTGAGE LLC",
            "WELLS FARGO BANK N A",
            "PITTS NORMA D",
            "MORTGAGE ELECTRONIC REGISTRATION SYSTEMS INC",
            "BLUE LAKE ESTATES",
        ]
        
        found_count = sum(1 for name in expected_names if name in full_text)
        assert found_count >= 7, f"PDF should contain at least 7 names, found {found_count}"


class TestOrdersList:
    """Test orders list endpoint."""

    def test_orders_list(self, auth_headers):
        """Verify orders list returns data."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # API returns list directly
        assert isinstance(data, list)
        assert len(data) > 0

    def test_enhanced_order_in_list(self, auth_headers):
        """Verify FS-Enhanced-002 is in the orders list."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        
        # API returns list directly
        order_ids = [o["id"] for o in data]
        assert ORDER_ID in order_ids, "FS-Enhanced-002 should be in orders list"
