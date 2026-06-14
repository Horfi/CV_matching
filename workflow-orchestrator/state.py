from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class CVData(BaseModel):
    name: str = ""
    contact_info: str = ""
    skills: List[str] = Field(default_factory=list)
    experience: str = ""

class AgentState(BaseModel):
    user_id: str
    cv_data: Optional[CVData] = None
    uploaded_file: Optional[Dict[str, str]] = None # {"base64": "...", "mime_type": "...", "filename": "..."}
    job_board_url: str = ""
    matched_jobs: List[Dict[str, Any]] = Field(default_factory=list)
    current_task_id: Optional[str] = None
    status: str = "initial" # initial, matching, review_pending, submitted
    human_approved: bool = False
    source_ids: List[int] = Field(default_factory=list)

