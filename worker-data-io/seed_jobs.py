import os
import sys
import psycopg
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import google.generativeai as genai

DB_URI = os.getenv("DATABASE_URL", "postgresql://user:password@state-vault:5432/cv_state")
QDRANT_URL = os.getenv("QDRANT_URL", "http://vector-store:6333")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY environment variable is required.", file=sys.stderr)
    sys.exit(1)

genai.configure(api_key=GEMINI_API_KEY)

jobs = [
    {
        "title": "Senior Python Developer",
        "company": "TechSolutions Inc.",
        "description": "We are seeking a Senior Python Developer to join our backend engineering team. You will build and scale RESTful APIs, integrate with PostgreSQL database architectures, manage Celery task queues, and deploy containers via Docker.",
        "url": "http://example.com/job/python-dev",
        "skills": "Python, Django, FastAPI, Celery, Redis, PostgreSQL, Docker, REST APIs"
    },
    {
        "title": "Frontend React Engineer",
        "company": "DesignHub",
        "description": "DesignHub is looking for a Frontend React Engineer. The ideal candidate will build interactive and highly aesthetic UI dashboards using Next.js, React, Tailwind CSS, TypeScript, and state management frameworks.",
        "url": "http://example.com/job/react-dev",
        "skills": "React, React.js, Next.js, HTML, CSS, Tailwind CSS, Javascript, TypeScript, state management, UI design"
    },
    {
        "title": "DevOps & Cloud Engineer",
        "company": "CloudScale Solutions",
        "description": "We are hiring a DevOps & Cloud Engineer. You will maintain CI/CD pipelines, manage Kubernetes clusters on AWS (EKS), configure cloud networks (VPCs, Security Groups), and write infrastructure as code (IaC) with Terraform.",
        "url": "http://example.com/job/devops",
        "skills": "AWS, DevOps, Kubernetes, K8s, Docker, CI/CD, Terraform, Infrastructure as Code, Linux, bash"
    },
    {
        "title": "Data Scientist / LLM Engineer",
        "company": "NeuroAI",
        "description": "NeuroAI is seeking an LLM Engineer / Data Scientist. You will fine-tune open-source models (Llama, Mistral), deploy pipelines with Hugging Face, run vector database similarity searches, and build conversational AI interfaces using LangChain or LangGraph.",
        "url": "http://example.com/job/data-scientist",
        "skills": "Data Science, Machine Learning, Python, PyTorch, LLMs, NLP, LangChain, LangGraph, Qdrant, Vector Databases, Hugging Face"
    }
]

def get_embedding(text):
    result = genai.embed_content(
        model="models/gemini-embedding-001",
        content=text,
        task_type="retrieval_document"
    )
    return result["embedding"]

def main():
    print("Connecting to PostgreSQL...")
    with psycopg.connect(DB_URI) as conn:
        with conn.cursor() as cur:
            # Create jobs table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    company VARCHAR(255) NOT NULL,
                    description TEXT NOT NULL,
                    url VARCHAR(255) NOT NULL,
                    skills TEXT NOT NULL
                );
            """)
            conn.commit()

            print("Database table 'jobs' verified.")
            
            # Clear existing jobs to ensure clean seed
            cur.execute("TRUNCATE TABLE jobs RESTART IDENTITY CASCADE;")
            conn.commit()

            db_job_ids = []
            for job in jobs:
                cur.execute("""
                    INSERT INTO jobs (title, company, description, url, skills)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                """, (job["title"], job["company"], job["description"], job["url"], job["skills"]))
                job_id = cur.fetchone()[0]
                db_job_ids.append(job_id)
                print(f"Inserted job '{job['title']}' in PostgreSQL with ID {job_id}.")
            conn.commit()

    print("Connecting to Qdrant at:", QDRANT_URL)
    qdrant_client = QdrantClient(url=QDRANT_URL, timeout=60.0)

    # Compute a sample embedding to get dimensions dynamically
    print("Fetching dummy embedding to determine dimension size...")
    sample_emb = get_embedding("test")
    vector_dim = len(sample_emb)
    print(f"Detected embedding dimension size: {vector_dim}")

    collection_name = "job_postings"
    
    # Recreate collection
    print(f"Recreating Qdrant collection '{collection_name}'...")
    qdrant_client.recreate_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_dim, distance=Distance.COSINE)
    )

    points = []
    for i, job_id in enumerate(db_job_ids):
        job = jobs[i]
        text_to_embed = f"Title: {job['title']}. Company: {job['company']}. Required Skills: {job['skills']}. Description: {job['description']}"
        print(f"Generating embedding for job {job_id}...")
        vector = get_embedding(text_to_embed)
        
        points.append(
            PointStruct(
                id=job_id,
                vector=vector,
                payload={
                    "job_id": job_id,
                    "title": job["title"],
                    "company": job["company"]
                }
            )
        )

    qdrant_client.upsert(
        collection_name=collection_name,
        points=points
    )
    print("Successfully seeded Qdrant collection with job postings!")

if __name__ == "__main__":
    main()
