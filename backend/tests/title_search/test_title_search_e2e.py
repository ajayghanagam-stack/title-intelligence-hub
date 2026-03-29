"""
End-to-end tests for Title Search & Abstracting micro-app.
Tests order listing, order details, pipeline status, and PDF download.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("NEXT_PUBLIC_API_URL", "https://dc353579-ba3e-4338-b011-8fae44983f1e.preview.emergentagent.com")
ORG_ID = "576b9a0f-0af5-4520-8093-e4af1155cc44"
DUVAL_ORDER_ID = "5daff57e-5ab8-46c8-94f8-a5dbb3aae69a"
HENDRY_ORDER_ID = "dbd6a815-c66e-43e2-8c17-ceb5799d1bac"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for admin@societytitle.com"""
    response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"email": "admin@societytitle.com", "password": "admin123"}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    assert "access_token" in data, f"No access_token in response: {data}"
    return data["access_token"]


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Create authenticated session with org header"""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {auth_token}",
        "X-Org-Id": ORG_ID,
        "Content-Type": "application/json"
    })
    return session


class TestHealthCheck:
    """Basic health check tests"""
    
    def test_health_endpoint(self):
        """Test health endpoint is accessible"""
        response = requests.get(f"{BASE_URL}/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print(f"✓ Health check passed: {data}")


class TestAuthentication:
    """Authentication tests"""
    
    def test_login_success(self):
        """Test login with valid credentials"""
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"email": "admin@societytitle.com", "password": "admin123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        print(f"✓ Login successful, token received")
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"email": "wrong@example.com", "password": "wrongpass"}
        )
        assert response.status_code in [401, 404]
        print(f"✓ Invalid login correctly rejected with status {response.status_code}")


class TestTitleSearchOrders:
    """Title Search order endpoint tests"""
    
    def test_list_orders(self, api_client):
        """Test GET /api/v1/apps/title-search/orders returns list of orders"""
        response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders")
        assert response.status_code == 200, f"Failed to list orders: {response.text}"
        
        orders = response.json()
        assert isinstance(orders, list), "Response should be a list"
        print(f"✓ Listed {len(orders)} orders")
        
        # Verify order structure
        if orders:
            order = orders[0]
            assert "id" in order
            assert "property_address" in order
            assert "status" in order
            assert "county" in order
            print(f"✓ Order structure validated: {order.get('property_address')}")
    
    def test_list_orders_with_status_filter(self, api_client):
        """Test order filtering by status"""
        for status in ["pending", "processing", "review_required", "completed", "failed"]:
            response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders?status={status}")
            assert response.status_code == 200, f"Failed to filter by {status}: {response.text}"
            print(f"✓ Status filter '{status}' works")
    
    def test_get_duval_order(self, api_client):
        """Test GET /api/v1/apps/title-search/orders/{order_id} for Duval County order"""
        response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders/{DUVAL_ORDER_ID}")
        assert response.status_code == 200, f"Failed to get Duval order: {response.text}"
        
        order = response.json()
        assert order["id"] == DUVAL_ORDER_ID
        assert "property_address" in order
        assert "county" in order
        assert "parcel_number" in order
        assert "borrower_name" in order
        
        # Verify expected values for Duval order
        assert "Sherman Hills" in order.get("property_address", ""), f"Expected Sherman Hills address, got: {order.get('property_address')}"
        assert order.get("county") == "Duval", f"Expected Duval county, got: {order.get('county')}"
        
        print(f"✓ Duval order retrieved: {order.get('property_address')}")
        print(f"  - County: {order.get('county')}")
        print(f"  - Parcel: {order.get('parcel_number')}")
        print(f"  - Owner: {order.get('borrower_name')}")
        print(f"  - Status: {order.get('status')}")
    
    def test_get_hendry_order(self, api_client):
        """Test GET /api/v1/apps/title-search/orders/{order_id} for Hendry County order"""
        response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders/{HENDRY_ORDER_ID}")
        assert response.status_code == 200, f"Failed to get Hendry order: {response.text}"
        
        order = response.json()
        assert order["id"] == HENDRY_ORDER_ID
        print(f"✓ Hendry order retrieved: {order.get('property_address')}")
    
    def test_get_nonexistent_order(self, api_client):
        """Test GET for non-existent order returns 404"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders/{fake_id}")
        assert response.status_code == 404
        print(f"✓ Non-existent order correctly returns 404")


class TestPipelineStatus:
    """Pipeline status endpoint tests"""
    
    def test_get_pipeline_status_duval(self, api_client):
        """Test GET /api/v1/apps/title-search/orders/{order_id}/pipeline for Duval order"""
        response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders/{DUVAL_ORDER_ID}/pipeline")
        assert response.status_code == 200, f"Failed to get pipeline status: {response.text}"
        
        pipeline = response.json()
        assert "stages" in pipeline, f"No stages in pipeline response: {pipeline}"
        
        stages = pipeline["stages"]
        assert isinstance(stages, list)
        assert len(stages) > 0, "Pipeline should have stages"
        
        # Check stage structure
        for stage in stages:
            assert "stage" in stage
            assert "status" in stage
        
        # Count completed stages
        completed = sum(1 for s in stages if s["status"] == "completed")
        print(f"✓ Pipeline status retrieved: {completed}/{len(stages)} stages completed")
        
        # Verify all 6 stages are present
        stage_names = [s["stage"] for s in stages]
        expected_stages = ["order", "retrieve", "parse", "chain", "package", "complete"]
        for expected in expected_stages:
            assert expected in stage_names, f"Missing stage: {expected}"
        print(f"✓ All 6 pipeline stages present")


class TestDocuments:
    """Document endpoint tests"""
    
    def test_get_documents(self, api_client):
        """Test GET /api/v1/apps/title-search/orders/{order_id}/documents"""
        response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders/{DUVAL_ORDER_ID}/documents")
        assert response.status_code == 200, f"Failed to get documents: {response.text}"
        
        documents = response.json()
        assert isinstance(documents, list)
        print(f"✓ Retrieved {len(documents)} documents for Duval order")
        
        if documents:
            doc = documents[0]
            assert "id" in doc
            assert "doc_type" in doc
            print(f"  - First doc type: {doc.get('doc_type')}")


class TestChainOfTitle:
    """Chain of title endpoint tests"""
    
    def test_get_chain(self, api_client):
        """Test GET /api/v1/apps/title-search/orders/{order_id}/chain"""
        response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders/{DUVAL_ORDER_ID}/chain")
        assert response.status_code == 200, f"Failed to get chain: {response.text}"
        
        data = response.json()
        # Response is an object with chain_links array
        assert "chain_links" in data, f"No chain_links in response: {data}"
        chain_links = data["chain_links"]
        assert isinstance(chain_links, list)
        assert "chain_complete" in data
        print(f"✓ Retrieved {len(chain_links)} chain links for Duval order")
        print(f"  - Chain complete: {data.get('chain_complete')}")


class TestFlags:
    """Flag endpoint tests"""
    
    def test_get_flags(self, api_client):
        """Test GET /api/v1/apps/title-search/orders/{order_id}/flags"""
        response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders/{DUVAL_ORDER_ID}/flags")
        assert response.status_code == 200, f"Failed to get flags: {response.text}"
        
        data = response.json()
        # Response is an object with flags array and counts
        assert "flags" in data, f"No flags in response: {data}"
        flags = data["flags"]
        assert isinstance(flags, list)
        assert "counts" in data
        print(f"✓ Retrieved {len(flags)} flags for Duval order")
        print(f"  - Counts: {data.get('counts')}")


class TestPackage:
    """Package endpoint tests"""
    
    def test_get_package(self, api_client):
        """Test GET /api/v1/apps/title-search/orders/{order_id}/package"""
        response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders/{DUVAL_ORDER_ID}/package")
        assert response.status_code == 200, f"Failed to get package: {response.text}"
        
        package = response.json()
        assert "id" in package
        assert "package_number" in package
        assert "status" in package
        print(f"✓ Package retrieved: {package.get('package_number')}")
        print(f"  - Status: {package.get('status')}")
        print(f"  - Total documents: {package.get('total_documents')}")
    
    def test_download_pdf(self, api_client):
        """Test GET /api/v1/apps/title-search/orders/{order_id}/package/pdf returns PDF"""
        response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders/{DUVAL_ORDER_ID}/package/pdf")
        assert response.status_code == 200, f"Failed to download PDF: {response.text}"
        
        # Verify it's a PDF
        content_type = response.headers.get("Content-Type", "")
        assert "application/pdf" in content_type, f"Expected PDF, got: {content_type}"
        
        # Verify content disposition header
        content_disp = response.headers.get("Content-Disposition", "")
        assert "attachment" in content_disp, f"Expected attachment, got: {content_disp}"
        
        # Verify PDF content starts with PDF magic bytes
        content = response.content
        assert len(content) > 0, "PDF content is empty"
        assert content[:4] == b"%PDF", f"Content doesn't start with PDF header: {content[:20]}"
        
        print(f"✓ PDF downloaded successfully ({len(content)} bytes)")
        print(f"  - Content-Type: {content_type}")
        print(f"  - Content-Disposition: {content_disp}")
    
    def test_download_pdf_hendry(self, api_client):
        """Test PDF download for Hendry County order"""
        response = api_client.get(f"{BASE_URL}/api/v1/apps/title-search/orders/{HENDRY_ORDER_ID}/package/pdf")
        assert response.status_code == 200, f"Failed to download Hendry PDF: {response.text}"
        
        content = response.content
        assert content[:4] == b"%PDF", "Hendry PDF doesn't have valid header"
        print(f"✓ Hendry PDF downloaded successfully ({len(content)} bytes)")


class TestOrderCreation:
    """Order creation tests (read-only verification)"""
    
    def test_create_order_requires_auth(self):
        """Test that order creation requires authentication"""
        response = requests.post(
            f"{BASE_URL}/api/v1/apps/title-search/orders",
            json={
                "property_address": "123 Test St",
                "county": "Test",
                "state_code": "FL"
            }
        )
        assert response.status_code in [401, 403], f"Expected auth error, got: {response.status_code}"
        print(f"✓ Order creation correctly requires authentication")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
