LISTING_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The title of the job offer"},
                    "url": {"type": "string", "description": "The full detail page URL of the job offer"}
                },
                "required": ["title", "url"]
            }
        }
    },
    "required": ["jobs"]
}

DETAIL_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "The title of the job offer"},
        "company": {"type": "string", "description": "Name of the company hiring"},
        "description": {"type": "string", "description": "Detailed description of the job, requirements, responsibilities"},
        "skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of key technical and professional skills mentioned in the job post"
        }
    },
    "required": ["title", "company", "description", "skills"]
}
