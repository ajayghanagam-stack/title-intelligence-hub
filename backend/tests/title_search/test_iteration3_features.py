"""
Iteration 3 Tests: PDF content verification and document naming
Tests for:
1. PDF section headers (orange branding)
2. PDF content: Tax Year 2025, Assessment Year 2025, Tax Status Paid, Total Value $391,818
3. Chain Book/Page 16178-01020
4. Plat in Misc Docs B/P 00065-00138
5. Names Search includes BLUE LAKE ESTATES UNIT 02
6. No double-type bug (e.g., "Warranty Deed Deed")
7. Documents endpoint returns meaningful names with plat type
"""

import os
import pytest
import requests
import fitz  # PyMuPDF

BASE_URL = os.environ.get("NEXT_PUBLIC_API_URL", "https://dc353579-ba3e-4338-b011-8fae44983f1e.preview.emergentagent.com")
ORG_ID = "576b9a0f-0af5-4520-8093-e4af1155cc44"
ORDER_ID = "5ad86920-8732-4191-b78e-8646a4700a32"


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


@pytest.fixture(scope="module")
def pdf_content(auth_headers):
    """Download and extract PDF content."""
    response = requests.get(
        f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
        headers=auth_headers,
    )
    assert response.status_code == 200, f"PDF download failed: {response.text}"
    
    # Save PDF temporarily
    pdf_path = "/tmp/test_iteration3.pdf"
    with open(pdf_path, "wb") as f:
        f.write(response.content)
    
    # Extract text
    doc = fitz.open(pdf_path)
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    doc.close()
    
    return full_text


class TestPDFContent:
    """Test PDF content matches expected values."""
    
    def test_tax_year_2025(self, pdf_content):
        """Verify Tax Year is 2025."""
        assert "Tax Year:" in pdf_content, "Tax Year label not found"
        assert "2025" in pdf_content, "Tax Year 2025 not found"
    
    def test_assessment_year_2025(self, pdf_content):
        """Verify Assessment Year is 2025."""
        assert "Assessment Year:" in pdf_content, "Assessment Year label not found"
        # Assessment Year should be 2025
        import re
        match = re.search(r"Assessment Year:\s*(\d+)", pdf_content)
        assert match, "Assessment Year value not found"
        assert match.group(1) == "2025", f"Assessment Year is {match.group(1)}, expected 2025"
    
    def test_tax_status_paid(self, pdf_content):
        """Verify Tax Status is Paid."""
        assert "Paid" in pdf_content, "Tax Status 'Paid' not found"
    
    def test_total_value(self, pdf_content):
        """Verify Total Value is $391,818."""
        assert "391,818" in pdf_content, "Total Value $391,818 not found"
    
    def test_chain_book_page(self, pdf_content):
        """Verify Chain Book/Page 16178-01020 is present."""
        assert "16178-01020" in pdf_content, "Chain Book/Page 16178-01020 not found"
    
    def test_plat_in_misc_docs(self, pdf_content):
        """Verify Plat B/P 00065-00138 is in Misc Docs."""
        assert "00065-00138" in pdf_content, "Plat B/P 00065-00138 not found"
        assert "Plat Map" in pdf_content, "Plat Map reference not found"
    
    def test_names_search_subdivision(self, pdf_content):
        """Verify Names Search includes BLUE LAKE ESTATES."""
        assert "BLUE LAKE ESTATES" in pdf_content, "BLUE LAKE ESTATES not found in Names Search"
    
    def test_no_double_type_bug(self, pdf_content):
        """Verify no double-type bug (e.g., 'Warranty Deed Deed')."""
        assert "Warranty Deed Deed" not in pdf_content, "Double-type bug: 'Warranty Deed Deed' found"
        assert "Plat Book Deed" not in pdf_content, "Double-type bug: 'Plat Book Deed' found"
        assert "Plat Map Deed" not in pdf_content, "Double-type bug: 'Plat Map Deed' found"


class TestDocumentsEndpoint:
    """Test documents endpoint returns correct data."""
    
    def test_documents_list(self, auth_headers):
        """Verify documents endpoint returns list."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/documents",
            headers=auth_headers,
        )
        assert response.status_code == 200, f"Documents endpoint failed: {response.text}"
        docs = response.json()
        assert len(docs) >= 3, f"Expected at least 3 documents, got {len(docs)}"
    
    def test_plat_document_type(self, auth_headers):
        """Verify plat document has correct type."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/documents",
            headers=auth_headers,
        )
        assert response.status_code == 200
        docs = response.json()
        
        plat_docs = [d for d in docs if d["doc_type"] == "plat"]
        assert len(plat_docs) >= 1, "No plat document found"
        
        plat = plat_docs[0]
        assert plat["recording_ref"] == "00065-00138", f"Plat recording_ref is {plat['recording_ref']}"
    
    def test_deed_with_grantee(self, auth_headers):
        """Verify deed document has grantee name."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/documents",
            headers=auth_headers,
        )
        assert response.status_code == 200
        docs = response.json()
        
        deed_docs = [d for d in docs if d["doc_type"] == "deed"]
        assert len(deed_docs) >= 1, "No deed document found"
        
        # Find the Special Warranty deed
        sw_deed = None
        for d in deed_docs:
            if d.get("doc_metadata", {}).get("deed_type_detail", "").startswith("SW"):
                sw_deed = d
                break
        
        assert sw_deed is not None, "Special Warranty deed not found"
        assert sw_deed["grantee"] is not None, "Grantee is None"
        assert "PITTS DERRICK R" in sw_deed["grantee"]["names"], "PITTS DERRICK R not in grantee names"
        assert sw_deed["consideration"] == 259000.0, f"Consideration is {sw_deed['consideration']}"
    
    def test_tax_assessment_record(self, auth_headers):
        """Verify tax assessment record has correct data."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/documents",
            headers=auth_headers,
        )
        assert response.status_code == 200
        docs = response.json()
        
        tax_docs = [d for d in docs if d.get("summary") == "Tax Assessment Record"]
        assert len(tax_docs) >= 1, "Tax Assessment Record not found"
        
        tax_doc = tax_docs[0]
        tax_info = tax_doc.get("doc_metadata", {}).get("tax_info", {})
        
        assert tax_info.get("tax_year") == "2025", f"Tax year is {tax_info.get('tax_year')}"
        assert tax_info.get("assessment_year") == "2025", f"Assessment year is {tax_info.get('assessment_year')}"
        assert tax_info.get("tax_status") == "Paid", f"Tax status is {tax_info.get('tax_status')}"
        assert tax_info.get("total_value") == 391818.0, f"Total value is {tax_info.get('total_value')}"


class TestOrderDetail:
    """Test order detail endpoint."""
    
    def test_order_detail(self, auth_headers):
        """Verify order detail returns correct data."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200, f"Order detail failed: {response.text}"
        order = response.json()
        
        assert order["property_address"] == "4471 Sherman Hills Pkwy"
        assert order["county"] == "Duval"
        assert order["state_code"] == "FL"
        assert order["search_scope"] == "full"
    
    def test_pipeline_status(self, auth_headers):
        """Verify pipeline is complete."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/pipeline",
            headers=auth_headers,
        )
        assert response.status_code == 200, f"Pipeline status failed: {response.text}"
        pipeline = response.json()
        
        # All stages should be completed
        for stage in pipeline["stages"]:
            assert stage["status"] == "completed", f"Stage {stage['stage']} is {stage['status']}"


class TestPDFDownload:
    """Test PDF download functionality."""
    
    def test_pdf_download(self, auth_headers):
        """Verify PDF download works."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200, f"PDF download failed: {response.text}"
        assert response.headers.get("content-type") == "application/pdf"
        assert len(response.content) > 10000, "PDF is too small"
    
    def test_pdf_is_valid(self, auth_headers):
        """Verify downloaded PDF is valid."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        # Save and verify PDF
        pdf_path = "/tmp/test_pdf_valid.pdf"
        with open(pdf_path, "wb") as f:
            f.write(response.content)
        
        doc = fitz.open(pdf_path)
        assert doc.page_count >= 1, "PDF has no pages"
        doc.close()
