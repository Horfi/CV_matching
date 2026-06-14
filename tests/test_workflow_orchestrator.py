import sys
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Insert lightweight mocks for native/optional libraries
sys.modules.setdefault("psycopg", MagicMock())
sys.modules.setdefault("psycopg_pool", MagicMock())
sys.modules.setdefault("langgraph", MagicMock())
sys.modules.setdefault("langgraph.checkpoint", MagicMock())
sys.modules.setdefault("langgraph.checkpoint.postgres", MagicMock())
sys.modules.setdefault("langgraph.checkpoint.postgres.aio", MagicMock())
sys.modules.setdefault("langgraph.graph", MagicMock())

# Load workflow-orchestrator/main.py as module
engine_path = Path("workflow-orchestrator").resolve()
sys.path.insert(0, str(engine_path))
spec = importlib.util.spec_from_file_location("orchestration_main", engine_path / "main.py")
orchestrator = importlib.util.module_from_spec(spec)
sys.modules["orchestration_main"] = orchestrator
spec.loader.exec_module(orchestrator)

app = orchestrator.app

client = TestClient(app)


def test_trigger_workflow():
    payload = {"user": "user1"}
    response = client.post("/api/v1/trigger", json=payload)
    assert response.status_code == 200
    assert "thread_id" in response.json()


def test_resume_workflow():
    payload = {"thread_id": "test_123"}
    response = client.post("/webhook/resume", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "resumed"}


@patch("orchestration_main.AsyncConnectionPool")
@patch("orchestration_main.AsyncPostgresSaver")
@patch("orchestration_main.compile_graph")
def test_app_startup_shutdown(mock_compile_graph, mock_postgres_saver, mock_connection_pool):
    async def mock_setup(*args, **kwargs):
        pass
    async def mock_close(*args, **kwargs):
        pass

    mock_postgres_saver.return_value.setup = mock_setup
    mock_connection_pool.return_value.close = mock_close

    with TestClient(app):
        pass

    mock_connection_pool.assert_called()
    mock_postgres_saver.assert_called()
    mock_compile_graph.assert_called()


def test_upload_cv():
    async def mock_ainvoke(*args, **kwargs):
        return None
    orchestrator.app_graph = MagicMock()
    orchestrator.app_graph.ainvoke = mock_ainvoke

    files = {"file": ("resume.pdf", b"pdf content", "application/pdf")}
    response = client.post("/api/v1/upload-cv", files=files)
    assert response.status_code == 200
    assert "thread_id" in response.json()


def test_get_status():
    mock_state = MagicMock()
    mock_state.values = {"status": "review_pending", "user_id": "user123"}

    async def mock_aget_state(*args, **kwargs):
        return mock_state

    orchestrator.app_graph = MagicMock()
    orchestrator.app_graph.aget_state = mock_aget_state

    response = client.get("/api/v1/status/test_thread")
    assert response.status_code == 200
    assert response.json() == {"status": "review_pending", "user_id": "user123"}

