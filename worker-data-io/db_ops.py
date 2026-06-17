import json
import logging
import psycopg
from config import DB_URI

logger = logging.getLogger(__name__)
_db_initialized = False

def ensure_db_schema():
    """Verify and initialize database tables for jobs, scraping sources, and caching."""
    global _db_initialized
    if _db_initialized:
        return
    
    with psycopg.connect(DB_URI) as conn:
        with conn.cursor() as cur:
            # 1. Create jobs table if it doesn't exist yet
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    company VARCHAR(255) NOT NULL,
                    description TEXT NOT NULL,
                    url VARCHAR(2048) NOT NULL,
                    skills TEXT NOT NULL
                );
            """)

            # 2. Create scraping_sources table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scraping_sources (
                    id SERIAL PRIMARY KEY,
                    url VARCHAR(2048) UNIQUE NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(50) DEFAULT 'careers_page',
                    status VARCHAR(50) DEFAULT 'idle',
                    is_default BOOLEAN DEFAULT FALSE,
                    last_scraped_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            
            cur.execute("""
                ALTER TABLE scraping_sources ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE;
            """)

            # Seed default sources
            default_sources = [
                ("https://www.google.com/about/careers/applications/jobs/results", "Google Careers", "careers_page"),
                ("https://www.google.com/about/careers/applications/jobs/results?q=youtube", "YouTube Careers", "careers_page"),
                ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", "Nvidia Careers", "careers_page")
            ]
            for url, name, s_type in default_sources:
                cur.execute("""
                    INSERT INTO scraping_sources (url, name, type, is_default, status)
                    VALUES (%s, %s, %s, TRUE, 'idle')
                    ON CONFLICT (url) DO UPDATE
                    SET is_default = TRUE;
                """, (url, name, s_type))
            
            # 3. Add source_id to jobs table if not exists
            cur.execute("""
                ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_id INTEGER REFERENCES scraping_sources(id) ON DELETE CASCADE;
            """)
            
            # 4. Ensure URL length is 2048 in jobs table
            cur.execute("""
                ALTER TABLE jobs ALTER COLUMN url TYPE VARCHAR(2048);
            """)
            
            # 5. Add unique constraint on url to jobs table if not exists
            cur.execute("""
                SELECT constraint_name 
                FROM information_schema.table_constraints 
                WHERE table_name = 'jobs' AND constraint_name = 'unique_job_url';
            """)
            if not cur.fetchone():
                cur.execute("""
                    ALTER TABLE jobs ADD CONSTRAINT unique_job_url UNIQUE (url);
                """)
                
            # 6. Create cache tables
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
    _db_initialized = True
    logger.info("Database schema verification completed successfully.")


def get_cached_parse(file_hash: str):
    """Retrieve cached parsed CV details or None."""
    ensure_db_schema()
    try:
        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT parsed_data FROM cv_parse_cache WHERE file_hash = %s", (file_hash,))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as exc:
        logger.warning("Failed to read parse cache: %s", exc)
        return None


def store_cached_parse(file_hash: str, parsed_data: dict):
    """Store parsed CV details in PostgreSQL cache."""
    ensure_db_schema()
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


def get_cached_embedding(text_hash: str):
    """Retrieve cached embedding vector or None."""
    ensure_db_schema()
    try:
        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT embedding FROM cv_embedding_cache WHERE text_hash = %s", (text_hash,))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as exc:
        logger.warning("Failed to read embedding cache: %s", exc)
        return None


def store_cached_embedding(text_hash: str, embedding: list):
    """Store embedding vector in PostgreSQL cache."""
    ensure_db_schema()
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


def update_source_status(source_id: int, status: str, update_timestamp: bool = False):
    """Update status (idle/scraping/completed/failed) of a scraping source."""
    ensure_db_schema()
    try:
        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                if update_timestamp:
                    cur.execute(
                        "UPDATE scraping_sources SET status = %s, last_scraped_at = NOW() WHERE id = %s",
                        (status, source_id),
                    )
                else:
                    cur.execute(
                        "UPDATE scraping_sources SET status = %s WHERE id = %s",
                        (status, source_id),
                    )
            conn.commit()
    except Exception as exc:
        logger.error("Failed to update scraping source status: %s", exc)


def get_obsolete_jobs(source_id: int, active_urls: list) -> list:
    """Finds IDs of jobs in PostgreSQL for a source whose URLs are not in the active URLs list."""
    ensure_db_schema()
    try:
        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                # If active_urls is empty, all jobs under this source are obsolete
                if not active_urls:
                    cur.execute("SELECT id FROM jobs WHERE source_id = %s", (source_id,))
                else:
                    cur.execute(
                        "SELECT id FROM jobs WHERE source_id = %s AND url != ALL(%s)",
                        (source_id, active_urls),
                    )
                return [row[0] for row in cur.fetchall()]
    except Exception as exc:
        logger.error("Failed to query obsolete jobs: %s", exc)
        return []


def delete_jobs(job_ids: list):
    """Deletes list of job IDs from PostgreSQL database."""
    ensure_db_schema()
    if not job_ids:
        return
    try:
        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM jobs WHERE id = ANY(%s)", (job_ids,))
            conn.commit()
        logger.info("Deleted %s jobs from PostgreSQL database.", len(job_ids))
    except Exception as exc:
        logger.error("Failed to delete jobs from database: %s", exc)


def upsert_job_detail(source_id: int, url: str, job: dict) -> int:
    """Inserts a new job or updates an existing job details in PostgreSQL, returning PostgreSQL ID."""
    ensure_db_schema()
    title = job.get("title", "")
    company = job.get("company", "")
    description = job.get("description", "")
    
    skills = job.get("skills", [])
    if isinstance(skills, list):
        skills_str = ", ".join(skills)
    else:
        skills_str = str(skills)

    with psycopg.connect(DB_URI) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM jobs WHERE url = %s", (url,))
            row = cur.fetchone()
            if row:
                job_id = row[0]
                cur.execute(
                    """UPDATE jobs 
                       SET title = %s, company = %s, description = %s, skills = %s, source_id = %s
                       WHERE id = %s""",
                    (title, company, description, skills_str, source_id, job_id),
                )
                logger.info("Updated job '%s' (ID: %s) in PostgreSQL database.", title, job_id)
            else:
                cur.execute(
                    """INSERT INTO jobs (title, company, description, url, skills, source_id)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (title, company, description, url, skills_str, source_id),
                )
                job_id = cur.fetchone()[0]
                logger.info("Inserted job '%s' (ID: %s) in PostgreSQL database.", title, job_id)
        conn.commit()
    return job_id


def _sanitize_structured_data(structured_data: dict) -> dict:
    """Ensure fields conform to Pydantic CVData model types (preventing validation errors)."""
    if not isinstance(structured_data, dict):
        structured_data = {}

    if not isinstance(structured_data.get("name"), str):
        structured_data["name"] = str(structured_data.get("name") or "")

    # Handle contact_info
    ci = structured_data.get("contact_info")
    if not isinstance(ci, str):
        if isinstance(ci, (dict, list)):
            if isinstance(ci, dict):
                parts = [f"{k}: {v}" for k, v in ci.items() if v]
                structured_data["contact_info"] = ", ".join(parts)
            else:
                structured_data["contact_info"] = json.dumps(ci, ensure_ascii=False)
        else:
            structured_data["contact_info"] = str(ci or "")

    # Handle skills
    skills = structured_data.get("skills")
    if not isinstance(skills, list):
        if isinstance(skills, str):
            structured_data["skills"] = [s.strip() for s in skills.split(",") if s.strip()]
        else:
            structured_data["skills"] = []
    else:
        structured_data["skills"] = [str(s) for s in skills if s]

    # Handle experience
    exp = structured_data.get("experience")
    if not isinstance(exp, str):
        if isinstance(exp, (dict, list)):
            if isinstance(exp, dict):
                lines = []
                for k, v in exp.items():
                    if isinstance(v, list):
                        lines.append(f"{k}:")
                        for item in v:
                            if isinstance(item, dict):
                                item_str = ", ".join(f"{sub_k}: {sub_v}" for sub_k, sub_v in item.items() if sub_v)
                                lines.append(f"  - {item_str}")
                            else:
                                lines.append(f"  - {item}")
                    elif isinstance(v, dict):
                        sub_str = ", ".join(f"{sub_k}: {sub_v}" for sub_k, sub_v in v.items() if sub_v)
                        lines.append(f"{k}: {sub_str}")
                    else:
                        lines.append(f"{k}: {v}")
                structured_data["experience"] = "\n".join(lines)
            else:
                structured_data["experience"] = json.dumps(exp, ensure_ascii=False)
        else:
            structured_data["experience"] = str(exp or "")
    return structured_data

