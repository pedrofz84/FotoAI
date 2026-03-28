import os
import threading
from database import SessionLocal, PhotoRecord, IndexedFolder
from vector_db import vector_db
from ml_model import clip_engine
from datetime import datetime

class Indexer:
    def __init__(self):
        self.is_running = False
        self.current_folder = ""
        self.total_files_found = 0
        self.files_processed = 0
        self.errors = 0
        self._thread = None
        self.supported_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

    def get_status(self):
        return {
            "is_running": self.is_running,
            "current_folder": self.current_folder,
            "total_files_found": self.total_files_found,
            "files_processed": self.files_processed,
            "errors": self.errors
        }

    def start_indexing(self, folder_path: str):
        if self.is_running:
            return False
        
        self.current_folder = folder_path
        self.total_files_found = 0
        self.files_processed = 0
        self.errors = 0
        self.is_running = True
        
        self._thread = threading.Thread(target=self._index_task, args=(folder_path,))
        self._thread.daemon = True
        self._thread.start()
        return True

    def stop_indexing(self):
        self.is_running = False

    def _index_task(self, root_folder: str):
        print(f"Starting indexing on {root_folder}")
        db = SessionLocal()
        
        # Track that this folder is being indexed
        folder_record = db.query(IndexedFolder).filter(IndexedFolder.folder_path == root_folder).first()
        if not folder_record:
            folder_record = IndexedFolder(folder_path=root_folder)
            db.add(folder_record)
        folder_record.last_indexed = datetime.utcnow()
        db.commit()
        
        # Phase 1: Scan for files (Could be separated for 3TB, but let's do simply for pilot)
        file_list = []
        for dirpath, _, filenames in os.walk(root_folder):
            if not self.is_running:
                break
            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                if ext in self.supported_extensions:
                    full_path = os.path.join(dirpath, f)
                    file_list.append(full_path)
        
        self.total_files_found = len(file_list)
        print(f"Found {self.total_files_found} supported image files.")

        # Phase 2: Process each file
        for idx, file_path in enumerate(file_list):
            if not self.is_running:
                print("Indexing stopped by user.")
                break

            # Check if file is already in our SQLite DB
            record = db.query(PhotoRecord).filter(PhotoRecord.file_path == file_path).first()
            if record and record.processed == 1:
                self.files_processed += 1
                continue # Skip already processed

            try:
                # 1. Create or get record
                if not record:
                    file_name = os.path.basename(file_path)
                    try:
                        size_bytes = os.path.getsize(file_path)
                        modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    except:
                        size_bytes = 0
                        modified_time = datetime.utcnow()
                        
                    record = PhotoRecord(
                        file_path=file_path,
                        file_name=file_name,
                        size_bytes=size_bytes,
                        modified_date=modified_time,
                        processed=0
                    )
                    db.add(record)
                    db.commit()
                    db.refresh(record)

                chroma_id = str(record.id)
                record.chroma_id = chroma_id
                
                # 2. Extract embedding using CLIP
                embedding = clip_engine.encode_image(file_path)
                
                if embedding:
                    # 3. Store in Vector DB
                    metadata = {"file_path": file_path, "file_name": record.file_name}
                    vector_db.add_image_embedding(image_id=chroma_id, embedding=embedding, metadata=metadata)
                    
                    # 4. Mark as processed
                    record.processed = 1
                    db.commit()
                else:
                    self.errors += 1
                    
            except Exception as e:
                print(f"Failed to process {file_path}: {e}")
                self.errors += 1
            
            self.files_processed += 1
            
            # Print progress every 10 files
            if self.files_processed % 10 == 0:
                print(f"Processed {self.files_processed}/{self.total_files_found}")

        self.is_running = False
        db.close()
        print("Indexing completed or stopped.")

global_indexer = Indexer()
