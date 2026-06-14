# CV Matcher & Automated Application Agent

A full-stack, AI-driven automation system designed to ingest your CV, find matching job descriptions, and automatically navigate platforms like Workday and Greenhouse to apply on your behalf.

Powered by **Google Gemini 2.5 Flash** for document intelligence, **Playwright / browser-use** for browser automation, and **LangGraph** for cognitive orchestration.

---

## 🏗️ The 10-Container Architecture

This project is built on a highly decoupled, production-grade microservices architecture orchestrated by `docker-compose` to ensure robust resource isolation, mitigating memory leaks and system crashes common to headless browser environments.

### System Architecture Diagram

```mermaid
graph TD
    Client[Frontend UI<br/>Next.js / Port 3000] -->|HTTP / API Requests| BFF[Edge Gateway / BFF<br/>FastAPI / Port 8000]
    BFF -->|HTTP Proxy| Orchestrator[Orchestration Engine<br/>LangGraph + FastAPI / Port 8001]

    Orchestrator -->|Durable State & HITL| StateVault[(State Vault<br/>PostgreSQL / Port 5432)]
    Orchestrator -->|Enqueue Tasks| MessageBroker[Message Broker<br/>Redis / Port 6379]

    WorkerData[Async Data Worker<br/>Celery / I/O] -->|Consume Tasks| MessageBroker
    WorkerData -->|Cache lookup/store| StateVault
    WorkerData -->|Semantic Search| VectorStore[(Vector Store<br/>Qdrant / Port 6333)]
    WorkerData -->|Document Intelligence| Gemini[Google Gemini API]

    WorkerBrowser[Browser Worker<br/>Celery / Playwright] -->|Consume Tasks| MessageBroker
    WorkerBrowser -->|Resume Webhook| Orchestrator

    WorkerScraper[Scraper Worker<br/>Celery / Crawler] -->|Consume Tasks| MessageBroker
    WorkerScraper -->|Trigger Crawls| FastCRW[fastCRW Scraper<br/>Rust / Port 3002]
```

### Component Details & Connection Ports

| Container / Service | Image / Tech | External Port / Connection URI | Description |
| :--- | :--- | :--- | :--- |
| **1. Frontend UI** | Next.js / React | `http://localhost:3000` | The user interface dashboard for uploading CVs, inspecting matches, and human approval. |
| **2. Edge Gateway / BFF** | FastAPI | `http://localhost:8000` (Docs: `/docs`) | The public API gateway. Proxies frontend uploads and status requests to the orchestration engine. |
| **3. Orchestration Engine** | LangGraph + FastAPI | `http://localhost:8001` (Docs: `/docs`) | The control plane. Compiles the state graph, manages thread runs, handles checkpoints and resumes. |
| **4. Relational State Vault** | PostgreSQL 15 | `postgresql://user:password@localhost:5432/cv_state` | Persistent database storing CV metadata, seeded job postings, LangGraph state checkpoints, **and AI result caches**. |
| **5. Message Broker** | Redis | `redis://localhost:6379/0` | The async task broker. Handles Celery queues and message routing. |
| **6. Semantic Vector Store** | Qdrant | `http://localhost:6333` (UI: `/dashboard`) | Vector database storing high-dimensional semantic job embeddings for similarity searches. |
| **7. Async Data Worker** | Celery (Threaded) | *Internal* | Consumes I/O tasks: calls Gemini to parse resumes, generate vector embeddings, and parse crawled markdown. **Results cached in PostgreSQL by content hash.** |
| **8. Autonomous Browser Worker**| Celery (Solo) | *Internal* | Consumes execution tasks: launches Playwright in ephemeral containers to automate form submissions. |
| **9. Self-Hosted fastCRW Engine**| Rust-native crawler | `http://localhost:3002` | High-speed webpage crawling engine (Firecrawl-compatible). |
| **10. Scraper Worker** | Celery (Threaded) | *Internal* | Consumes crawling tasks: triggers `fastcrw` to fetch webpage markdown. |

---

## ⚙️ Configuration & Prerequisites

### Prerequisites
- **Docker & Docker Compose**: Installed on your system.
- **WSL 2 (if on Windows)**: Active and integrated with Docker Desktop.

### Environment Setup (`.env`)
The system requires a `.env` file at the root of the project to supply API credentials.
Create a `.env` file (if not already present) and configure your Google Gemini API key:
```env
GEMINI_API_KEY="your-google-gemini-api-key-here"
```
This key is automatically read by Docker Compose and injected into the orchestration and data-worker services.

---

## 🛠️ Useful Commands & Scripts

Here are the essential commands for running, testing, and debugging the system.

### 1. Stack Management

- **Start all services (interactive mode):**
  ```bash
  docker compose up --build
  ```
- **Start all services in background (detached mode):**
  ```bash
  docker compose up -d --build
  ```
- **Stop all services:**
  ```bash
  docker compose down
  ```
- **Stop and remove all volumes (reset databases & vector stores):**
  ```bash
  docker compose down -v
  ```

### 2. Seeding Job Postings

To populate PostgreSQL and the Qdrant vector collection with job descriptions before matching:
1. Boot the stack.
2. Run the seeding script inside the data worker container:
   ```bash
   docker compose exec worker-data-io python /code/seed_jobs.py
   ```

### 3. Running Tests

- **Run all integration and unit tests:**
  ```bash
  docker compose up --build test-runner
  ```
- **Run tests and automatically stop/cleanup containers on exit:**
  ```bash
  docker compose up --build --abort-on-container-exit --exit-code-from test-runner test-runner
  ```

### 4. Simulate a CV Upload (End-to-End Test)

A simulation script is included in the workflow-orchestrator container. It uploads the test CV, polls the status endpoint, and prints the full matched-jobs state:
```bash
docker compose exec workflow-orchestrator python /code/simulate_upload.py
```
Expected output reaches `status: review_pending` — meaning the entire pipeline (parse → embed → match → browser dispatch) completed successfully and is awaiting human approval.

### 5. Monitoring & Debugging

- **Inspect Docker logs in real time:**
  ```bash
  docker compose logs -f <service-name>
  ```
- **Check Celery worker status & active tasks:**
  ```bash
  docker exec -it cv_worker_data celery -A tasks_api status
  docker exec -it cv_worker_data celery -A tasks_api inspect active
  ```
- **Inspect PostgreSQL state tables directly:**
  ```bash
  docker exec -it cv_postgres_state psql -U user -d cv_state -c "\dt"
  ```
- **Inspect the AI result caches:**
  ```bash
  docker exec -it cv_postgres_state psql -U user -d cv_state \
    -c "SELECT file_hash, created_at FROM cv_parse_cache;"
  docker exec -it cv_postgres_state psql -U user -d cv_state \
    -c "SELECT text_hash, created_at FROM cv_embedding_cache;"
  ```
- **Interact with Redis CLI:**
  ```bash
  docker exec -it cv_redis redis-cli monitor
  ```

---

## 🗂️ File Structure

The workspace strictly enforces separation of concerns:

```text
/ (Root)
│
├── docker-compose.yml           <-- Master orchestration for the distributed system
├── README.md                    <-- Project documentation
├── antigravity.md               <-- AI agent session notes & implementation insights
│
├── bff-gateway/                 <-- Edge Gateway (BFF)
│   ├── Dockerfile               <-- Multi-stage build for routing & auth
│   └── main.py                  <-- upload-cv, extract-cv and resume endpoints
│
├── workflow-orchestrator/       <-- LangGraph Control Plane (Renamed from orchestration-engine)
│   ├── Dockerfile
│   ├── graph.py                 <-- LangGraph workflow nodes & wait-for-celery logic
│   ├── state.py                 <-- Pydantic schemas (AgentState, CVData)
│   ├── main.py                  <-- App setup, database pools, status API, scraping endpoints
│   └── simulate_upload.py       <-- End-to-end pipeline smoke test script
│
├── worker-data-io/              <-- Async I/O Data Worker (Postgres/Qdrant operations)
│   ├── Dockerfile
│   ├── db_ops.py                <-- Relational state caching and job details querying
│   ├── qdrant_ops.py            <-- Vector storage indexing & semantic queries
│   ├── gemini_ops.py            <-- Gemini text parser & embedding queries
│   ├── tasks_api.py             <-- Celery tasks definition & routes
│   └── seed_jobs.py             <-- Seeds PostgreSQL + Qdrant with job postings
│
├── worker-scraper/              <-- Async Scraper Worker (fastCRW crawling)
│   ├── Dockerfile
│   ├── celery_app.py            <-- Scraper Celery registration
│   ├── fastcrw_client.py        <-- fastCRW structured schema extraction client
│   ├── schemas.py               <-- JSON schemas for listing & job detail extraction
│   └── tasks_scraper.py         <-- Celery crawl and save job data tasks
│
├── worker-job-applier/          <-- Playwright Browser Automation Worker (Renamed from worker-browser-heavy)
│   ├── Dockerfile               <-- Bundles Playwright, chromium, and system deps
│   └── tasks_browser.py         <-- Solo pool browser-use automation logic
│
├── frontend-ui/                 <-- Next.js Frontend Presentation Layer
│   ├── Dockerfile
│   ├── package.json
│   └── src/
│       └── app/
│           ├── page.tsx         <-- Premium file upload, sources manager, & matched jobs UI
│           └── globals.css      <-- Tailwind CSS imports
│
├── scripts/
│   └── wait_for_services.py     <-- Verification script checking TCP port availability
│
└── tests/                       <-- Automated testing suite
    ├── requirements-test.txt    <-- Dependencies for testing
    ├── pytest.ini               <-- Pytest settings
    ├── example_cv.png           <-- Sample CV used in end-to-end tests
    ├── test_bff_gateway.py
    ├── test_workflow_orchestrator.py
    ├── test_worker_job_applier.py
    ├── test_worker_data_io.py   <-- Includes cache hit/miss & idempotency tests
    └── test_worker_scraper.py   <-- Includes fastCRW crawler payload and task dispatch mocks
```

---

## 🚀 System Data Flow & State Management

**1. Source Crawling & Scraping:** The user selects career boards or single job URLs in the Next.js Frontend. Clicking "Scrape Selected" dispatches Celery tasks to the Scraper Worker (`worker-scraper`), which calls the self-hosted `fastcrw` engine to extract active job listings. Obsolete jobs are purged, and detailed requirements/skills are extracted and cached in the Relational State Vault (`state-vault`) and Semantic Vector Store (`vector-store`).

**2. CV Ingestion & Edit:** The candidate uploads their CV. Clicking "Extract CV Data" runs a Gemini parse task via `worker-data-io` and populates the Profile Form Editor where details (Name, Contact Info, Skills, Experience) can be edited.

**3. Graph Inception & Matching:** When the user clicks "Match Selected Jobs", the edited details are submitted. A LangGraph thread run starts with a unique ID, generating embeddings for the CV and matching similar job postings in Qdrant. Full match results are returned to the matched jobs list in the UI.

**4. Ephemeral Application Execution:** The user selects which jobs they want to apply to and clicks "Apply to Selected". Playwright application tasks are enqueued to the Applier Worker (`worker-job-applier`).

**5. Human-In-The-Loop (HITL) Checkpoint:** Playwright pauses the application flow before form submission. The Orchestration engine saves the state checkpoint to PostgreSQL and returns `status: review_pending`.

**6. Resumption:** Once the candidate reviews the forms on the UI and clicks "Approve & Apply", the state is resumed from PostgreSQL, and the Playwright worker completes the submission.

### AI Cache Performance

The caching layer delivers significant speedups for repeated uploads of the same CV:

| Scenario | Parse time | Embed time | Total |
|:---|:---|:---|:---|
| **First upload** (cache cold) | ~7-9 s (Gemini API) | ~1 s (Gemini API) | ~9 s |
| **Repeat upload** (cache warm) | ~0 ms (PostgreSQL) | ~0 ms (PostgreSQL) | ~0.3 s |

---

## 🛠️ Environment Troubleshooting Notes

During setup, several key containerization issues were resolved:

### 1. Python Compatibility in `worker-browser-heavy`
- **Symptom**: `pip install` failed because `browser-use` requires Python `>=3.11`, whereas standard Ubuntu 22.04 base images (like Playwright `jammy` tags) only package Python 3.10.
- **Solution**: Upgraded `worker-browser-heavy/Dockerfile` to `mcr.microsoft.com/playwright/python:v1.47.0-noble`, which bases the container on Ubuntu 24.04 (Noble Numbat) providing native **Python 3.12** support.

### 2. Local Dependencies Masking in `frontend-ui`
- **Symptom**: The container exited with `sh: next: not found` due to the local volume mount (`./frontend-ui:/app`) masking the `/app/node_modules` directory built during image creation.
- **Solution**: Added an anonymous volume (`- /app/node_modules`) to the `frontend-ui` service in `docker-compose.yml` to prevent local directory overrides from hiding the container-internal dependencies.

### 3. Celery Queue Routing
- **Symptom**: `worker-browser-heavy` was receiving `tasks_api` tasks (data-io queue) because both workers defaulted to the `celery` queue.
- **Solution**: Explicit `queues` configuration in `docker-compose.yml` — `worker-data-io` listens on `data_io`, `worker-browser-heavy` listens on `browser_heavy`. Tasks are dispatched with the `queue=` parameter in `graph.py`.

### 4. Hydration Warning in Next.js
- **Symptom**: Browser console showed `Extra attributes from the server: data-new-gr-c-s-check-loaded` — a Grammarly browser extension injecting attributes into `<body>` at runtime.
- **Solution**: Added `suppressHydrationWarning` to the `<body>` tag in `frontend-ui/src/app/layout.tsx`.

### 5. Qdrant Client API Version
- **Symptom**: `'QdrantClient' object has no attribute 'search'` on older container builds.
- **Solution**: Upgraded to `qdrant-client>=1.18.0` — use `query_points()` (not the deprecated `search()`). The response object exposes `.points` (a list of `ScoredPoint`).
