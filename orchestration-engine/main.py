import os
import uuid
import base64
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver
from graph import compile_graph

app = FastAPI(title="Orchestration Engine")

# Allow Next.js frontend and BFF Gateway
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_URI = os.getenv("DATABASE_URL", "postgresql://user:password@state-vault:5432/cv_state")

pool = None
checkpointer = None
app_graph = None

@app.on_event("startup")
def on_startup():
    global pool, checkpointer, app_graph
    # Setup PostgreSQL connection pool for the LangGraph Checkpointer
    pool = ConnectionPool(conninfo=DB_URI, max_size=20, kwargs={"autocommit": True})
    checkpointer = PostgresSaver(pool)
    
    # Needs PostgresSaver.setup() to establish tables
    checkpointer.setup()
    
    app_graph = compile_graph(checkpointer=checkpointer)

@app.on_event("shutdown")
def on_shutdown():
    if pool:
        pool.close()

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
