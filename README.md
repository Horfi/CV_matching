# CV Matcher & Automated Application Agent

A full-stack, AI-driven automation system designed to ingest your CV, find matching job descriptions, and automatically navigate platforms like Workday and Greenhouse to apply on your behalf. 

Powered by **Google Gemini 1.5 Flash** for document intelligence, **Playwright / browser-use** for browser automation, and **LangGraph** for cognitive orchestration.

---

## 🏗️ The 7-Container Architecture

This project is built on a highly decoupled, production-grade microservices architecture orchestrated by `docker-compose` to ensure robust resource isolation, mitigating memory leaks and system crashes common to headless browser environments.

### System Architecture Diagram

```mermaid
graph TD
    Client[Frontend UI<br/>Next.js / Port 3000] -->|HTTP / API Requests| BFF[Edge Gateway / BFF<br/>FastAPI / Port 8000]
    BFF -->|HTTP Proxy| Orchestrator[Orchestration Engine<br/>LangGraph + FastAPI / Port 8001]
    
    Orchestrator -->|Durable State & HITL| StateVault[(State Vault<br/>PostgreSQL / Port 5432)]
    Orchestrator -->|Enqueue Tasks| MessageBroker[Message Broker<br/>Redis / Port 6379]
    
    WorkerData[Async Data Worker<br/>Celery / I/O] -->|Consume Tasks| MessageBroker
    WorkerData -->|Semantic Search| VectorStore[(Vector Store<br/>Qdrant / Port 6333)]
    WorkerData -->|Document Intelligence| Gemini[Google Gemini API]
    
    WorkerBrowser[Browser Worker<br/>Celery / Playwright] -->|Consume Tasks| MessageBroker
    WorkerBrowser -->|Resume Webhook| Orchestrator
```

### Component Details & Connection Ports

Once the stack is running, you can connect directly to the following containers or access their dashboards:

| Container / Service | Image / Tech | External Port / Connection URI | Description |
| :--- | :--- | :--- | :--- |
| **1. Frontend UI** | Next.js / React | `http://localhost:3000` | The user interface dashboard for uploading CVs, inspecting matches, and human approval. |
| **2. Edge Gateway / BFF** | FastAPI | `http://localhost:8000` (Docs: `/docs`) | The public API gateway. Proxies frontend uploads and status requests to the orchestration engine. |
| **3. Orchestration Engine** | LangGraph + FastAPI | `http://localhost:8001` (Docs: `/docs`) | The control plane. Compiles the state graph, manages thread runs, handles checkpoints and resumes. |
| **4. Relational State Vault** | PostgreSQL 15 | `postgresql://user:password@localhost:5432/cv_state` | Persistent database storing CV metadata, seeded job postings, and LangGraph state checkpoints. |
| **5. Message Broker** | Redis | `redis://localhost:6379/0` | The async task broker. Handles Celery queues and message routing. |
| **6. Semantic Vector Store** | Qdrant | `http://localhost:6333` (UI: `/dashboard`) | Vector database storing high-dimensional semantic job embeddings for similarity searches. |
| **7. Async Data Worker** | Celery (Threaded) | *Internal* | Consumes I/O tasks: calls Gemini to parse resumes and generate vector embeddings. |
| **8. Autonomous Browser Worker**| Celery (Solo) | *Internal* | Consumes execution tasks: launches Playwright in ephemeral containers to automate form submissions. |

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

### 4. Monitoring & Debugging

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
│
├── bff-gateway/                 <-- Edge Gateway (BFF)
│   ├── Dockerfile               <-- Multi-stage build for routing & auth
│   └── main.py                  <-- upload-cv and resume endpoints
│
├── orchestration-engine/        <-- LangGraph Control Plane
│   ├── Dockerfile               
│   ├── graph.py                 <-- LangGraph workflow nodes & wait-for-celery logic
│   ├── state.py                 <-- Pydantic schemas (AgentState, CVData)
│   └── main.py                  <-- App setup, database pools, status API
│
├── worker-data-io/              <-- Async I/O Data Worker
│   ├── Dockerfile               
│   └── tasks_api.py             <-- Gemini parsing/embeddings & Qdrant query tasks
│
├── worker-browser-heavy/        <-- Playwright Browser automation Worker
│   ├── Dockerfile               <-- Bundles Playwright, chromium, and system deps
│   └── tasks_browser.py         <-- Solo pool browser-use automation logic
│
├── frontend-ui/                 <-- Next.js Frontend Presentation Layer
│   ├── Dockerfile           
│   ├── package.json         
│   └── src/                 
│       └── app/
│           ├── page.tsx         <-- Premium file upload & matched jobs UI
│           └── globals.css      <-- Tailwind CSS imports
│
├── scripts/                     
│   ├── wait_for_services.py     <-- Verification script checking TCP port availability
│   └── seed_jobs.py             <-- Script seeding database & vector store with job listings
│
└── tests/                       <-- Automated testing suite
    ├── requirements-test.txt    <-- Dependencies for testing
    ├── pytest.ini               <-- Pytest settings
    ├── test_bff_gateway.py
    ├── test_orchestration_engine.py
    ├── test_worker_browser_heavy.py
    └── test_worker_data_io.py
```

---

## 🚀 System Data Flow & State Management

**1. CV Ingestion:** The frontend UI requests a CV analysis by uploading a PDF/image resume to the Edge Gateway (`bff-gateway`).
**2. Graph Inception:** The Gateway forwards it to the Orchestration Engine. A LangGraph thread run is started with a unique ID, and its initial state is checkpointed in PostgreSQL (`state-vault`).
**3. AI Extraction:** The Orchestration Engine dispatches the raw CV bytes to the Data Worker (`worker-data-io`). Using `gemini-1.5-flash`, the CV is parsed into structured JSON and stored in PostgreSQL.
**4. Vector Matchmaking:** The CV details are encoded into embeddings using `gemini-embedding-001`. Qdrant indexes are searched for matching jobs, and the full job postings details are fetched from PostgreSQL and returned.
**5. Ephemeral Execution:** Relevant jobs are enqueued to Redis, consumed by the `worker-browser-heavy` container.
**6. Human-In-The-Loop (HITL) Checkpoint:** Playwright pauses the application flow before form submission. The Orchestration engine pauses execution, saving the state checkpoint to PostgreSQL.
**7. Resumption:** Once the candidate reviews the matches on the UI and clicks "Approve & Apply", the state is resumed from PostgreSQL, and the Playwright worker completes the submission.

---

## 🛠️ Environment Troubleshooting Notes

During setup, two key containerization bugs were resolved to ensure robust compilation and runtime behavior:

### 1. Python Compatibility in `worker-browser-heavy`
- **Symptom**: `pip install` failed because `browser-use` requires Python `>=3.11`, whereas standard Ubuntu 22.04 base images (like Playwright `jammy` tags) only package Python 3.10.
- **Solution**: Upgraded `worker-browser-heavy/Dockerfile` to `mcr.microsoft.com/playwright/python:v1.47.0-noble`, which bases the container on Ubuntu 24.04 (Noble Numbat) providing native **Python 3.12** support.

### 2. local Dependencies Masking in `frontend-ui`
- **Symptom**: The container exited with `sh: next: not found` due to the local volume mount (`./frontend-ui:/app`) masking the `/app/node_modules` directory built during image creation.
- **Solution**: Added an anonymous volume (`- /app/node_modules`) to the `frontend-ui` service in `docker-compose.yml` to prevent local directory overrides from hiding the container-internal dependencies.

