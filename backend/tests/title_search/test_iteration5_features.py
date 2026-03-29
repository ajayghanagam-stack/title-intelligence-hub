"""
Test iteration 5 features:
1. Orders list pagination (10 per page, latest first)
2. PDF report - no vertical cell borders
3. PDF logo renders correctly (Logo_rev_no-tagline.svg converted to PNG)
"""
import pytest
import requests
import os
import tempfile
import pdfplumber

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = os.environ.get("NEXT_PUBLIC_API_URL", "").rstrip("/")

ORG_ID = "576b9a0f-0af5-4520-8093-e4af1155cc44"
TEST_ORDER_ID = "687ffd0c-4c45-4fd7-a8f2-b6f9dca935cc"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"email": "admin@societytitle.com", "password": "admin123"},
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token and org ID"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "X-Org-Id": ORG_ID,
        "Content-Type": "application/json",
    }


class TestAuthentication:
    """Test login endpoint"""

    def test_login_success(self):
        """Test login with valid credentials"""
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"email": "admin@societytitle.com", "password": "admin123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["email"] == "admin@societytitle.com"

    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"email": "wrong@example.com", "password": "wrongpass"},
        )
        assert response.status_code == 401


class TestOrdersList:
    """Test orders list endpoint and sorting"""

    def test_orders_list_returns_200(self, auth_headers):
        """Test orders list endpoint returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_orders_sorted_latest_first(self, auth_headers):
        """Test orders are sorted by created_at descending (latest first)"""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders",
            headers=auth_headers,
        )
        assert response.status_code == 200
        orders = response.json()
        
        if len(orders) >= 2:
            # Verify orders are sorted by created_at descending
            for i in range(len(orders) - 1):
                current_date = orders[i]["created_at"]
                next_date = orders[i + 1]["created_at"]
                assert current_date >= next_date, f"Orders not sorted: {current_date} should be >= {next_date}"

    def test_orders_have_required_fields(self, auth_headers):
        """Test orders have required fields for display"""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders",
            headers=auth_headers,
        )
        assert response.status_code == 200
        orders = response.json()
        
        if orders:
            order = orders[0]
            assert "id" in order
            assert "property_address" in order
            assert "created_at" in order
            assert "status" in order


class TestPDFGeneration:
    """Test PDF generation endpoint"""

    def test_pdf_endpoint_returns_200(self, auth_headers):
        """Test PDF endpoint returns 200 with application/pdf content type"""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200, f"PDF endpoint failed: {response.text}"
        assert "application/pdf" in response.headers.get("Content-Type", "")

    def test_pdf_no_vertical_borders(self, auth_headers):
        """Test PDF has no vertical cell borders (only horizontal separators)"""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        # Save PDF to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(response.content)
            pdf_path = f.name
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_vertical_lines = 0
                
                for page in pdf.pages:
                    lines = page.lines
                    # Vertical lines have x0 ≈ x1
                    vertical = [l for l in lines if abs(l['x0'] - l['x1']) < 1]
                    total_vertical_lines += len(vertical)
                
                assert total_vertical_lines == 0, f"Found {total_vertical_lines} vertical cell borders in PDF"
        finally:
            os.unlink(pdf_path)

    def test_pdf_has_horizontal_separators(self, auth_headers):
        """Test PDF has horizontal separators (for table headers)"""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(response.content)
            pdf_path = f.name
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_horizontal_lines = 0
                
                for page in pdf.pages:
                    lines = page.lines
                    # Horizontal lines have top ≈ bottom
                    horizontal = [l for l in lines if abs(l['top'] - l['bottom']) < 1]
                    total_horizontal_lines += len(horizontal)
                
                # Should have some horizontal lines for table headers
                assert total_horizontal_lines > 0, "PDF should have horizontal separators"
        finally:
            os.unlink(pdf_path)

    def test_pdf_has_logo(self, auth_headers):
        """Test PDF has logo image on first page"""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{TEST_ORDER_ID}/package/pdf",
            headers=auth_headers,
        )
        assert response.status_code == 200
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(response.content)
            pdf_path = f.name
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                first_page = pdf.pages[0]
                images = first_page.images
                assert len(images) >= 1, "PDF should have logo image on first page"
        finally:
            os.unlink(pdf_path)


class TestLogoFile:
    """Test logo file exists and is valid"""

    def test_logo_file_exists(self):
        """Test logo PNG file exists in backend services directory"""
        logo_path = "/app/backend/app/micro_apps/title_search/services/logikality_logo.png"
        assert os.path.exists(logo_path), f"Logo file not found at {logo_path}"

    def test_logo_file_is_png(self):
        """Test logo file is a valid PNG"""
        logo_path = "/app/backend/app/micro_apps/title_search/services/logikality_logo.png"
        with open(logo_path, "rb") as f:
            header = f.read(8)
        # PNG magic bytes
        png_signature = b'\x89PNG\r\n\x1a\n'
        assert header == png_signature, "Logo file is not a valid PNG"

    def test_logo_file_size_reasonable(self):
        """Test logo file size is reasonable (not empty, not too large)"""
        logo_path = "/app/backend/app/micro_apps/title_search/services/logikality_logo.png"
        size = os.path.getsize(logo_path)
        assert size > 1000, f"Logo file too small: {size} bytes"
        assert size < 1000000, f"Logo file too large: {size} bytes"


class TestCreateOrdersForPagination:
    """Create additional orders to test pagination (need >10 orders)"""

    def test_create_test_orders(self, auth_headers):
        """Create test orders to have >10 total for pagination testing"""
        # First check current count
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders",
            headers=auth_headers,
        )
        assert response.status_code == 200
        current_count = len(response.json())
        
        # Need at least 11 orders for pagination to show
        orders_needed = max(0, 11 - current_count)
        
        created_ids = []
        for i in range(orders_needed):
            order_data = {
                "property_address": f"TEST_{i+1} Pagination Test St",
                "city": "Jacksonville",
                "county": "Duval",
                "state_code": "FL",
                "zip_code": "32210",
                "search_scope": "current_owner",
            }
            response = requests.post(
                f"{BASE_URL}/api/v1/apps/title-search/orders",
                headers=auth_headers,
                json=order_data,
            )
            if response.status_code == 201:
                created_ids.append(response.json()["id"])
        
        # Verify we now have >10 orders
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders",
            headers=auth_headers,
        )
        assert response.status_code == 200
        final_count = len(response.json())
        
        print(f"Created {len(created_ids)} test orders. Total orders: {final_count}")
        assert final_count >= 11, f"Need at least 11 orders for pagination, have {final_count}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
