import os
import json
import base64
import hashlib
import logging
import psycopg
from celery import Celery

import config
import db_ops
import qdrant_ops
import gemini_ops

logger = logging.getLogger(__name__)

app = Celery('tasks_api', broker=config.REDIS_URL, backend=config.REDIS_URL)

def _hash_content(content: str) -> str:
    """Return a hex SHA-256 digest for a string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def rescale_score(raw_score: float, min_val: float = 0.60, max_val: float = 0.80) -> float:
    """Linearly rescales raw cosine similarity scores into a 0.0-1.0 percentage range."""
    if raw_score <= min_val:
        return 0.0
    if raw_score >= max_val:
        return 1.0
    return (raw_score - min_val) / (max_val - min_val)


@app.task(name='tasks_api.parse_cv_with_gemini', bind=True, max_retries=5, default_retry_delay=15)
def parse_cv_with_gemini(self, file_base64: str, mime_type: str, filename: str):
    """
    Decodes CV file bytes and uses Gemini to extract structured JSON.
    Results are cached by file content hash so identical uploads skip the AI call.
    """
    try:
        db_ops.ensure_db_schema()

        # --- cache check (keyed on raw file content) ---
        file_hash = _hash_content(file_base64)
        cached = db_ops.get_cached_parse(file_hash)
        if cached is not None:
            logger.info("CV parse cache HIT for %s (hash %s…)", filename, file_hash[:12])
            sanitized = db_ops._sanitize_structured_data(cached)
            if sanitized != cached:
                db_ops.store_cached_parse(file_hash, sanitized)
            return {"status": "success", "structured_data": sanitized}

        logger.info("CV parse cache MISS for %s – calling Gemini", filename)

        file_bytes = base64.b64decode(file_base64)
        structured_data = gemini_ops.parse_cv_text_with_gemini(file_bytes, mime_type)
        structured_data = db_ops._sanitize_structured_data(structured_data)

        # --- store in cache ---
        db_ops.store_cached_parse(file_hash, structured_data)

        return {
            "status": "success",
            "structured_data": structured_data
        }
    except Exception as e:
        exc_str = str(e)
        if "ResourceExhausted" in exc_str or "429" in exc_str or "quota" in exc_str.lower():
            logger.warning("Gemini parse rate limit hit. Retrying task in 15 seconds: %s", e)
            raise self.retry(exc=e, countdown=15)
        return {
            "status": "error",
            "message": f"Failed to parse CV: {str(e)}"
        }


@app.task(name='tasks_api.generate_vector_embeddings', bind=True, max_retries=5, default_retry_delay=15)
def generate_vector_embeddings(self, cv_data: dict, job_postings: list = None, source_ids: list = None):
    """
    Generates embedding for the CV and queries Qdrant to find matching jobs.
    Embedding vectors are cached so identical CV text skips the AI call.
    """
    try:
        db_ops.ensure_db_schema()

        if not cv_data:
            cv_data = {}

        # Check if CV is blank
        skills = cv_data.get("skills") or []
        experience = cv_data.get("experience") or ""
        skills_clean = "".join(s.strip() for s in skills if isinstance(s, str))
        experience_clean = experience.strip()
        if not skills_clean and not experience_clean:
            logger.info("CV is blank. Bypassing search and returning zero matches.")
            return {"status": "success", "matches": []}

        # Construct search text from CV details
        skills_str = ", ".join(cv_data.get("skills", []))
        experience_str = cv_data.get("experience", "")
        text_to_embed = f"Skills: {skills_str}. Experience: {experience_str}"

        # Prefix key with task type config so any legacy retrieval_document cache entries are invalidated
        cache_key_text = f"task_type=retrieval_query:{text_to_embed}"

        # --- embedding cache check ---
        text_hash = _hash_content(cache_key_text)
        cached_vec = db_ops.get_cached_embedding(text_hash)

        if cached_vec is not None:
            logger.info("Embedding cache HIT (hash %s…)", text_hash[:12])
            cv_vector = cached_vec
        else:
            logger.info("Embedding cache MISS – calling Gemini embedding API")
            cv_vector = gemini_ops.get_vector_embedding(text_to_embed, task_type="retrieval_query")
            db_ops.store_cached_embedding(text_hash, cv_vector)

        # Connect to Qdrant and query
        points = qdrant_ops.query_similar_jobs(cv_vector, limit=100, source_ids=source_ids)
        matched_job_ids = [hit.id for hit in points]
        scores = {hit.id: hit.score for hit in points}

        if not matched_job_ids:
            return {"status": "success", "matches": []}

        # Query PostgreSQL for job details
        matched_jobs = []
        with psycopg.connect(config.DB_URI) as conn:
            with conn.cursor() as cur:
                if source_ids:
                    cur.execute("""
                        SELECT id, title, company, description, url, skills, source_id
                        FROM jobs
                        WHERE id = ANY(%s) AND source_id = ANY(%s)
                    """, (matched_job_ids, source_ids))
                else:
                    cur.execute("""
                        SELECT id, title, company, description, url, skills, source_id
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
                        "source_id": row[6],
                        "score": round(rescale_score(scores.get(job_id, 0.0)), 3)
                    })

        # Sort matches by score descending
        matched_jobs.sort(key=lambda x: x["score"], reverse=True)

        return {
            "status": "success",
            "matches": matched_jobs
        }


    except Exception as e:
        exc_str = str(e)
        if "ResourceExhausted" in exc_str or "429" in exc_str or "quota" in exc_str.lower():
            logger.warning("Gemini embedding rate limit hit. Retrying task in 15 seconds: %s", e)
            raise self.retry(exc=e, countdown=15)
        return {
            "status": "error",
            "message": f"Failed to perform matching: {str(e)}"
        }


@app.task(name='tasks_api.sync_listing_jobs')
def sync_listing_jobs(source_id: int, active_jobs: list):
    """
    Receives list of active jobs found on the listing board.
    Purges obsolete jobs from DB/Qdrant, and enqueues detail crawls for new jobs.
    """
    logger.info("Received active job list of size %s for source %s", len(active_jobs), source_id)
    try:
        db_ops.ensure_db_schema()
        active_urls = [job.get("url") for job in active_jobs if job.get("url")]
        
        # 1. Identify and purge obsolete jobs
        obsolete_ids = db_ops.get_obsolete_jobs(source_id, active_urls)
        if obsolete_ids:
            logger.info("Purging %s expired jobs under source %s", len(obsolete_ids), source_id)
            db_ops.delete_jobs(obsolete_ids)
            qdrant_ops.delete_qdrant_points(obsolete_ids)
            
        # 2. Trigger scraper detail tasks for new jobs
        new_jobs_triggered = 0
        with psycopg.connect(config.DB_URI) as conn:
            with conn.cursor() as cur:
                for job in active_jobs:
                    url = job.get("url")
                    if not url:
                        continue
                    cur.execute("SELECT id FROM jobs WHERE url = %s", (url,))
                    if not cur.fetchone():
                        # Job is new, enqueue scrape task to the scraper worker
                        app.send_task(
                            'tasks_scraper.scrape_detail',
                            args=[source_id, url],
                            queue='scraper'
                        )
                        new_jobs_triggered += 1
                        
        logger.info("Triggered %s new job detail crawls", new_jobs_triggered)
        if new_jobs_triggered == 0:
            # If no new jobs need to be crawled, the scrape cycle is completed
            db_ops.update_source_status(source_id, 'completed', update_timestamp=True)
            
        return f"Synchronized listing. Obsolete purged: {len(obsolete_ids)}. New detail crawls enqueued: {new_jobs_triggered}."
    except Exception as exc:
        logger.error("Failed to sync listing jobs: %s", exc)
        db_ops.update_source_status(source_id, 'failed')
        raise exc


@app.task(name='tasks_api.save_job_detail')
def save_job_detail(source_id: int, job_url: str, structured_job: dict):
    """
    Receives structured job details (title, company, description, skills).
    Saves/updates details in PostgreSQL, generates embeddings, and uploads to Qdrant.
    """
    logger.info("Saving job details for %s", job_url)
    try:
        db_ops.ensure_db_schema()
        
        # 1. Save/upsert to PostgreSQL
        job_id = db_ops.upsert_job_detail(source_id, job_url, structured_job)
        
        # 2. Generate embedding vector
        skills_list = structured_job.get("skills", [])
        skills_str = ", ".join(skills_list) if isinstance(skills_list, list) else str(skills_list)
        description = structured_job.get("description", "")
        text_to_embed = f"Skills: {skills_str}. Experience: {description}"
        
        vector = gemini_ops.get_vector_embedding(text_to_embed, task_type="retrieval_document")
        
        # 3. Upload vector point to Qdrant
        payload = {
            "title": structured_job.get("title", ""),
            "company": structured_job.get("company", ""),
            "description": description,
            "url": job_url,
            "skills": skills_str,
            "source_id": int(source_id)
        }
        qdrant_ops.upsert_qdrant_point(job_id, vector, payload)
        
        # 4. Finalize scraping source status as completed
        db_ops.update_source_status(source_id, 'completed', update_timestamp=True)
        return f"Successfully saved job ID {job_id}."
    except Exception as exc:
        logger.error("Failed to save job detail for %s: %s", job_url, exc)
        db_ops.update_source_status(source_id, 'failed')
        raise exc


@app.task(name='tasks_api.update_source_status')
def update_source_status(source_id: int, status: str):
    """Simple wrapper task to allow worker-scraper to report failures to the DB."""
    db_ops.update_source_status(source_id, status)


@app.task(
    name='tasks_api.parse_and_sync_listing',
    bind=True,
    max_retries=10,
    default_retry_delay=15
)
def parse_and_sync_listing(self, source_id: int, markdown_content: str, base_url: str):
    """
    Called after worker-scraper crawls the listing page.
    Uses Gemini to extract structured job listing links, then calls sync_listing_jobs.
    """
    logger.info("Parsing listing markdown with Gemini for source_id %s", source_id)
    try:
        extraction = gemini_ops.parse_job_listing_programmatically(markdown_content, base_url)
        jobs_list = extraction.get("jobs", [])
        
        # Now trigger the sync
        sync_listing_jobs(source_id, jobs_list)
        return f"Successfully parsed listing. Triggered sync for {len(jobs_list)} jobs."
    except Exception as exc:
        exc_str = str(exc)
        if "ResourceExhausted" in exc_str or "429" in exc_str or "quota" in exc_str.lower():
            logger.warning("Gemini rate limit hit during listing parsing. Retrying in 15 seconds: %s", exc)
            raise self.retry(exc=exc, countdown=15)
        logger.error("Failed to parse and sync listing for source %s: %s", source_id, exc)
        db_ops.update_source_status(source_id, 'failed')
        raise exc


@app.task(
    name='tasks_api.parse_and_save_job_detail',
    bind=True,
    max_retries=10,
    default_retry_delay=15,
    rate_limit='30/m'
)
def parse_and_save_job_detail(self, source_id: int, job_url: str, markdown_content: str):
    """
    Called after worker-scraper crawls a single job detail page.
    Uses Gemini to parse detail page markdown and save/upsert the job detail.
    """
    logger.info("Parsing detail markdown with Gemini for job: %s", job_url)
    try:
        structured_job = gemini_ops.parse_job_detail_programmatically(markdown_content, job_url=job_url)
        
        # Check if the page is invalid or taken down
        if gemini_ops.is_invalid_job_page(markdown_content, structured_job.get("title", "")):
            logger.warning("Job detail page is invalid or taken down for URL: %s", job_url)
            # Purge the job if it exists in the database/Qdrant
            db_ops.ensure_db_schema()
            with psycopg.connect(config.DB_URI) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM jobs WHERE url = %s", (job_url,))
                    row = cur.fetchone()
                    if row:
                        job_id = row[0]
                        db_ops.delete_jobs([job_id])
                        qdrant_ops.delete_qdrant_points([job_id])
            raise ValueError(f"Job at {job_url} has been taken down or is invalid.")

        # Now save the job details
        save_job_detail(source_id, job_url, structured_job)
        return "Successfully parsed and saved job detail."
    except Exception as exc:
        exc_str = str(exc)
        if "ResourceExhausted" in exc_str or "429" in exc_str or "quota" in exc_str.lower():
            logger.warning("Gemini rate limit hit during detail parsing. Retrying in 15 seconds: %s", exc)
            raise self.retry(exc=exc, countdown=15)
        logger.error("Failed to parse and save job detail for %s: %s", job_url, exc)
        db_ops.update_source_status(source_id, 'failed')
        raise exc


@app.task(name='tasks_api.delete_source')
def delete_source(source_id: int):
    """Deletes a source and all its associated jobs from both DB and Qdrant."""
    try:
        db_ops.ensure_db_schema()
        # 1. Get all job IDs for this source
        with psycopg.connect(config.DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM jobs WHERE source_id = %s", (source_id,))
                job_ids = [row[0] for row in cur.fetchall()]
        
        # 2. Delete points from Qdrant
        if job_ids:
            qdrant_ops.delete_qdrant_points(job_ids)
            
        # 3. Delete source from PostgreSQL (cascades to jobs)
        with psycopg.connect(config.DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM scraping_sources WHERE id = %s", (source_id,))
            conn.commit()
        logger.info("Deleted source %s and %s associated jobs from DB & Qdrant", source_id, len(job_ids))
        return f"Deleted source {source_id} and {len(job_ids)} jobs."
    except Exception as exc:
        logger.error("Failed to delete source %s: %s", source_id, exc)
        raise exc


