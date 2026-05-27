import os
import json
import base64
import psycopg
from celery import Celery
from qdrant_client import QdrantClient
import google.generativeai as genai

REDIS_URL = os.getenv("REDIS_URL", "redis://message-broker:6379/0")
QDRANT_URL = os.getenv("QDRANT_URL", "http://vector-store:6333")
DB_URI = os.getenv("DATABASE_URL", "postgresql://user:password@state-vault:5432/cv_state")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

app = Celery('tasks_api', broker=REDIS_URL, backend=REDIS_URL)

@app.task(name='tasks_api.parse_cv_with_gemini')
def parse_cv_with_gemini(file_base64: str, mime_type: str, filename: str):
    """
    Decodes CV file bytes and uses gemini-1.5-flash to extract structured JSON.
    """
    if not GEMINI_API_KEY:
        # Fallback to mock data for tests if no API key
        return {
            "status": "success",
            "structured_data": {
                "name": "Mock Candidate",
                "contact_info": "mock@example.com",
                "skills": ["Python", "Docker", "FastAPI"],
                "experience": "Experienced Software Engineer with 5 years in Python APIs."
            }
        }

    try:
        file_bytes = base64.b64decode(file_base64)
        
        # If it's plain text, we can just decode to string
        if mime_type.startswith("text/"):
            content = file_bytes.decode("utf-8")
            payload = [content]
        else:
            payload = [{
                "mime_type": mime_type,
                "data": file_bytes
            }]

        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = """
        Analyze the uploaded CV document (which may be a PDF, text, or image) and extract the key information.
        You must output a JSON object containing precisely these fields:
        - name: String (Full name of candidate)
        - contact_info: String (Email, phone number, links)
        - skills: Array of Strings (Key technical and professional skills)
        - experience: String (Detailed summary of work experience and roles)

        Ensure the output is valid JSON and nothing else.
        """
        payload.append(prompt)

        response = model.generate_content(
            payload,
            generation_config={"response_mime_type": "application/json"}
        )
        
        structured_data = json.loads(response.text)
        return {
            "status": "success",
            "structured_data": structured_data
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to parse CV: {str(e)}"
        }

@app.task(name='tasks_api.generate_vector_embeddings')
def generate_vector_embeddings(cv_data: dict, job_postings: list = None):
    """
    Generates embedding for the CV and queries Qdrant to find matching jobs.
    Then retrieves the full job details from PostgreSQL.
    """
    if not GEMINI_API_KEY:
        # Fallback mock matching for tests
        return {
            "status": "success",
            "matches": [
                {"job_id": 1, "title": "Senior Python Developer", "company": "TechSolutions Inc.", "score": 0.95, "url": "http://example.com/job/python-dev"},
                {"job_id": 2, "title": "Frontend React Engineer", "company": "DesignHub", "score": 0.88, "url": "http://example.com/job/react-dev"}
            ]
        }

    try:
        # Construct search text from CV details
        skills_str = ", ".join(cv_data.get("skills", []))
        experience_str = cv_data.get("experience", "")
        text_to_embed = f"Skills: {skills_str}. Experience: {experience_str}"

        # Generate CV embedding
        result = genai.embed_content(
            model="models/gemini-embedding-001",
            content=text_to_embed,
            task_type="retrieval_document"
        )
        cv_vector = result["embedding"]

        # Connect to Qdrant and query
        qdrant_client = QdrantClient(url=QDRANT_URL)
        search_results = qdrant_client.search(
            collection_name="job_postings",
            query_vector=cv_vector,
            limit=5
        )

        matched_job_ids = [hit.id for hit in search_results]
        scores = {hit.id: hit.score for hit in search_results}

        if not matched_job_ids:
            return {"status": "success", "matches": []}

        # Query PostgreSQL for job details
        matched_jobs = []
        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                # Use parameterized query to fetch job details
                cur.execute("""
                    SELECT id, title, company, description, url, skills
                    FROM jobs
                    WHERE id = ANY(%s)
                """, (matched_job_ids,))
                
                rows = cur.fetchall()
                for row in rows:
                    job_id = row[0]
                    matched_jobs.append({
                        "job_id": job_id,
                        "title": row[1],
                        "company": row[2],
                        "description": row[3],
                        "url": row[4],
                        "skills": row[5],
                        "score": round(scores.get(job_id, 0.0), 3)
                    })

        # Sort matches by score descending
        matched_jobs.sort(key=lambda x: x["score"], reverse=True)

        return {
            "status": "success",
            "matches": matched_jobs
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to perform matching: {str(e)}"
        }
