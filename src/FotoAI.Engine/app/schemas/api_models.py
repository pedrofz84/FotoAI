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
    offset: int = 0                   # para "Mostrar mais": saltar os primeiros N resultados
    min_score: float = 0.15
    year_from: Optional[int] = None   # filtros por ano de captura (inclusive)
    year_to: Optional[int] = None

class SearchResultItem(BaseModel):
    id: int
    file_name: str
    file_path: str
    score: float
    guid: str
    capture_date: Optional[str] = None   # AAAA-MM-DD, se conhecida

class YearCount(BaseModel):
    year: int
    count: int

class YearsResponse(BaseModel):
    years: List[YearCount]
    without_date: int

class SearchResponse(BaseModel):
    results: List[SearchResultItem]
    has_more: bool = False            # True se pode haver mais resultados além destes
