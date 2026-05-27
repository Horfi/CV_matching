import os
from fastapi import FastAPI, Request
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver
from graph import compile_graph

app = FastAPI(title="Orchestration Engine")

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
    # entrypoint to start LangGraph processing
    return {"status": "started", "thread_id": "application-session-001"}

@app.post("/webhook/resume")
async def resume_workflow(data: dict):
    # Receives HTTP POST from Celery Playwright worker
    # Re-loads state by thread_id, updates state, continues graph
    return {"status": "resumed"}
