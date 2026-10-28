from app.vector.qdrant_client import vector_store
from app.imaging.ml_pipeline import ml_pipeline
from app.db.database import SessionLocal
from app.models.domain import PhotoRecord

print("Loading model and searching...")
vector_store.initialize()
q = ml_pipeline.encode_text("pessoa")
res = vector_store.client.query_points(
    collection_name=vector_store.COLLECTION_NAME,
    query=q,
    limit=5
)
print("Qdrant Results:", res)
if res.points:
    db = SessionLocal()
    for hit in res.points:
        photo_id = hit.payload.get("photo_id")
        print(f"Look up photo_id={photo_id}")
        rec = db.query(PhotoRecord).filter(PhotoRecord.id == photo_id).first()
        print(f"SQLite found: {rec}")
