from sqlalchemy import Column, Integer, String, Float, DateTime
from datetime import datetime
from app.db.database import Base

class PhotoRecord(Base):
    __tablename__ = "photos"

    id = Column(Integer, primary_key=True, index=True)
    library_id = Column(Integer, index=True, nullable=False)
    file_path = Column(String, unique=True, index=True, nullable=False)
    file_name = Column(String, index=True, nullable=False)
    guid_id = Column(String, unique=True, index=True, nullable=False)
    
    # Mechanics for diffing (Deteção passiva de Ficheiros Modificados)
    size_bytes = Column(Integer, default=0)
    mtime = Column(Float, default=0.0)
    
    # State tracking per-file isolation
    processing_status = Column(String, default="PENDING", index=True) # PENDING, INDEXED, FAILED
    error_message = Column(String, nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow)
    indexed_date = Column(DateTime, nullable=True)

class IndexedFolder(Base):
    __tablename__ = "indexed_folders"
    
    id = Column(Integer, primary_key=True, index=True)
    folder_path = Column(String, unique=True, index=True, nullable=False)
    last_scanned = Column(DateTime, default=datetime.utcnow)
    scan_status = Column(String, default="IDLE") # IDLE, SCANNING, DB_SYNC, INDEXING
