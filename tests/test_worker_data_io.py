import sys
import base64
import hashlib
import json
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# NOTE ON TEST SCOPE
# These are backend UNIT tests for worker-data-io/tasks_api.py only.
# They do NOT cover the Next.js frontend (drag-and-drop, file picker, fetch
# calls to the BFF gateway). UI interaction tests would need a browser
# automation tool like Playwright/Cypress pointed at localhost:3000.
# ---------------------------------------------------------------------------

# Mock ALL heavy native libs before loading the module under test
psycopg_mock = MagicMock()
sys.modules.setdefault("psycopg", psycopg_mock)
sys.modules.setdefault("psycopg_pool", MagicMock())
sys.modules.setdefault("qdrant_client", MagicMock())
sys.modules.setdefault("qdrant_client.models", MagicMock())
sys.modules.setdefault("google", MagicMock())
sys.modules.setdefault("google.generativeai", MagicMock())

# Insert worker-data-io to sys.path so its internal imports work
data_io_path = Path("worker-data-io").resolve()
sys.path.insert(0, str(data_io_path))

# Clear cached config module to avoid name collision with worker-scraper
if "config" in sys.modules:
    del sys.modules["config"]

# Load worker-data-io/tasks_api.py as module (with no GEMINI_API_KEY so mocks kick in)
spec = importlib.util.spec_from_file_location(
    "tasks_api", data_io_path / "tasks_api.py"
)
tasks_module = importlib.util.module_from_spec(spec)
sys.modules["tasks_api"] = tasks_module
spec.loader.exec_module(tasks_module)

# Also import the modules from worker-data-io for testing/patching
import db_ops
import gemini_ops
import qdrant_ops

parse_cv_with_gemini = tasks_module.parse_cv_with_gemini
generate_vector_embeddings = tasks_module.generate_vector_embeddings
_hash_content = tasks_module._hash_content
_ensure_cache_tables = db_ops.ensure_db_schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 1. Existing smoke tests (no GEMINI_API_KEY → mock data returned) - REMOVED
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2. _hash_content helper
# ---------------------------------------------------------------------------

def test_hash_content_deterministic():
    """Same input always produces the same SHA-256 hex digest."""
    h1 = _hash_content("hello world")
    h2 = _hash_content("hello world")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 → 64 hex chars


def test_hash_content_unique():
    """Different inputs produce different digests."""
    assert _hash_content("cv_a") != _hash_content("cv_b")


# ---------------------------------------------------------------------------
# 3. Cache helpers with psycopg mocked
# ---------------------------------------------------------------------------

def _make_conn_ctx(fetchone_return=None):
    """Build a fake psycopg connection context manager returning fetchone_return."""
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_return
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


def test_get_cached_parse_miss(monkeypatch):
    """Cache miss: fetchone returns None → helper returns None."""
    conn, _ = _make_conn_ctx(fetchone_return=None)
    monkeypatch.setattr(db_ops.psycopg, "connect", lambda *a, **kw: conn)
    result = db_ops.get_cached_parse("deadbeef" * 8)
    assert result is None


def test_get_cached_parse_hit(monkeypatch):
    """Cache hit: fetchone returns a row → helper returns the parsed dict."""
    cached_data = {"name": "Alice", "skills": ["Python"], "contact_info": "", "experience": ""}
    conn, _ = _make_conn_ctx(fetchone_return=(cached_data,))
    monkeypatch.setattr(db_ops.psycopg, "connect", lambda *a, **kw: conn)
    result = db_ops.get_cached_parse("deadbeef" * 8)
    assert result == cached_data


def test_store_cached_parse_executes_insert(monkeypatch):
    """_store_cached_parse issues an INSERT … ON CONFLICT DO NOTHING."""
    conn, cur = _make_conn_ctx()
    monkeypatch.setattr(db_ops.psycopg, "connect", lambda *a, **kw: conn)
    file_hash = "a" * 64
    parsed = {"name": "Bob", "skills": [], "contact_info": "", "experience": ""}
    db_ops.store_cached_parse(file_hash, parsed)
    assert cur.execute.called
    sql_arg = cur.execute.call_args[0][0]
    assert "INSERT INTO cv_parse_cache" in sql_arg
    assert "ON CONFLICT" in sql_arg


def test_get_cached_embedding_miss(monkeypatch):
    conn, _ = _make_conn_ctx(fetchone_return=None)
    monkeypatch.setattr(db_ops.psycopg, "connect", lambda *a, **kw: conn)
    assert db_ops.get_cached_embedding("z" * 64) is None


def test_get_cached_embedding_hit(monkeypatch):
    vector = [0.1, 0.2, 0.3]
    conn, _ = _make_conn_ctx(fetchone_return=(vector,))
    monkeypatch.setattr(db_ops.psycopg, "connect", lambda *a, **kw: conn)
    assert db_ops.get_cached_embedding("z" * 64) == vector


def test_store_cached_embedding_executes_insert(monkeypatch):
    conn, cur = _make_conn_ctx()
    monkeypatch.setattr(db_ops.psycopg, "connect", lambda *a, **kw: conn)
    db_ops.store_cached_embedding("b" * 64, [0.9, 0.8])
    sql_arg = cur.execute.call_args[0][0]
    assert "INSERT INTO cv_embedding_cache" in sql_arg
    assert "ON CONFLICT" in sql_arg


# ---------------------------------------------------------------------------
# 4. _ensure_cache_tables idempotency
# ---------------------------------------------------------------------------

def test_ensure_cache_tables_called_onlyonce(monkeypatch):
    """_ensure_cache_tables must create tables only once per process lifetime."""
    conn, cur = _make_conn_ctx()
    monkeypatch.setattr(db_ops.psycopg, "connect", lambda *a, **kw: conn)
    # Reset the guard flag so we can test the first-run path
    db_ops._db_initialized = False
    _ensure_cache_tables()
    first_call_count = cur.execute.call_count
    assert first_call_count >= 2  # at least CREATE TABLE for parse + embedding

    # Second call must be a no-op (guard is now True)
    cur.execute.reset_mock()
    _ensure_cache_tables()
    assert cur.execute.call_count == 0  # no DB calls on second invocation


# ---------------------------------------------------------------------------
# 5. End-to-end parse: cache MISS then HIT (with GEMINI_API_KEY patched in)
# ---------------------------------------------------------------------------

def test_parse_cv_cache_miss_then_hit(monkeypatch):
    """
    First call with a real-looking API key should:
      1. query the cache → miss
      2. call Gemini
      3. store result
    Second call with the same file should:
      1. query the cache → hit
      2. NOT call Gemini
    """
    structured = {"name": "Eve", "contact_info": "eve@example.com",
                  "skills": ["Go"], "experience": "SRE at BigCo"}

    # Patch GEMINI_API_KEY so the task doesn't short-circuit to mock data
    monkeypatch.setattr(gemini_ops, "GEMINI_API_KEY", "fake-key")

    # Patch ensure_db_schema to be a no-op
    monkeypatch.setattr(db_ops, "ensure_db_schema", lambda: None)

    gemini_call_count = {"n": 0}

    def fake_get_parse(file_hash):
        """Miss on first call, hit on second."""
        return None if gemini_call_count["n"] == 0 else structured

    def fake_store_parse(file_hash, data):
        pass

    def fake_parse_cv_text(file_bytes, mime_type):
        gemini_call_count["n"] += 1
        return structured

    monkeypatch.setattr(db_ops, "get_cached_parse", fake_get_parse)
    monkeypatch.setattr(db_ops, "store_cached_parse", fake_store_parse)
    monkeypatch.setattr(gemini_ops, "parse_cv_text_with_gemini", fake_parse_cv_text)

    file_b64 = _b64("some cv content")

    # First call — cache MISS, Gemini called once
    r1 = parse_cv_with_gemini(file_b64, "text/plain", "cv.txt")
    assert r1["status"] == "success"
    assert gemini_call_count["n"] == 1

    # Second call — cache HIT, Gemini NOT called again
    r2 = parse_cv_with_gemini(file_b64, "text/plain", "cv.txt")
    assert r2["status"] == "success"
    assert r2["structured_data"] == structured
    assert gemini_call_count["n"] == 1  # still 1, not 2


# ---------------------------------------------------------------------------
# 6. End-to-end embeddings: cache MISS then HIT
# ---------------------------------------------------------------------------

def test_embedding_cache_miss_then_hit(monkeypatch):
    """Same CV text should hit the embedding cache on the second call."""
    monkeypatch.setattr(gemini_ops, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(db_ops, "ensure_db_schema", lambda: None)

    vector = [0.1, 0.2, 0.3]
    embed_call_count = {"n": 0}

    def fake_get_embedding(text_hash):
        return None if embed_call_count["n"] == 0 else vector

    def fake_store_embedding(text_hash, emb):
        pass

    def fake_get_vector_embedding(text, task_type):
        embed_call_count["n"] += 1
        return vector

    # Qdrant mock similar jobs
    point = MagicMock()
    point.id = 1
    point.score = 0.9
    monkeypatch.setattr(qdrant_ops, "query_similar_jobs", lambda vector, limit, source_ids=None: [point])

    # psycopg mock for jobs fetch
    conn, cur = _make_conn_ctx()
    cur.fetchall.return_value = [(1, "Dev", "Acme", "Build stuff", "http://job", "Python")]

    monkeypatch.setattr(db_ops, "get_cached_embedding", fake_get_embedding)
    monkeypatch.setattr(db_ops, "store_cached_embedding", fake_store_embedding)
    monkeypatch.setattr(gemini_ops, "get_vector_embedding", fake_get_vector_embedding)
    monkeypatch.setattr(db_ops.psycopg, "connect", lambda *a, **kw: conn)

    cv_data = {"name": "Eve", "skills": ["Python"], "experience": "SRE"}

    # First call — embedding MISS
    r1 = generate_vector_embeddings(cv_data)
    assert r1["status"] == "success"
    assert embed_call_count["n"] == 1

    # Second call — embedding HIT
    r2 = generate_vector_embeddings(cv_data)
    assert r2["status"] == "success"
    assert embed_call_count["n"] == 1  # not called again


# ---------------------------------------------------------------------------
# 7. Structured Data Sanitization Tests
# ---------------------------------------------------------------------------

def test_parse_cv_sanitization_nested_dictionaries(monkeypatch):
    """
    Ensure that when Gemini returns nested dictionaries or lists for fields like
    experience, contact_info, and skills (which expect flat string/lists),
    the worker sanitizes them to valid flat strings and lists.
    """
    monkeypatch.setattr(gemini_ops, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(db_ops, "ensure_db_schema", lambda: None)

    # Gemini returns nested dictionaries and lists instead of flat strings
    gemini_nested_output = {
        "name": "John Doe",
        "contact_info": {
            "email": "john.doe@example.com",
            "phone": "123-456-7890",
            "linkedin": "linkedin.com/in/johndoe"
        },
        "skills": "Python, Go, Kubernetes, Terraform",
        "experience": {
            "summary": "Experienced DevOps Engineer",
            "jobs": [
                {"role": "SRE", "company": "TechCorp", "years": "2"},
                {"role": "DevOps", "company": "SystemsInc", "years": "3"}
            ],
            "education": {
                "degree": "B.S. Computer Science",
                "school": "University"
            }
        }
    }

    monkeypatch.setattr(db_ops, "get_cached_parse", lambda file_hash: None)
    monkeypatch.setattr(db_ops, "store_cached_parse", lambda file_hash, data: None)
    monkeypatch.setattr(gemini_ops, "parse_cv_text_with_gemini", lambda file_bytes, mime: gemini_nested_output)

    result = parse_cv_with_gemini(_b64("dummy content"), "image/jpeg", "example_cv.jpg")
    assert result["status"] == "success"
    data = result["structured_data"]

    # Verify contact_info got flattened to a string
    assert isinstance(data["contact_info"], str)
    assert "john.doe@example.com" in data["contact_info"]
    assert "123-456-7890" in data["contact_info"]

    # Verify skills got parsed into a list of strings
    assert isinstance(data["skills"], list)
    assert data["skills"] == ["Python", "Go", "Kubernetes", "Terraform"]

    # Verify experience got flattened to a clean string representation
    assert isinstance(data["experience"], str)
    assert "summary: Experienced DevOps Engineer" in data["experience"]
    assert "TechCorp" in data["experience"]
    assert "SystemsInc" in data["experience"]
    assert "B.S. Computer Science" in data["experience"]


@patch("tasks_api.gemini_ops.parse_job_listing_programmatically")
@patch("tasks_api.sync_listing_jobs")
def test_parse_and_sync_listing_success(mock_sync, mock_parse_gemini):
    mock_parse_gemini.return_value = {
        "jobs": [
            {"title": "Job 1", "url": "http://example.com/job1"},
            {"title": "Job 2", "url": "http://example.com/job2"}
        ]
    }
    
    result = tasks_module.parse_and_sync_listing(123, "# Job Listing\n- [Job 1](/job1)", "http://example.com")
    
    assert "Successfully parsed listing" in result
    mock_parse_gemini.assert_called_once_with("# Job Listing\n- [Job 1](/job1)", "http://example.com")
    mock_sync.assert_called_once_with(123, [
        {"title": "Job 1", "url": "http://example.com/job1"},
        {"title": "Job 2", "url": "http://example.com/job2"}
    ])


@patch("tasks_api.gemini_ops.parse_job_detail_programmatically")
@patch("tasks_api.save_job_detail")
def test_parse_and_save_job_detail_success(mock_save, mock_parse_gemini):
    job_details = {
        "title": "Software Engineer",
        "company": "Google",
        "description": "Coding in Python",
        "skills": ["Python", "FastAPI"]
    }
    mock_parse_gemini.return_value = job_details
    
    result = tasks_module.parse_and_save_job_detail(123, "http://example.com/job1", "# Job Details")
    
    assert "Successfully parsed and saved job detail" in result
    mock_parse_gemini.assert_called_once_with("# Job Details", job_url="http://example.com/job1")
    mock_save.assert_called_once_with(123, "http://example.com/job1", job_details)


@patch("tasks_api.gemini_ops.parse_job_detail_programmatically")
@patch("tasks_api.db_ops.delete_jobs")
@patch("tasks_api.qdrant_ops.delete_qdrant_points")
@patch("tasks_api.db_ops.update_source_status")
@patch("tasks_api.psycopg.connect")
def test_parse_and_save_job_detail_invalid_taken_down(mock_connect, mock_update_status, mock_delete_qdrant, mock_delete_jobs, mock_parse_gemini):
    # Mock invalid job details page (taken down)
    markdown_content = "# job details\nJob not found. This job may have been taken down."
    job_details = {
        "title": "job details",
        "company": "Google",
        "description": "Job not found. This job may have been taken down.",
        "skills": []
    }
    mock_parse_gemini.return_value = job_details

    # Mock psycopg connect to find a job ID
    cur = MagicMock()
    cur.fetchone.return_value = (999,)  # job_id is 999
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_connect.return_value = conn

    # Calling the task should raise ValueError
    try:
        tasks_module.parse_and_save_job_detail(123, "http://example.com/job1", markdown_content)
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "taken down or is invalid" in str(exc)

    # Verify existing job was fetched and deleted
    cur.execute.assert_called_with("SELECT id FROM jobs WHERE url = %s", ("http://example.com/job1",))
    mock_delete_jobs.assert_called_once_with([999])
    mock_delete_qdrant.assert_called_once_with([999])
    
    # Verify status was updated to failed
    mock_update_status.assert_called_once_with(123, 'failed')


# --- New Tests for Source Filtering & Blank CV Match Anomaly Prevention ---

@patch("tasks_api.gemini_ops.get_vector_embedding")
@patch("tasks_api.qdrant_ops.query_similar_jobs")
def test_generate_vector_embeddings_blank_cv(mock_query, mock_embed):
    """Blank/empty CV should bypass similarity search and return zero matches immediately."""
    blank_cv = {
        "skills": [],
        "experience": ""
    }
    result = generate_vector_embeddings(blank_cv)
    assert result == {"status": "success", "matches": []}
    mock_embed.assert_not_called()
    mock_query.assert_not_called()

    # Even with spaces/newlines/None
    blank_cv_whitespace = {
        "skills": ["  ", "\n"],
        "experience": " \n\t "
    }
    result_ws = generate_vector_embeddings(blank_cv_whitespace)
    assert result_ws == {"status": "success", "matches": []}


@patch("tasks_api.psycopg.connect")
@patch("tasks_api.db_ops.get_cached_embedding")
@patch("tasks_api.qdrant_ops.query_similar_jobs")
@patch("tasks_api.gemini_ops.get_vector_embedding")
def test_generate_vector_embeddings_source_filtering(mock_embed, mock_query, mock_get_cached, mock_connect):
    """Source filtering must be propagated to Qdrant query filter and DB fetch query."""
    mock_get_cached.return_value = None
    mock_embed.return_value = [0.1] * 768
    
    # Mock Qdrant return value
    mock_hit = MagicMock()
    mock_hit.id = 42
    mock_hit.score = 0.75
    mock_query.return_value = [mock_hit]
    
    # Mock Postgres return row
    cur = MagicMock()
    cur.fetchall.return_value = [
        (42, "Nvidia Developer", "Nvidia", "Description", "http://nvidia.com", "Python, CUDA")
    ]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_connect.return_value = conn
    
    cv_data = {
        "skills": ["Python"],
        "experience": "Developer"
    }
    
    # Call with source filter [101]
    result = generate_vector_embeddings(cv_data, source_ids=[101])
    
    # Verify Qdrant filter was called with source_ids
    mock_query.assert_called_once_with(mock_embed.return_value, limit=5, source_ids=[101])
    
    # Verify DB query was filtered by both matched IDs and source_ids
    assert cur.execute.called
    sql_args = cur.execute.call_args[0]
    sql_query = sql_args[0]
    params = sql_args[1]
    assert "AND source_id = ANY(%s)" in sql_query
    assert params == ([42], [101])


@patch("tasks_api.psycopg.connect")
@patch("tasks_api.db_ops.get_cached_embedding")
@patch("tasks_api.qdrant_ops.query_similar_jobs")
@patch("tasks_api.gemini_ops.get_vector_embedding")
def test_generate_vector_embeddings_statistical_guard(mock_embed, mock_query, mock_get_cached, mock_connect):
    """Cosine similarity scores below threshold must scale to exactly 0.0 (preventing default match scores)."""
    mock_get_cached.return_value = None
    mock_embed.return_value = [0.1] * 768
    
    # Mock Qdrant returning low scores below 0.60 (e.g., 0.50, 0.58)
    mock_hit_1 = MagicMock()
    mock_hit_1.id = 10
    mock_hit_1.score = 0.58
    
    mock_hit_2 = MagicMock()
    mock_hit_2.id = 11
    mock_hit_2.score = 0.50
    
    mock_query.return_value = [mock_hit_1, mock_hit_2]
    
    cur = MagicMock()
    cur.fetchall.return_value = [
        (10, "Job A", "Company A", "Desc A", "http://a.com", "Skill A"),
        (11, "Job B", "Company B", "Desc B", "http://b.com", "Skill B")
    ]
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_connect.return_value = conn
    
    cv_data = {
        "skills": ["RandomSkill"],
        "experience": "RandomExperience"
    }
    
    result = generate_vector_embeddings(cv_data)
    
    matches = result["matches"]
    # Both matches should have rescaled scores of exactly 0.0, because similarity is < 0.60
    assert len(matches) == 2
    assert matches[0]["score"] == 0.0
    assert matches[1]["score"] == 0.0



