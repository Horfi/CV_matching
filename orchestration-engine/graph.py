from langgraph.graph import StateGraph, START, END
from typing import Dict, Any
import os
from celery import Celery
from state import AgentState, CVData

REDIS_URL = os.getenv("REDIS_URL", "redis://message-broker:6379/0")
# Connect to the Celery broker to enqueue tasks to the workers
celery_app = Celery('orchestrator', broker=REDIS_URL, backend=REDIS_URL)

def parse_cv_node(state: AgentState):
    """
    Enqueues a task to the I/O worker (worker-data-io) for CV extraction via Gemini
    and blocks to retrieve the result.
    """
    if state.uploaded_file:
        state.status = "parsing_cv"
        # Enqueue task
        task = celery_app.send_task(
            'tasks_api.parse_cv_with_gemini', 
            args=[
                state.uploaded_file.get("base64"),
                state.uploaded_file.get("mime_type"),
                state.uploaded_file.get("filename")
            ]
        )
        state.current_task_id = task.id
        
        # Wait for Celery result (timeout after 60s)
        try:
            result = task.get(timeout=60)
            if result.get("status") == "success":
                state.cv_data = CVData(**result["structured_data"])
                state.status = "parsing_complete"
            else:
                state.status = "parsing_failed"
        except Exception as e:
            state.status = f"parsing_failed: {str(e)}"
    
    return state

def evaluate_match_node(state: AgentState):
    """
    Enqueues a task to the I/O worker to generate embeddings and query Qdrant,
    then blocks to retrieve the matching job listings.
    """
    if state.cv_data:
        state.status = "matching"
        task = celery_app.send_task(
            'tasks_api.generate_vector_embeddings', 
            args=[state.cv_data.dict()]
        )
        state.current_task_id = task.id
        
        # Wait for Celery result
        try:
            result = task.get(timeout=60)
            if result.get("status") == "success":
                state.matched_jobs = result["matches"]
                state.status = "matching_complete"
            else:
                state.status = "matching_failed"
        except Exception as e:
            state.status = f"matching_failed: {str(e)}"
            
    return state

def dispatch_browser_tasks(state: AgentState):
    """
    Dispatches tasks to the Heavy Browser Worker (Playwright) to fill application forms.
    This task is triggered asynchronously and will pause for human approval.
    """
    if state.matched_jobs:
        first_job = state.matched_jobs[0]
        # Dispatch to browser worker
        task = celery_app.send_task(
            'tasks_browser.execute_job_application', 
            args=[first_job.get("url"), state.cv_data.dict(), state.current_task_id]
        )
        state.current_task_id = task.id
    
    state.status = "review_pending"
    return state

def complete_application(state: AgentState):
    if state.human_approved:
        state.status = "submitted"
    return state

# Initialize Graph
workflow = StateGraph(AgentState)

workflow.add_node("parse_cv", parse_cv_node)
workflow.add_node("evaluate_match", evaluate_match_node)
workflow.add_node("dispatch_tasks", dispatch_browser_tasks)
workflow.add_node("complete", complete_application)

workflow.add_edge(START, "parse_cv")
workflow.add_edge("parse_cv", "evaluate_match")
workflow.add_edge("evaluate_match", "dispatch_tasks")
workflow.add_edge("dispatch_tasks", "complete")
workflow.add_edge("complete", END)

# Checkpointer and Interrupt is added when compiling the app
def compile_graph(checkpointer=None):
    return workflow.compile(checkpointer=checkpointer, interrupt_before=["complete"])
