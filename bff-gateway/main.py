from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import os

app = FastAPI(title="BFF Gateway", description="Backend for Frontend API Gateway")

# Allow Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Update for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ORCHESTRATION_URL = os.getenv("ORCHESTRATION_URL", "http://orchestration-engine:8001")

class TriggerRequest(BaseModel):
    user_id: str
    cv_text: str

@app.get("/")
async def root():
    return {"message": "BFF Gateway is running"}

@app.post("/api/v1/trigger")
async def trigger_workflow_api(req: TriggerRequest):
    """
    Direct route to start the application process via Orchestrator
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{ORCHESTRATION_URL}/api/v1/trigger",
                json=req.dict(),
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/upload-cv")
async def upload_cv_api(file: UploadFile = File(...)):
    """
    Accepts file upload and forwards it to the Orchestrator.
    """
    async with httpx.AsyncClient() as client:
        try:
            content = await file.read()
            files = {'file': (file.filename, content, file.content_type)}
            response = await client.post(
                f"{ORCHESTRATION_URL}/api/v1/upload-cv",
                files=files,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/resume")
async def resume_workflow_api(thread_id: dict):
    """
    Called by Frontend to approve HITL
    """
    async with httpx.AsyncClient() as client:
        try:
            # We send to the orchestrator to resume the loop from DB
            response = await client.post(
                f"{ORCHESTRATION_URL}/webhook/resume",
                json=thread_id,
                timeout=10.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_orchestration(path: str, request: Request):
    # Proxy requests to the orchestration engine
    client = httpx.AsyncClient(base_url=ORCHESTRATION_URL)
    url = httpx.URL(path=request.url.path, query=request.url.query.encode("utf-8"))
    
    # Needs refinement for body bridging, auth headers, etc.
    body = await request.body()
    req = client.build_request(
        request.method,
        url,
        headers=request.headers.raw,
        content=body
    )
    response = await client.send(req)
    await client.aclose()
    
    # Return proxied response
    return response.json()
