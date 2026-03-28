import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from database import init_db, SessionLocal, PhotoRecord, IndexedFolder
from vector_db import vector_db
from indexer import global_indexer
from ml_model import clip_engine

app = FastAPI(title="FotosAI Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Make sure DB is initialized
init_db()

class SearchRequest(BaseModel):
    query: str
    top_k: int = 50

class IndexRequest(BaseModel):
    folder_path: str

@app.post("/api/index")
def start_index(req: IndexRequest):
    if not os.path.exists(req.folder_path):
        raise HTTPException(status_code=400, detail="A pasta não existe!")
    success = global_indexer.start_indexing(req.folder_path)
    if success:
        return {"status": "started", "folder": req.folder_path}
    return {"status": "already_running"}

@app.post("/api/index/stop")
def stop_index():
    global_indexer.stop_indexing()
    return {"status": "stopped"}

@app.get("/api/status")
def get_status():
    return global_indexer.get_status()

@app.get("/api/folders")
def get_folders():
    db = SessionLocal()
    folders = db.query(IndexedFolder).all()
    res = [{"id": f.id, "folder_path": f.folder_path, "last_indexed": str(f.last_indexed)} for f in folders]
    db.close()
    return {"folders": res}

@app.delete("/api/folders/{folder_id}")
def delete_folder(folder_id: int):
    db = SessionLocal()
    folder = db.query(IndexedFolder).filter(IndexedFolder.id == folder_id).first()
    if not folder:
        db.close()
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
    
    # Encontra todas as fotografias pertencentes a esta pasta
    photos = db.query(PhotoRecord).filter(PhotoRecord.file_path.like(folder.folder_path + '%')).all()
    
    # Extrai os IDs (chroma_id é igual ao ID do SQLite como vimos em indexer.py)
    chroma_ids = [str(p.id) for p in photos]
    
    # Elimina do Vector DB
    if chroma_ids:
        # Nota: grandes eliminações deveriam ser feitas em batch, deixamos simples
        vector_db.delete_embeddings(chroma_ids)
        
    # Elimina os registos da base de dados SQLite
    for p in photos:
        db.delete(p)
        
    db.delete(folder)
    db.commit()
    db.close()
    
    return {"status": "success", "deleted_photos": len(photos)}

@app.post("/api/search")
def search_photos(req: SearchRequest):
    # 1. Encode query with CLIP
    query_emb = clip_engine.encode_text(req.query)
    if not query_emb:
        raise HTTPException(status_code=500, detail="Falha ao codificar texto via IA")

    # 2. Search in vector DB
    results = vector_db.search_by_embedding(query_emb, n_results=req.top_k)
    
    if not results or "ids" not in results or not results["ids"][0]:
        return {"results": []}

    # 3. Fetch paths from SQLite
    db = SessionLocal()
    matched_ids = results["ids"][0]
    distances = results["distances"][0] if "distances" in results and results["distances"] else []
    
    records = []
    for i, chroma_id in enumerate(matched_ids):
        photo = db.query(PhotoRecord).filter(PhotoRecord.id == int(chroma_id)).first()
        if photo:
            score = distances[i] if i < len(distances) else 0.0
            records.append({
                "id": photo.id,
                "file_name": photo.file_name,
                "file_path": photo.file_path,
                "score": score
            })
            
    db.close()
    
    # Sort by score (ascending for distances like cosine used in Chroma)
    records.sort(key=lambda x: x["score"])
    
    return {"results": records}

@app.get("/image/{photo_id}")
def get_image(photo_id: int):
    db = SessionLocal()
    photo = db.query(PhotoRecord).filter(PhotoRecord.id == photo_id).first()
    db.close()
    
    if not photo or not os.path.exists(photo.file_path):
        raise HTTPException(status_code=404, detail="Photo not found")
        
    return FileResponse(photo.file_path)

@app.get("/")
def read_root():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
