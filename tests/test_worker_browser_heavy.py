import sys
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

# Prevent heavy native libs from breaking imports
sys.modules.setdefault("psycopg", MagicMock())
sys.modules.setdefault("psycopg_pool", MagicMock())

# Load the tasks_browser module by file path
spec = importlib.util.spec_from_file_location("tasks_browser", Path("worker-browser-heavy") / "tasks_browser.py")
tb = importlib.util.module_from_spec(spec)
sys.modules["tasks_browser"] = tb
spec.loader.exec_module(tb)
execute_job_application = tb.execute_job_application


@patch("tasks_browser.httpx")
@patch("tasks_browser.sync_playwright")
def test_execute_job_application(mock_sync_playwright, mock_httpx):
    # Setup Playwright mocks
    mock_playwright_instance = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_sync_playwright.return_value.__enter__.return_value = mock_playwright_instance
    mock_playwright_instance.chromium.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    # Run the task
    result = execute_job_application("http://example.com/job", {"name": "Test User"}, "test_thread_123")

    # Assertions
    assert result == "Application Paused for HITL"

    # Verify Playwright flow
    mock_playwright_instance.chromium.launch.assert_called_once_with(headless=True)
    mock_browser.new_context.assert_called_once()
    mock_context.new_page.assert_called_once()
    mock_context.close.assert_called_once()
    mock_browser.close.assert_called_once()

    # Verify webhook hit
    mock_httpx.post.assert_called_once()
    args, kwargs = mock_httpx.post.call_args
    assert kwargs["json"]["thread_id"] == "test_thread_123"
    assert kwargs["json"]["status"] == "awaiting_approval"
