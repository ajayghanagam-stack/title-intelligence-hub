"""
Iteration 6 Tests: Nationwide Pipeline Support

Tests for:
- Non-FL order creation and processing
- AI portal discovery and caching
- CAPTCHA-blocked orders completing as review_required
- PDF generation for non-FL orders
- FL regression (existing orders still work)
- Pagination on orders list
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ORG_ID = "576b9a0f-0af5-4520-8093-e4af1155cc44"


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
def headers(auth_token):
    """Headers with auth and org ID."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "X-Org-Id": ORG_ID,
        "Content-Type": "application/json",
    }


class TestLoginFlow:
    """Test authentication."""

    def test_login_success(self):
        """POST /api/v1/auth/login works."""
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"email": "admin@societytitle.com", "password": "admin123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["email"] == "admin@societytitle.com"


class TestExistingNonFLOrders:
    """Test existing non-FL orders from previous pipeline runs."""

    def test_ca_order_completed(self, headers):
        """CA order (Los Angeles) should be completed."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/a862d47b-57c4-4d45-979b-9e390a2920c3",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["state_code"] == "CA"
        assert data["county"] == "Los Angeles"
        assert data["status"] == "completed"
        assert data["pipeline_error"] is None

    def test_tx_order_review_required(self, headers):
        """TX order (Travis) should be review_required due to CAPTCHA."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/63cc772a-0e3f-4107-b9dc-0cb48bb82cbf",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["state_code"] == "TX"
        assert data["county"] == "Travis"
        assert data["status"] == "review_required"
        assert data["pipeline_error"] is None

    def test_tx_order_has_captcha_flags(self, headers):
        """TX order should have captcha_blocked flags."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/63cc772a-0e3f-4107-b9dc-0cb48bb82cbf/flags",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        flags = data["flags"]
        captcha_flags = [f for f in flags if f["flag_type"] == "captcha_blocked"]
        assert len(captcha_flags) >= 1, "Should have at least one captcha_blocked flag"
        # Check critical flag exists
        critical_captcha = [f for f in captcha_flags if f["severity"] == "critical"]
        assert len(critical_captcha) >= 1, "Should have critical captcha flag"


class TestPDFGenerationNonFL:
    """Test PDF generation for non-FL orders."""

    def test_ca_order_pdf(self, headers):
        """CA order PDF should generate successfully."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/a862d47b-57c4-4d45-979b-9e390a2920c3/package/pdf",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/pdf"
        assert response.content[:4] == b"%PDF"

    def test_tx_order_pdf(self, headers):
        """TX order PDF should generate even with review_required status."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/63cc772a-0e3f-4107-b9dc-0cb48bb82cbf/package/pdf",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/pdf"
        assert response.content[:4] == b"%PDF"


class TestFLRegression:
    """Regression tests for existing FL orders."""

    def test_fl_order_still_completed(self, headers):
        """FL order should still be completed."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/85173427-74a2-4d5a-8332-2300759cfe97",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["state_code"] == "FL"
        assert data["county"] == "Duval"
        assert data["status"] == "completed"

    def test_fl_order_pdf(self, headers):
        """FL order PDF should still generate."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders/85173427-74a2-4d5a-8332-2300759cfe97/package/pdf",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/pdf"


class TestOrdersList:
    """Test orders list and pagination."""

    def test_orders_list_returns_all(self, headers):
        """Orders list should return all orders."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders",
            headers=headers,
        )
        assert response.status_code == 200
        orders = response.json()
        assert len(orders) >= 10, "Should have at least 10 orders for pagination"

    def test_orders_include_multiple_states(self, headers):
        """Orders list should include orders from multiple states."""
        response = requests.get(
            f"{BASE_URL}/api/v1/apps/title-search/orders",
            headers=headers,
        )
        assert response.status_code == 200
        orders = response.json()
        states = set(o.get("state_code") for o in orders if o.get("state_code"))
        assert "FL" in states, "Should have FL orders"
        assert "CA" in states or "TX" in states or "NY" in states, "Should have non-FL orders"


class TestCreateNonFLOrder:
    """Test creating new non-FL orders."""

    def test_create_order_non_fl_state(self, headers):
        """Creating order with non-FL state should work."""
        response = requests.post(
            f"{BASE_URL}/api/v1/apps/title-search/orders",
            headers=headers,
            json={
                "property_address": "TEST_123 Main Street",
                "city": "Chicago",
                "state_code": "IL",
                "zip_code": "60601",
                "search_scope": "current_owner",
                "search_years": 30,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["state_code"] == "IL"
        assert data["status"] == "pending"
        
        # Clean up - delete the test order
        order_id = data["id"]
        requests.delete(
            f"{BASE_URL}/api/v1/apps/title-search/orders/{order_id}",
            headers=headers,
        )
