# Antigravity Agent Session Notes — CV Matching Project

> This file is for AI agent instances picking up this project. It summarises architecture decisions, bugs fixed, gotchas, and what's been verified end-to-end. Read this before touching anything.

---

## What This Project Does

A multi-container AI automation system that:
1. Accepts a CV (PDF/image/text) via a Next.js frontend
2. Parses it with Gemini 2.5 Flash into structured JSON
3. Embeds the CV text with `gemini-embedding-001` and finds matching jobs in Qdrant
4. Dispatches a Playwright browser-use worker to auto-fill job application forms
5. Pauses for human-in-the-loop (HITL) review before submitting
6. Resumes on approval and completes submission

---

## Architecture at a Glance

```
[Next.js :3000] → [BFF FastAPI :8000] → [Orchestrator LangGraph :8001]
                                              ↓                    ↑
                                        [Redis :6379]        [PostgreSQL :5432]
                                              ↓
                   ┌──────────────────────────┼─────────────────────────┐
          [worker-data-io]            [worker-scraper]          [worker-job-applier]
          queue: data_io              queue: scraper            queue: browser_heavy
          tasks_api.py                tasks_scraper.py          tasks_browser.py
               ↓                             ↓                          ↓
        [Qdrant :6333]                 [fastCRW :3002]       [Playwright → resume webhook]
        [Gemini API]
        [PostgreSQL cache tables]
```

### Container Names (for `docker exec`)
| Service | Container name |
|---|---|
| PostgreSQL | `cv_postgres_state` |
| Redis | `cv_redis` |
| Qdrant | `cv_qdrant` |
| BFF Gateway | `cv_bff_gateway` |
| Orchestrator | `cv_orchestrator` |
| Data Worker | `cv_worker_data` |
| Scraper Worker | `cv_worker_scraper` |
| Browser Worker | `cv_worker_browser` |
| fastCRW Engine | `cv_fastcrw` |
| Frontend | `cv_frontend_ui` |

---

## Key Files

| File | Purpose |
|---|---|
| `worker-data-io/tasks_api.py` | **Main AI task file.** Gemini parse, embeddings, Qdrant query. Has the cache layer. |
| `worker-data-io/db_ops.py` | Modulared SQL database query helper functions. |
| `worker-data-io/seed_jobs.py` | Seeds PostgreSQL + Qdrant with 4 job postings. Run once after stack up. |
| `workflow-orchestrator/graph.py` | LangGraph state machine. 4 nodes: parse_cv → evaluate_match → dispatch_tasks → complete |
| `workflow-orchestrator/state.py` | Pydantic models: `AgentState`, `CVData` |
| `workflow-orchestrator/main.py` | FastAPI app: `/api/v1/upload-cv`, `/api/v1/status/{thread_id}`, `/webhook/resume`, scraping CRUD |
| `workflow-orchestrator/simulate_upload.py` | E2E smoke test. Uploads the test CV, polls status, prints full state. |
| `worker-scraper/tasks_scraper.py` | Celery tasks executing crawls with fastCRW markdown crawling. |
| `tests/test_worker_data_io.py` | Unit tests including cache hit/miss, db_ops mocking, and sanitization tests. |
| `tests/test_worker_scraper.py` | Unit tests covering fastCRW payloads and Celery dispatcher callbacks. |
| `tests/example_cv.png` | Sample CV used by the simulation script. |

---

## The Caching System (Added Session 2026-06-09)

### Why
Gemini API calls are slow (~7-9 s for CV parse) and cost money. The same CV file uploaded repeatedly shouldn't trigger new API calls.

### How
Two PostgreSQL tables, auto-created on first task execution:

**`cv_parse_cache`**
```sql
CREATE TABLE cv_parse_cache (
    file_hash   VARCHAR(64) PRIMARY KEY,  -- SHA-256 of file base64 content
    parsed_data JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**`cv_embedding_cache`**
```sql
CREATE TABLE cv_embedding_cache (
    text_hash  VARCHAR(64) PRIMARY KEY,  -- SHA-256 of "Skills: X. Experience: Y"
    embedding  JSONB       NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Cache Key Strategy
- **Parse cache**: keyed on the raw `file_base64` string (SHA-256). Same file bytes → same hash → cache hit.
- **Embedding cache**: keyed on the constructed text `f"Skills: {skills_str}. Experience: {experience_str}"` (SHA-256). Same parsed CV content → cache hit.

### Guard Pattern
```python
_cache_tables_ready = False  # module-level flag

def _ensure_cache_tables():
    global _cache_tables_ready
    if _cache_tables_ready:
        return   # no-op on every call after the first
    # ... CREATE TABLE IF NOT EXISTS ...
    _cache_tables_ready = True
```
Called at the start of each task. Zero overhead after the first call per worker process.

### Verified Performance
| Scenario | Time |
|---|---|
| Cache MISS (first upload) | ~8-9 s |
| Cache HIT (same CV again) | ~0.3 s |

---

## CV Embedding & Score Matching (Added Session 2026-06-11)

### The Score Compression Problem
Cosine similarity scores returned by `gemini-embedding-001` across plain text documents are naturally compressed within a narrow band (typically 0.62–0.85). This caused completely irrelevant CVs (like an Administrative Assistant) to match software developer jobs at 65%, which is misleading to users.

### The Solution: Task Type Alignment + Score Rescaling
1. **Task Type Alignment**:
   - In `seed_jobs.py` (when indexing jobs), we use `task_type="retrieval_document"`.
   - In `tasks_api.py` (when searching with a CV), we use `task_type="retrieval_query"`.
   Aligning these task types according to Google's guidelines improves semantic retrieval and expands the score distribution.
2. **Linear Rescaling**:
   We apply a linear rescaling function to the raw similarity score `s`:
   `scaled_score = max(0.0, min(1.0, (s - 0.60) / 0.20))`
   - Raw scores `s <= 0.60` map to `0%` match (irrelevant CVs).
   - Raw scores `s >= 0.80` map to `100%` match (strong/exact matches).
   - In-between values scale linearly (e.g. `0.78` maps to `91%`).

### Cache Key Invalidation
To prevent using legacy `retrieval_document` embeddings from the PostgreSQL cache, the text hash cache key in `tasks_api.py` now prefixes `task_type=retrieval_query:` to the CV search text. This automatically invalidates and regenerates correct embeddings when the strategy changes.

---

## LangGraph State Machine

### Nodes
1. **`parse_cv`** — dispatches `tasks_api.parse_cv_with_gemini` to `data_io` queue, blocks on `task.get(timeout=60)`, populates `state.cv_data`
2. **`evaluate_match`** — dispatches `tasks_api.generate_vector_embeddings`, blocks, populates `state.matched_jobs`
3. **`dispatch_tasks`** — dispatches `tasks_browser.execute_job_application` to `browser_heavy` queue (async, does NOT block), sets `state.status = "review_pending"`
4. **`complete`** — sets `state.status = "submitted"` if `state.human_approved`

### HITL Mechanism
The graph is compiled with `interrupt_before=["complete"]`. When it hits the `complete` node, LangGraph saves the checkpoint to PostgreSQL and returns. The `/webhook/resume` endpoint calls `aupdate_state(..., {"human_approved": True})` then `ainvoke(None, config)` to resume.

### State Schema (`state.py`)
```python
class AgentState(TypedDict):
    user_id: str
    uploaded_file: dict          # {base64, mime_type, filename}
    cv_data: Optional[CVData]
    matched_jobs: list
    current_task_id: str
    status: str
    human_approved: bool
    job_board_url: str

class CVData(TypedDict):
    name: str
    contact_info: str
    skills: list[str]
    experience: str
```

---

## Celery Queue Routing (Critical)

Both workers must be on different queues or tasks get dropped silently.

**docker-compose.yml command for `worker-data-io`:**
```
celery -A tasks_api worker --loglevel=info -Q data_io -c 20
```

**docker-compose.yml command for `worker-browser-heavy`:**
```
celery -A tasks_browser worker --loglevel=info -Q browser_heavy --pool=solo
```

**graph.py dispatch:**
```python
celery_app.send_task('tasks_api.parse_cv_with_gemini', ..., queue='data_io')
celery_app.send_task('tasks_browser.execute_job_application', ..., queue='browser_heavy')
```

If you see `Unregistered task` in worker logs → the task went to the wrong queue or the worker restarted on the old queue.

---

## Verified End-to-End Flow (Confirmed Working)

Run the simulation from inside the orchestrator container:
```bash
docker compose exec orchestration-engine python /code/simulate_upload.py
```

Expected log output (worker-data-io):
```
CV parse cache MISS for example_cv.png – calling Gemini          ← first upload
Task tasks_api.parse_cv_with_gemini[...] succeeded in 7.8s
Embedding cache MISS – calling Gemini embedding API
Task tasks_api.generate_vector_embeddings[...] succeeded in 1.1s

CV parse cache HIT for example_cv.png (hash 232756a50b57…)       ← second upload
Embedding cache HIT (hash 76c1924878ac…)
Task tasks_api.generate_vector_embeddings[...] succeeded in 0.32s
```

Simulation script output will show `status: review_pending` with `matched_jobs` list.

---

## Known Issues & Gotchas

### 1. `LANGGRAPH_STRICT_MSGPACK` Warning
```
Deserializing unregistered type state.CVData from checkpoint.
```
Harmless warning. Means a checkpoint was saved before `CVData` was registered. Will be blocked in future LangGraph versions. Fix: add `CVData` to `allowed_msgpack_modules` in the checkpointer config.

### 2. `psycopg_pool` Deprecation Warning
```
opening the async pool AsyncConnectionPool in the constructor is deprecated
```
Fix: use `await pool.open()` or `async with AsyncConnectionPool(...) as pool:` in `orchestration-engine/main.py` lifespan handler. Cosmetic for now.

### 3. `google.generativeai` FutureWarning
```
All support for the google.generativeai package has ended.
```
The package still works but Google has deprecated it in favour of `google.genai`. When you have bandwidth: migrate `tasks_api.py` and `seed_jobs.py` to `import google.genai as genai`.

### 4. Qdrant `recreate_collection` Deprecation
In `seed_jobs.py`, `qdrant_client.recreate_collection(...)` is deprecated. Replace with:
```python
qdrant_client.delete_collection(collection_name)
qdrant_client.create_collection(collection_name, vectors_config=VectorParams(...))
```

### 5. Next.js Hydration Warning
Grammarly browser extension injects `data-new-gr-c-s-check-loaded` into `<body>`. Suppressed with `suppressHydrationWarning` in `layout.tsx`. Not a real bug.

### 6. Docker Desktop Must Be Running
Containers stop when Docker Desktop shuts down. Always `docker compose up -d --build` before testing. Seeds persist across restarts (PostgreSQL volume), but Qdrant vectors do too — no need to re-seed unless you `docker compose down -v`.

---

## Seeding (Do Once After First Boot)

```bash
docker compose exec worker-data-io python /code/seed_jobs.py
```

This:
1. Creates the `jobs` table in PostgreSQL (if absent)
2. Truncates + re-inserts 4 job postings
3. Calls `gemini-embedding-001` to embed each job
4. Creates/recreates the `job_postings` Qdrant collection
5. Upserts the 4 job vectors

After seeding, the `cv_parse_cache` and `cv_embedding_cache` tables are created automatically on the first task run.

---

## Test Suite

```bash
docker compose up --build test-runner
# or run locally:
cd tests && pytest -v
```

### Test files
| File | What it covers |
|---|---|
| `test_bff_gateway.py` | Root endpoint, trigger/resume/upload proxy routes |
| `test_workflow_orchestrator.py` | Trigger, resume, upload-cv, status endpoints, startup/shutdown |
| `test_worker_data_io.py` | **Cache hit/miss logic**, table creation idempotency, and data sanitization |
| `test_worker_job_applier.py` | Playwright browser worker task execution mock |
| `test_worker_scraper.py` | fastCRW crawling and Celery enqueue dispatcher callback mocks |

---

## Quick Reference Commands

```bash
# Start everything
docker compose up -d --build

# Seed the job database (once)
docker compose exec worker-data-io python /code/seed_jobs.py

# Run E2E simulation
docker compose exec workflow-orchestrator python /code/simulate_upload.py

# Watch worker logs live
docker compose logs -f worker-data-io

# Watch scraper logs live
docker compose logs -f worker-scraper

# Inspect cache tables
docker exec -it cv_postgres_state psql -U user -d cv_state \
  -c "SELECT file_hash, created_at FROM cv_parse_cache;"

# Run tests
docker compose up --build test-runner

# Rebuild only the data worker (fast, no full stack rebuild)
docker compose up -d --build worker-data-io

# Full reset (destroys all data)
docker compose down -v && docker compose up -d --build
```
