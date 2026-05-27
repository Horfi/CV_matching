import sys
import importlib.util
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Ensure heavy native libs are mocked so importing service code doesn't fail
sys.modules.setdefault("psycopg", MagicMock())
sys.modules.setdefault("psycopg_pool", MagicMock())

# Load bff-gateway/main.py as a module
spec = importlib.util.spec_from_file_location("bff_gateway_main", Path("bff-gateway") / "main.py")
module = importlib.util.module_from_spec(spec)
sys.modules["bff_gateway_main"] = module
spec.loader.exec_module(module)

app = module.app
client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "BFF Gateway is running"}


@patch("bff_gateway_main.httpx.AsyncClient.post")
def test_trigger_workflow_api(mock_post):
    # Create a mock response object that AsyncClient.post would return
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"status": "started", "thread_id": "test-123"}
    mock_post.return_value = mock_response

    payload = {"user_id": "user_1", "cv_text": "Sample CV"}
    response = client.post("/api/v1/trigger", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "started", "thread_id": "test-123"}
    mock_post.assert_called()


@patch("bff_gateway_main.httpx.AsyncClient.post")
def test_resume_workflow_api(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"status": "resumed"}
    mock_post.return_value = mock_response

    payload = {"thread_id": "test-123"}
    response = client.post("/api/v1/resume", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "resumed"}
    mock_post.assert_called()


@patch("bff_gateway_main.httpx.AsyncClient.post")
def test_upload_cv_api(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"status": "started", "thread_id": "test-123"}
    mock_post.return_value = mock_response

    files = {"file": ("resume.pdf", b"pdf content", "application/pdf")}
    response = client.post("/api/v1/upload-cv", files=files)

    assert response.status_code == 200
    assert response.json() == {"status": "started", "thread_id": "test-123"}
    mock_post.assert_called()
