from pydantic import BaseModel, HttpUrl
from typing import List, Dict, Optional

class EnumerateRequest(BaseModel):
    url: HttpUrl
    max_concurrency: int = 64
    timeout_seconds: int = 10
    follow_redirects: bool = False
    max_paths: int = 50000  # safety cap

class FoundItem(BaseModel):
    url: str
    path: str
    status: int
    size: Optional[int] = None
    redirected_to: Optional[str] = None
    wordlist: Optional[str] = None
    issues: List[str] = []

class GraphResult(BaseModel):
    nodes: List[Dict]
    edges: List[Dict]
    summary: Dict
    findings: List[FoundItem]
