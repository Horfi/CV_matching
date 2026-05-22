# CV Matcher & Automated Application Agent

A full-stack, AI-driven automation system designed to ingest your CV, find matching job descriptions, and automatically navigate platforms like Workday and Greenhouse to apply on your behalf. 

Powered by **Google Gemini 2.5 Flash** for document intelligence and **Playwright / browser-use** for browser automation.

---

## 🏗️ The 5-Container Architecture

This project is built on a robust, scalable microservices architecture orchestrated by `docker-compose`.

| Container | Tech Stack | Purpose |
| :--- | :--- | :--- |
| **1. The API Backend** | Python (FastAPI) | **The central brain.** It receives UI requests, talks to the LLM (Gemini 2.5) for fast PDF/Image parsing, and orchestrates tasks. |
| **2. The Message Broker** | Redis | **The waiting room.** When the API says "apply to these 10 jobs," it drops those tasks into Redis. It ensures tasks aren't lost if the system crashes. |
| **3. The AI Worker(s)** | Python (Celery) + Playwright | **The heavy lifters.** These containers pick up tasks from Redis, boot up the headless browsers, execute the job applications, and report back. |
| **4. The Database** | PostgreSQL | **The vault.** Stores user profiles, the extracted CV JSONs, job URLs, and application statuses (Applied, Failed, Interviewing). |
| **5. The Frontend UI** | Next.js or React | **The dashboard.** Where the user uploads their CV, sets preferences, and views their Kanban board of applications. |

---

## 🗂️ File Structure

The workspace is organized into discrete service folders:

```text
/ (Root)
│
├── docker-compose.yml       <-- The master blueprint that connects all 5 containers
├── README.md                <-- Project documentation
│
├── api-backend/             <-- FOLDER 1: FastAPI API
│   ├── Dockerfile           
│   ├── main.py              <-- Contains the CV ingestion logic via Gemini
│   └── requirements.txt     
│
├── ai-worker/               <-- FOLDER 2: Celery + Playwright
│   ├── Dockerfile           <-- Pre-configured with Headless Chromium dependencies
│   ├── tasks.py             <-- Where browser-use automation tasks will live
│   └── requirements.txt     
│
└── frontend-ui/             <-- FOLDER 3: Next.js / React
    ├── Dockerfile           
    ├── package.json         
    └── src/                 
```

---

## 🚀 Development Phases

### Phase 1: The Ingestion Pipeline ✅
Uses Google Gemini API to process uploaded CVs (PDF, PNG, JPG). Extracts the user's skills, work history, and education into a strict Pydantic-validated JSON model.

### Phase 2: The Browser Agent (Coming Next) ⏳
Building a standalone worker using `playwright` and `browser-use`. The AI relies on the parsed JSON profile to map your data to job application fields (like Workday setups) and includes a "Human-in-the-Loop" pause to verify information on the final page before submitting.

### Phase 3: The Matchmaker ⏳
Connecting to job APIs to pull live listings. We'll use embeddings/vector distance to match your scraped CV against 50+ job descriptions and output the top 5 matches.

### Phase 4: The Loop ⏳
Implementing `LangGraph` and Celery to bind the system. The agent systematically pulls a top match, navigates the URL, attempts the application, prompts for human review, and logs the result back into Postgres.
