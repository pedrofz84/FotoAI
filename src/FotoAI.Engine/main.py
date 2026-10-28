import uvicorn
from fastapi import FastAPI
from app.core.logging import setup_logging
from loguru import logger

# 1. Configurar Boot Level (Logs e Pastas Base)
setup_logging()

# 2. Transações de Esqueleto (SQLite DDL e Qdrant Collection)
from app.db.database import Base, engine
import app.models.domain  # noqa: F401  (regista as tabelas no Base antes do create_all)
from app.vector.qdrant_client import vector_store

logger.info("Bootstrapping: A avaliar Modelo Relacional de Dados SQLite...")
Base.metadata.create_all(bind=engine) # Migração Automática SQLAlchemy

logger.info("Bootstrapping: A despertar Base Vetorial...")
vector_store.initialize()

# Juntar pastas indexadas que estejam dentro de outras (versões antigas permitiam-no)
try:
    from app.db.database import SessionLocal
    from app.services.folder_service import consolidate_folders
    with SessionLocal() as db:
        consolidate_folders(db)
except Exception as e:
    logger.error(f"Consolidação de pastas falhou: {e}")

# Se a base vetorial estiver vazia (ex: mudança do modo local para o servidor Qdrant)
# mas o SQLite achar que há fotos indexadas, volta a pô-las na fila.
try:
    from app.db.database import SessionLocal
    from app.models.domain import PhotoRecord
    n_vectors = vector_store.client.count(vector_store.COLLECTION_NAME, exact=True).count
    with SessionLocal() as db:
        n_indexed = db.query(PhotoRecord).filter(PhotoRecord.processing_status == "INDEXED").count()
        if n_vectors == 0 and n_indexed > 0:
            logger.warning(f"Qdrant vazio mas {n_indexed} fotos marcadas como indexadas. "
                           "Vão ser reindexadas no próximo sync de cada pasta.")
            db.query(PhotoRecord).filter(PhotoRecord.processing_status == "INDEXED").update(
                {"processing_status": "PENDING"}, synchronize_session=False)
            db.commit()
except Exception as e:
    logger.error(f"Verificação de consistência SQLite/Qdrant falhou: {e}")

# Carregar os modelos de IA em segundo plano (a UI mostra o progresso do download)
import os
if os.getenv("FOTOAI_PRELOAD", "1") != "0":
    from app.imaging.ml_pipeline import ml_pipeline
    ml_pipeline.preload()

# 3. Encapsular Rotas e levantar FastAPI
from app.api.routes import router

app = FastAPI(title="FotoAI.Engine", version="1.0.0", description="Motor Híbrido C# -> Python")
app.include_router(router, prefix="/api")

if __name__ == "__main__":
    logger.info("Arrancando Servidor ASGI (Uvicorn) no socket TCP 8000...")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False, access_log=False)
