import os
import uuid
import base64
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from graph import compile_graph
from pydantic import BaseModel

DB_URI = os.getenv("DATABASE_URL", "postgresql://user:password@state-vault:5432/cv_state")

pool = None
checkpointer = None
app_graph = None

# Pydantic models for request validation
class SourceCreate(BaseModel):
    url: str
    name: str
    type: str  # 'careers_page' or 'single_job'

class ScrapeSelectedRequest(BaseModel):
    ids: list[int]

class ApplyRequest(BaseModel):
    thread_id: str
    job_urls: list[str]
    cv_data: dict

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, checkpointer, app_graph
    # Setup PostgreSQL connection pool for the LangGraph Checkpointer
    pool = AsyncConnectionPool(conninfo=DB_URI, max_size=20, kwargs={"autocommit": True})
    checkpointer = AsyncPostgresSaver(pool)
    
    # Needs PostgresSaver.setup() to establish tables
    await checkpointer.setup()
    
    app_graph = compile_graph(checkpointer=checkpointer)
    yield
    if pool:
        await pool.close()

app = FastAPI(title="Orchestration Engine", lifespan=lifespan)

# Allow Next.js frontend and BFF Gateway
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/v1/trigger")
async def trigger_workflow(data: dict):
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    initial_input = {
        "user_id": data.get("user_id", "user123"),
        "status": "initial",
        "human_approved": False
    }
    if "cv_data" in data:
        initial_input["cv_data"] = data["cv_data"]
    if "source_ids" in data:
        initial_input["source_ids"] = data["source_ids"]
    if app_graph:
        await app_graph.ainvoke(initial_input, config)
    return {"status": "started", "thread_id": thread_id}

@app.post("/api/v1/upload-cv")
async def upload_cv(file: UploadFile = File(...)):
    content = await file.read()
    base64_str = base64.b64encode(content).decode("utf-8")
    
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_input = {
        "user_id": "user123",
        "uploaded_file": {
            "base64": base64_str,
            "mime_type": file.content_type,
            "filename": file.filename
        },
        "status": "initial",
        "human_approved": False
    }
    
    if app_graph:
        await app_graph.ainvoke(initial_input, config)
        
    return {"status": "started", "thread_id": thread_id}

@app.post("/webhook/resume")
async def resume_workflow(data: dict):
    thread_id = data.get("thread_id")
    if app_graph:
        config = {"configurable": {"thread_id": thread_id}}
        await app_graph.aupdate_state(config, {"human_approved": True}, as_node="complete")
        await app_graph.ainvoke(None, config)
    return {"status": "resumed"}

@app.get("/api/v1/status/{thread_id}")
async def get_status(thread_id: str):
    if app_graph:
        config = {"configurable": {"thread_id": thread_id}}
        state = await app_graph.aget_state(config)
        if state and state.values:
            return state.values
    raise HTTPException(status_code=404, detail="Thread not found")

# --- Scraper & Source Management Endpoints ---

@app.get("/api/v1/scraping/sources")
async def get_scraping_sources():
    if not pool:
        raise HTTPException(status_code=500, detail="Database connection pool not ready")
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT id, url, name, type, status, last_scraped_at, created_at
                    FROM scraping_sources
                    ORDER BY created_at DESC
                """)
                rows = await cur.fetchall()
                sources = []
                for row in rows:
                    sources.append({
                        "id": row[0],
                        "url": row[1],
                        "name": row[2],
                        "type": row[3],
                        "status": row[4],
                        "last_scraped_at": row[5].isoformat() if row[5] else None,
                        "created_at": row[6].isoformat() if row[6] else None
                    })
                return sources
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch sources: {str(e)}")

@app.post("/api/v1/scraping/sources")
async def add_scraping_source(source: SourceCreate):
    if not pool:
        raise HTTPException(status_code=500, detail="Database connection pool not ready")
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO scraping_sources (url, name, type, status)
                    VALUES (%s, %s, %s, 'idle')
                    ON CONFLICT (url) DO UPDATE
                    SET name = EXCLUDED.name, type = EXCLUDED.type, status = 'idle'
                    RETURNING id, url, name, type, status
                """, (source.url, source.name, source.type))
                row = await cur.fetchone()
                return {
                    "id": row[0],
                    "url": row[1],
                    "name": row[2],
                    "type": row[3],
                    "status": row[4]
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add source: {str(e)}")

@app.post("/api/v1/scraping/scrape-selected")
async def scrape_selected_sources(req: ScrapeSelectedRequest):
    if not pool:
        raise HTTPException(status_code=500, detail="Database connection pool not ready")
    
    from graph import celery_app
    triggered = []
    failed = []
    
    try:
        async with pool.connection() as conn:
            for source_id in req.ids:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT id, url, type FROM scraping_sources WHERE id = %s
                    """, (source_id,))
                    row = await cur.fetchone()
                    if not row:
                        failed.append({"id": source_id, "reason": "Not found"})
                        continue
                        
                    s_id, url, s_type = row
                    
                    # Update status to scraping
                    await cur.execute("""
                        UPDATE scraping_sources SET status = 'scraping' WHERE id = %s
                    """, (s_id,))
                    
                    # Dispatch task
                    if s_type == "careers_page":
                        celery_app.send_task(
                            'tasks_scraper.scrape_listing',
                            args=[s_id, url],
                            queue='scraper'
                        )
                    else:  # single_job
                        celery_app.send_task(
                            'tasks_scraper.scrape_detail',
                            args=[s_id, url],
                            queue='scraper'
                        )
                    triggered.append(s_id)
            await conn.commit()
        return {"status": "success", "triggered_ids": triggered, "failed": failed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to trigger scraping: {str(e)}")

@app.post("/api/v1/extract-cv")
async def extract_cv_only(file: UploadFile = File(...)):
    content = await file.read()
    base64_str = base64.b64encode(content).decode("utf-8")
    
    from graph import celery_app
    task = celery_app.send_task(
        'tasks_api.parse_cv_with_gemini',
        args=[base64_str, file.content_type, file.filename],
        queue='data_io'
    )
    try:
        result = task.get(timeout=60)
        if result.get("status") == "success":
            return result["structured_data"]
        else:
            raise HTTPException(status_code=500, detail=result.get("message", "Failed to parse CV"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during CV extraction: {str(e)}")

@app.post("/api/v1/apply-selected")
async def apply_selected(req: ApplyRequest):
    from graph import celery_app
    triggered_jobs = []
    
    try:
        for url in req.job_urls:
            celery_app.send_task(
                'tasks_browser.execute_job_application',
                args=[url, req.cv_data, req.thread_id],
                queue='browser_heavy'
            )
            triggered_jobs.append(url)
        return {"status": "success", "triggered_jobs": triggered_jobs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to trigger applications: {str(e)}")

