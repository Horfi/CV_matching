import sys
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

# Mock celery before import to avoid connection attempts and decorate nicely
class MockCelery:
    def __init__(self, *args, **kwargs):
        self.send_task = MagicMock()
    def task(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator

celery_module_mock = MagicMock()
celery_module_mock.Celery = MockCelery
sys.modules["celery"] = celery_module_mock

# Add worker-scraper directory to sys.path so its internal imports work
scraper_path = Path("worker-scraper").resolve()
sys.path.insert(0, str(scraper_path))

# Clear cached config module to avoid name collision with worker-data-io
if "config" in sys.modules:
    del sys.modules["config"]

# Load tasks_scraper
spec = importlib.util.spec_from_file_location("tasks_scraper", scraper_path / "tasks_scraper.py")
tasks_scraper = importlib.util.module_from_spec(spec)
sys.modules["tasks_scraper"] = tasks_scraper
spec.loader.exec_module(tasks_scraper)

import celery_app
app_mock = celery_app.app


@patch("tasks_scraper.scrape_url_markdown")
def test_scrape_listing_success(mock_scrape):
    markdown_content = "# Career Page Listing\n- [Job 1](/job1)\n- [Job 2](/job2)"
    mock_scrape.return_value = markdown_content
    
    app_mock.send_task.reset_mock()
    
    result = tasks_scraper.scrape_listing(123, "http://example.com/careers")
    
    assert "Successfully crawled listing page" in result
    mock_scrape.assert_called_once_with("http://example.com/careers")
    
    app_mock.send_task.assert_called_once_with(
        'tasks_api.parse_and_sync_listing',
        args=[123, markdown_content, "http://example.com/careers"],
        queue='data_io'
    )


@patch("tasks_scraper.scrape_url_markdown")
def test_scrape_listing_failure(mock_scrape):
    mock_scrape.side_effect = Exception("Network error")
    
    app_mock.send_task.reset_mock()
    
    try:
        tasks_scraper.scrape_listing(123, "http://example.com/careers")
    except Exception as exc:
        assert "Network error" in str(exc)
        
    app_mock.send_task.assert_called_once_with(
        'tasks_api.update_source_status',
        args=[123, 'failed'],
        queue='data_io'
    )


@patch("tasks_scraper.scrape_url_markdown")
def test_scrape_detail_success(mock_scrape):
    markdown_detail = "# Software Engineer\nGoogle\nWrite code\nPython, Algorithms"
    mock_scrape.return_value = markdown_detail
    
    app_mock.send_task.reset_mock()
    
    result = tasks_scraper.scrape_detail(123, "http://example.com/job1")
    
    assert "Successfully crawled detail page" in result
    mock_scrape.assert_called_once_with("http://example.com/job1")
    
    app_mock.send_task.assert_called_once_with(
        'tasks_api.parse_and_save_job_detail',
        args=[123, "http://example.com/job1", markdown_detail],
        queue='data_io'
    )
