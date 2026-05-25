from langgraph.graph import StateGraph, START, END
from typing import Dict, Any
import os
from celery import Celery
from state import AgentState

REDIS_URL = os.getenv("REDIS_URL", "redis://message-broker:6379/0")
# Connect to the Celery broker to enqueue tasks to the workers
celery_app = Celery('orchestrator', broker=REDIS_URL, backend=REDIS_URL)

def parse_cv_node(state: AgentState):
    """
    Enqueues a task to the I/O worker (worker-data-io) for CV extraction via Gemini.
    """
    if state.cv_data and not state.cv_data.name:
        # Enqueue task
        task = celery_app.send_task('tasks_api.parse_cv_with_gemini', args=[state.cv_data.experience])
        state.current_task_id = task.id
    state.status = "parsing_cv"
    return state

def evaluate_match_node(state: AgentState):
    """
    Enqueues a task to the I/O worker to generate embeddings and query Qdrant.
    """
    task = celery_app.send_task('tasks_api.generate_vector_embeddings', args=[state.cv_data.dict(), []])
    state.current_task_id = task.id
    state.status = "matching"
    return state

def dispatch_browser_tasks(state: AgentState):
    """
    Dispatches tasks to the Heavy Browser Worker (Playwright).
    Since it uses a Solo Pool, it will be executed securely.
    """
    if state.matched_jobs:
        first_job = state.matched_jobs[0]
        # Dispatch to browser worker
        task = celery_app.send_task('tasks_browser.execute_job_application', args=[first_job.get("url"), state.cv_data.dict(), state.user_id])
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

# Checkpointer would be added when compiling the app
def compile_graph(checkpointer=None):
    return workflow.compile(checkpointer=checkpointer)
