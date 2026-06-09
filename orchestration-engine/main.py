import os
import uuid
import base64
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from graph import compile_graph

DB_URI = os.getenv("DATABASE_URL", "postgresql://user:password@state-vault:5432/cv_state")

pool = None
checkpointer = None
app_graph = None

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
