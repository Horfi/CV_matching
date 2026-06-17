import json
import logging
import google.generativeai as genai
from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def clean_job_title_from_url(url: str, parsed_title: str) -> str:
    """
    If the parsed title is missing, generic, or default, attempts to extract
    a beautiful job title from the URL slug, supporting Google, Nvidia,
    and other standard URL schemes.
    """
    cleaned = parsed_title.strip() if parsed_title else ""
    if not cleaned or cleaned.lower() in ["job details", "jobs search", "google careers", "career", "job not found", "software engineer"]:
        from urllib.parse import urlparse
        import re
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        if not path:
            return cleaned or "Software Engineer (Google Careers)"
            
        # Take the last path segment
        segments = [s for s in path.split('/') if s]
        if not segments:
            return cleaned or "Software Engineer (Google Careers)"
        last_seg = segments[-1]
        
        # Clean up standard URL path separators/formats:
        # 1. Remove trailing file extensions (e.g. .html)
        last_seg = re.sub(r'\.[a-zA-Z0-9]+$', '', last_seg)
        
        # 2. Remove leading/trailing numbers or IDs
        last_seg = re.sub(r'^\d+-', '', last_seg)
        last_seg = re.sub(r'_\d+$', '', last_seg)
        last_seg = re.sub(r'_JR\d+$', '', last_seg)
        last_seg = re.sub(r'-JR\d+$', '', last_seg)
        
        # Replace dashes, underscores, and %20 with spaces
        title_raw = last_seg.replace('-', ' ').replace('_', ' ').replace('%20', ' ')
        
        # Capitalize words and strip
        words = [word.capitalize() for word in title_raw.split() if word]
        cleaned_slug_title = " ".join(words)
        
        if cleaned_slug_title and len(cleaned_slug_title) >= 3 and not cleaned_slug_title.isdigit():
            cleaned = cleaned_slug_title
            
    return cleaned or "Software Engineer (Google Careers)"



def is_invalid_job_page(markdown_content: str, title: str) -> bool:
    """
    Returns True if the page content indicates the job was taken down,
    or if it is a general search/listing page instead of a single job detail page.
    """
    if not markdown_content:
        return True
        
    content_lower = markdown_content.lower()
    title_lower = title.strip().lower() if title else ""
    
    # Taken down / not found markers
    if "job not found" in content_lower or "this job may have been taken down" in content_lower:
        return True
        
    # Listing page markers in disguise (if title is generic and it looks like a list page)
    if not title_lower or title_lower in ["job details", "jobs search", "google careers", "career", "search jobs"]:
        if "jobs matched" in content_lower or "filter_list" in content_lower or "showing 1 to 20" in content_lower:
            return True
            
    return False



def get_vector_embedding(text: str, task_type: str = "retrieval_query") -> list:
    """Generates embedding vector for text using Gemini embedding model."""
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not configured. Returning mock embedding.")
        return _get_fallback_vector()
        
    try:
        result = genai.embed_content(
            model="models/gemini-embedding-001",
            content=text,
            task_type=task_type
        )
        return result["embedding"]
    except Exception as e:
        logger.warning("Gemini embedding API call failed: %s. Returning mock embedding fallback.", e)
        return _get_fallback_vector()


def _get_fallback_vector() -> list:
    # Try to dynamically query Qdrant to match the correct dimension
    try:
        from qdrant_client import QdrantClient
        from config import QDRANT_URL
        client = QdrantClient(url=QDRANT_URL, timeout=5.0)
        collection_info = client.get_collection("job_postings")
        vectors_config = collection_info.config.params.vectors
        if hasattr(vectors_config, 'size'):
            size = vectors_config.size
        elif isinstance(vectors_config, dict) and 'size' in vectors_config:
            size = vectors_config['size']
        else:
            size = 768
        logger.info("Detected Qdrant collection vector size: %s", size)
        return [0.1] * size
    except Exception as exc:
        logger.warning("Failed to determine Qdrant collection size: %s. Defaulting to 768.", exc)
        return [0.1] * 768


def parse_cv_text_with_gemini(file_bytes: bytes, mime_type: str) -> dict:
    """Calls Gemini to parse raw CV bytes and structure details into JSON."""
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY is not configured. Returning mock parsed CV data.")
        return _get_fallback_cv_data()

    try:
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

        return json.loads(response.text)
    except Exception as e:
        logger.warning("Gemini CV parse failed: %s. Returning mock parsed CV data fallback.", e)
        return _get_fallback_cv_data()


def _get_fallback_cv_data() -> dict:
    return {
        "name": "Jane Doe",
        "contact_info": "jane.doe@example.com, +1-555-0199, github.com/janedoe",
        "skills": ["Python", "FastAPI", "React", "Docker", "DevOps", "PostgreSQL", "Qdrant", "Celery"],
        "experience": "Senior Software Engineer with 5+ years of experience building scalable backend microservices, REST APIs, and responsive React frontend dashboards."
    }


def parse_job_listing_programmatically(markdown_content: str, base_url: str = None) -> dict:
    """
    Programmatically parses raw markdown job listing to extract active job postings.
    Bypasses Gemini API calls to save tokens. Runs domain-agnostically.
    Returns: {"jobs": [{"title": "...", "url": "..."}]}
    """
    import re
    from urllib.parse import urljoin, urlparse
    
    # Extract all candidate links in markdown format [text](url) or HTML href="url"
    md_links = re.findall(r'\[[^\]]*\]\(([^)]+)\)', markdown_content)
    html_links = re.findall(r'href=["\']([^"\']+)["\']', markdown_content)
    all_urls = list(set(md_links + html_links))
    
    if not base_url:
        base_url = "https://www.google.com/about/careers/applications/jobs/results"
    
    base_parsed = urlparse(base_url)
    base_domain = base_parsed.netloc.lower()
    
    jobs = []
    for u in all_urls:
        u_trimmed = u.strip()
        if not u_trimmed or u_trimmed.startswith('#') or u_trimmed.startswith('javascript:'):
            continue
            
        full_url = urljoin(base_url, u_trimmed)
        parsed = urlparse(full_url)
        u_domain = parsed.netloc.lower()
        u_path = parsed.path.lower()
        
        # Check if URL belongs to the same domain (or is a known ATS like Workday/Greenhouse/Lever)
        is_same_domain = (base_domain in u_domain) or (u_domain in base_domain)
        is_ats = any(ats in u_domain for ats in ["myworkdayjobs.com", "greenhouse.io", "lever.co", "smartrecruiters.com"])
        
        if is_same_domain or is_ats:
            # Filter out generic/non-job pages
            if any(ignored in u_path for ignored in [
                "/privacy", "/terms", "/help", "/contact", "/login", "/register",
                "/cookies", "/eeo", "/faq", "/how-we-hire", "/my-applications", "/settings"
            ]):
                continue
                
            # Job posting URL paths typically contain /job/, /jobs/, /results/digits, /posting/, or /jobdetail
            is_job_detail = any(keyword in u_path for keyword in ["/job/", "/jobs/", "/results/", "/posting/", "/jobdetail"])
            
            # Make sure it's not the main listing landing page itself
            is_main_listing = u_path.rstrip('/') in [
                "/about/careers/applications/jobs/results",
                "/about/careers/applications/jobs",
                "/jobs",
                "/jobs/"
            ]
            
            if is_job_detail and not is_main_listing:
                if "/jobs/jobs/" in full_url:
                    full_url = full_url.replace("/jobs/jobs/", "/jobs/")
                title = clean_job_title_from_url(full_url, "")
                jobs.append({"title": title, "url": full_url})
                
    # Deduplicate extracted jobs by URL
    seen_urls = set()
    deduped_jobs = []
    for job in jobs:
        if job["url"] not in seen_urls:
            seen_urls.add(job["url"])
            deduped_jobs.append(job)
            
    # Fallback to defaults if no links discovered
    if not deduped_jobs:
        deduped_jobs = []
        
    return {"jobs": deduped_jobs}


def parse_job_detail_programmatically(markdown_content: str, job_url: str = None) -> dict:
    """
    Programmatically parses raw job detail page markdown.
    Bypasses Gemini API calls to save tokens. Runs domain-agnostically.
    Returns: {"title": "...", "company": "...", "description": "...", "skills": ["..."]}
    """
    import re
    
    # 1. Extract job title from URL slug or markdown header
    title = ""
    if job_url:
        title = clean_job_title_from_url(job_url, "")
    if not title:
        title_match = re.search(r'#+\s*(.+)', markdown_content)
        title = title_match.group(1).strip() if title_match else "Software Engineer (Google Careers)"

    # 2. Extract company from domain name or URL keywords
    company = "Google"
    if job_url:
        # Heuristic for sub-brands
        if "youtube" in job_url.lower() or "youtube" in title.lower():
            company = "YouTube"
        else:
            from urllib.parse import urlparse
            parsed = urlparse(job_url)
            domain = parsed.netloc.lower()
            domain = domain.replace("careers.", "").replace("jobs.", "").replace("workday.", "")
            parts = domain.split('.')
            if len(parts) >= 2:
                # If first part is www or wdX, take the next part
                if parts[0] == "www" and len(parts) >= 3:
                    name = parts[1]
                elif re.match(r'^wd\d+$', parts[0]) and len(parts) >= 3:
                    name = parts[1]
                else:
                    name = parts[0]
            else:
                name = parts[0] if parts else "Google"
            name = name.replace("myworkdayjobs", "")
            company = name.title() if name else "Google"

    # 3. Description: Grab the entire markdown content as is (more context for embeddings)
    description = markdown_content.strip() if markdown_content else "No description available."
    
    # 4. Skills: Scan description programmatically for key technical terms
    common_skills = [
        "python", "javascript", "typescript", "golang", "java", "c\\+\\+", "c#", "rust",
        "fastapi", "react", "next\\.js", "vue", "angular", "node\\.js", "express",
        "docker", "kubernetes", "aws", "gcp", "azure", "terraform", "ansible",
        "postgresql", "mysql", "redis", "mongodb", "qdrant", "elasticsearch",
        "celery", "rabbitmq", "playwright", "cypress", "selenium", "ci/cd", "devops",
        "sre", "machine learning", "ml", "ai", "llm", "nlp", "pytorch", "tensorflow",
        "scikit-learn", "pandas", "numpy", "git", "linux", "graphql", "rest api", "saas"
    ]
    
    found_skills = []
    desc_lower = description.lower()
    for skill in common_skills:
        # Match as word boundaries to prevent substring collisions
        pattern = rf'\b{skill}\b'
        if skill == "c\\+\\+":
            pattern = r'\bc\+\+'
            
        if re.search(pattern, desc_lower):
            display_name = skill.replace("\\", "")
            if display_name == "gcp":
                display_name = "GCP"
            elif display_name == "sre":
                display_name = "SRE"
            elif display_name == "saas":
                display_name = "SaaS"
            elif display_name == "ci/cd":
                display_name = "CI/CD"
            elif display_name == "ml":
                display_name = "ML"
            elif display_name == "ai":
                display_name = "AI"
            elif display_name == "llm":
                display_name = "LLM"
            elif display_name == "nlp":
                display_name = "NLP"
            else:
                display_name = display_name.title()
            found_skills.append(display_name)
            
    if not found_skills:
        found_skills = ["Software Engineering"]

    return {
        "title": title,
        "company": company,
        "description": description,
        "skills": list(set(found_skills))
    }


