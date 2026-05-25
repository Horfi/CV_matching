# CV Matcher & Automated Application Agent

A full-stack, AI-driven automation system designed to ingest your CV, find matching job descriptions, and automatically navigate platforms like Workday and Greenhouse to apply on your behalf. 

Powered by **Google Gemini 2.5 Flash** for document intelligence, **Playwright / browser-use** for browser automation, and **LangGraph** for cognitive orchestration.

---

## 🏗️ The 7-Container Architecture

This project is built on a highly decoupled, production-grade microservices architecture orchestrated by `docker-compose` to ensure robust resource isolation, mitigating memory leaks and system crashes common to headless browser environments.

| Container | Tech Stack | Architecture Pattern / Role |
| :--- | :--- | :--- |
| **1. Edge Gateway / BFF** | Python (FastAPI) | **The Ambassador.** Serves as the sole public entry point. Manages auth, rate limiting, and aggregates data for the Next.js client. |
| **2. Orchestration Engine** | LangGraph + FastAPI | **The Control Plane.** Manages graph state, makes cognitive decisions, evaluates CV data via Gemini APIs, and dispatches instructions. |
| **3. Message Broker** | Redis | **The Nervous System.** Manages task queues, providing asynchronous decoupling between cognitive decision and mechanical action. |
| **4. Async Data Worker** | Celery (Threaded Pool) | **The I/O Processor.** Dedicated to lightweight async tasks: polling job boards, extracting data with Gemini, and embedding vectors. |
| **5. Autonomous Browser Worker**| Celery (Solo Pool) + Playwright | **The Execution Plane.** Executes heavy DOM manipulation. Uses the "Death Pact" config (`--max-tasks-per-child`) for pure memory isolation. |
| **6. Relational State Vault** | PostgreSQL | **Durable Memory.** Stores structured user data, CV profiles, and LangGraph checkpointing states for Human-in-the-Loop (HITL) pauses. |
| **7. Semantic Vector Store** | Qdrant | **The Matchmaker Core.** Manages high-dimensional embeddings to execute cosine similarity searches between CVs and Jobs. |

*(Note: The system also includes an 8th container for the **Frontend UI** built with Next.js/React).*

---

## 🗂️ File Structure

The workspace strictly enforces separation of concerns:

```text
/ (Root)
│
├── docker-compose.yml           <-- Master orchestration for the distributed system
├── README.md                    <-- Project documentation
│
├── bff-gateway/                 <-- FOLDER 1: Fast API Gateway (BFF)
│   ├── Dockerfile               <-- Secure routing & proxying to orchestration engine
│   └── main.py                  
│
├── orchestration-engine/        <-- FOLDER 2: LangGraph Control Plane
│   ├── Dockerfile               
│   ├── graph.py                 <-- LangGraph node/edge definitions
│   ├── state.py                 <-- Pydantic state schemas & PG checkpointer
│   └── main.py                  
│
├── worker-data-io/              <-- FOLDER 3: Async I/O Data Worker
│   ├── Dockerfile               <-- Lightweight Python image
│   └── tasks_api.py             <-- Job fetching, Gemini parsing, Embeddings
│
├── worker-browser-heavy/        <-- FOLDER 4: Playwright Heavy Execution
│   ├── Dockerfile               <-- Includes Chromium binaries & OS dependencies
│   └── tasks_browser.py         <-- Solo pool browser-use automation logic
│
└── frontend-ui/                 <-- FOLDER 5: Next.js / React Presentation Layer
    ├── Dockerfile           
    ├── package.json         
    └── src/                 
```

---

## 🚀 System Data Flow & State Management

**1. Initiation:** The frontend UI requests an application blitz through the BFF Gateway.
**2. Decision (Orchestration):** LangGraph processes the user's CV via the `worker-data-io` container and matches profiles across embeddings stored in Qdrant.
**3. Execution (Playwright):** Relevant jobs are enqueued to Redis, consumed by the `worker-browser-heavy` containers. Utilizing isolated ephemeral browser contexts, it performs complex DOM manipulations.
**4. Human-In-The-Loop (HITL):** At the final verification step on platforms like Workday, Playwright pauses. The Orchestration engine serializes its state directly into PostgreSQL (`langgraph-checkpoint-postgres`).
**5. Resumption:** Once the user reviews and clicks "Approve", the state is deserialized, signaling the pending Playwright worker via webhook to confirm and complete the application.
