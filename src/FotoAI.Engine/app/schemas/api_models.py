from pydantic import BaseModel
from typing import List, Optional

class HealthResponse(BaseModel):
    status: str
    version: str

class StatusResponse(BaseModel):
    is_running: bool
    current_folder: str
    total_files_found: int
    files_processed: int
    errors: int
    phase: str = "IDLE"            # SCANNING, DB_SYNC, MODEL, INDEXING, IDLE, FAILED
    message: str = ""              # texto pronto a mostrar na UI
    progress: float = -1.0         # 0..1, ou -1 se indeterminado
    eta_seconds: Optional[int] = None

class FolderResponseItem(BaseModel):
    id: int
    folder_path: str
    last_scanned: str
    scan_status: str
    image_count: int
    source_type: str = "FOLDER"     # FOLDER ou LIGHTROOM

class FolderListResponse(BaseModel):
    folders: List[FolderResponseItem]

class SearchRequest(BaseModel):
    query: str
    top_k: int = 50
    min_score: float = 0.15

class SearchResultItem(BaseModel):
    id: int
    file_name: str
    file_path: str
    score: float
    guid: str

class SearchResponse(BaseModel):
    results: List[SearchResultItem]
