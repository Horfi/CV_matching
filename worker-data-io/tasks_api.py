import os
import json
import base64
import hashlib
import logging
import psycopg
from celery import Celery
from qdrant_client import QdrantClient
import google.generativeai as genai

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://message-broker:6379/0")
QDRANT_URL = os.getenv("QDRANT_URL", "http://vector-store:6333")
DB_URI = os.getenv("DATABASE_URL", "postgresql://user:password@state-vault:5432/cv_state")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

app = Celery('tasks_api', broker=REDIS_URL, backend=REDIS_URL)

# ---------------------------------------------------------------------------
# Cache helpers – avoids redundant Gemini API calls for identical inputs
# ---------------------------------------------------------------------------

_cache_tables_ready = False


def _ensure_cache_tables():
    """Create the cache tables once per worker lifetime."""
    global _cache_tables_ready
    if _cache_tables_ready:
        return
    with psycopg.connect(DB_URI) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cv_parse_cache (
                    file_hash   VARCHAR(64) PRIMARY KEY,
                    parsed_data JSONB       NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cv_embedding_cache (
                    text_hash  VARCHAR(64) PRIMARY KEY,
                    embedding  JSONB       NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
        conn.commit()
    _cache_tables_ready = True


def _hash_content(content: str) -> str:
    """Return a hex SHA-256 digest for a string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _get_cached_parse(file_hash: str):
    """Return cached parsed CV data or None."""
    try:
        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT parsed_data FROM cv_parse_cache WHERE file_hash = %s",
                    (file_hash,),
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None


def _store_cached_parse(file_hash: str, parsed_data: dict):
    """Store parsed CV data in cache."""
    try:
        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO cv_parse_cache (file_hash, parsed_data)
                       VALUES (%s, %s::jsonb)
                       ON CONFLICT (file_hash) DO NOTHING""",
                    (file_hash, json.dumps(parsed_data)),
                )
            conn.commit()
    except Exception as exc:
        logger.warning("Failed to write parse cache: %s", exc)


def _get_cached_embedding(text_hash: str):
    """Return cached embedding vector or None."""
    try:
        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT embedding FROM cv_embedding_cache WHERE text_hash = %s",
                    (text_hash,),
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None


def _store_cached_embedding(text_hash: str, embedding: list):
    """Store embedding vector in cache."""
    try:
        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO cv_embedding_cache (text_hash, embedding)
                       VALUES (%s, %s::jsonb)
                       ON CONFLICT (text_hash) DO NOTHING""",
                    (text_hash, json.dumps(embedding)),
                )
            conn.commit()
    except Exception as exc:
        logger.warning("Failed to write embedding cache: %s", exc)


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------

@app.task(name='tasks_api.parse_cv_with_gemini')
def parse_cv_with_gemini(file_base64: str, mime_type: str, filename: str):
    """
    Decodes CV file bytes and uses Gemini to extract structured JSON.
    Results are cached by file content hash so identical uploads skip the AI call.
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
        _ensure_cache_tables()

        # --- cache check (keyed on raw file content) ---
        file_hash = _hash_content(file_base64)
        cached = _get_cached_parse(file_hash)
        if cached is not None:
            logger.info("CV parse cache HIT for %s (hash %s…)", filename, file_hash[:12])
            return {"status": "success", "structured_data": cached}

        logger.info("CV parse cache MISS for %s – calling Gemini", filename)

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

        model = genai.GenerativeModel('gemini-2.5-flash')
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

        # --- store in cache ---
        _store_cached_parse(file_hash, structured_data)

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
    Embedding vectors are cached so identical CV text skips the AI call.
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
        _ensure_cache_tables()

        # Construct search text from CV details
        skills_str = ", ".join(cv_data.get("skills", []))
        experience_str = cv_data.get("experience", "")
        text_to_embed = f"Skills: {skills_str}. Experience: {experience_str}"

        # --- embedding cache check ---
        text_hash = _hash_content(text_to_embed)
        cached_vec = _get_cached_embedding(text_hash)

        if cached_vec is not None:
            logger.info("Embedding cache HIT (hash %s…)", text_hash[:12])
            cv_vector = cached_vec
        else:
            logger.info("Embedding cache MISS – calling Gemini embedding API")
            result = genai.embed_content(
                model="models/gemini-embedding-001",
                content=text_to_embed,
                task_type="retrieval_document"
            )
            cv_vector = result["embedding"]
            _store_cached_embedding(text_hash, cv_vector)

        # Connect to Qdrant and query
        qdrant_client = QdrantClient(url=QDRANT_URL)
        query_response = qdrant_client.query_points(
            collection_name="job_postings",
            query=cv_vector,
            limit=5
        )

        matched_job_ids = [hit.id for hit in query_response.points]
        scores = {hit.id: hit.score for hit in query_response.points}

        if not matched_job_ids:
            return {"status": "success", "matches": []}

        # Query PostgreSQL for job details
        matched_jobs = []
        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
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
