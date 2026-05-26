import sys
import importlib.util
from pathlib import Path

# Mock heavy native libs
from unittest.mock import MagicMock
sys.modules.setdefault("psycopg", MagicMock())
sys.modules.setdefault("psycopg_pool", MagicMock())

# Load worker-data-io/tasks_api.py as module
spec = importlib.util.spec_from_file_location("tasks_api", Path("worker-data-io") / "tasks_api.py")
tasks_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tasks_module)

parse_cv_with_gemini = tasks_module.parse_cv_with_gemini
generate_vector_embeddings = tasks_module.generate_vector_embeddings


def test_parse_cv_with_gemini():
    # Calling the Celery task directly as a regular python function
    cv_text = "Experienced software engineer"
    result = parse_cv_with_gemini(cv_text)

    assert result["status"] == "success"
    assert "structured_data" in result
    assert result["structured_data"]["experience"] == cv_text


def test_generate_vector_embeddings():
    cv_data = {"name": "Test User", "skills": ["Python"]}
    job_postings = [{"id": 1, "description": "Needs Python"}]

    result = generate_vector_embeddings(cv_data, job_postings)

    assert result["status"] == "success"
    assert "matches" in result
    assert isinstance(result["matches"], list)
    assert len(result["matches"]) > 0
