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
sys.modules.setdefault("langgraph.graph", MagicMock())

# Load orchestration-engine/main.py as module
engine_path = Path("orchestration-engine").resolve()
sys.path.insert(0, str(engine_path))
spec = importlib.util.spec_from_file_location("orchestration_main", engine_path / "main.py")
orchestrator = importlib.util.module_from_spec(spec)
sys.modules["orchestration_main"] = orchestrator
spec.loader.exec_module(orchestrator)

app = orchestrator.app
on_startup = orchestrator.on_startup
on_shutdown = orchestrator.on_shutdown

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


@patch("orchestration_main.ConnectionPool")
@patch("orchestration_main.PostgresSaver")
@patch("orchestration_main.compile_graph")
def test_app_startup_shutdown(mock_compile_graph, mock_postgres_saver, mock_connection_pool):
    on_startup()
    mock_connection_pool.assert_called()
    mock_postgres_saver.assert_called()
    mock_postgres_saver.return_value.setup.assert_called()
    mock_compile_graph.assert_called()

    on_shutdown()
    # Ensure the pool close was attempted if pool exists
    if mock_connection_pool.return_value:
        mock_connection_pool.return_value.close.assert_called()
