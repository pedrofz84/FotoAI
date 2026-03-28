from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./fotosai.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class PhotoRecord(Base):
    __tablename__ = "photos"

    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, unique=True, index=True, nullable=False)
    file_name = Column(String, index=True, nullable=False)
    size_bytes = Column(Integer, default=0)
    created_date = Column(DateTime, default=datetime.utcnow)
    modified_date = Column(DateTime, default=datetime.utcnow)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    # Status to keep track if it was processed by the embedding engine
    processed = Column(Integer, default=0) # 0 = false, 1 = true
    # We store the chroma id here if needed, but file_path can be the chroma ID
    chroma_id = Column(String, unique=True, index=True, nullable=True)

class IndexedFolder(Base):
    __tablename__ = "indexed_folders"
    id = Column(Integer, primary_key=True, index=True)
    folder_path = Column(String, unique=True, index=True, nullable=False)
    last_indexed = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
