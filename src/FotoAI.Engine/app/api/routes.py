from fastapi import APIRouter, File, UploadFile, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import io
from PIL import Image
from app.schemas.api_models import HealthResponse, StatusResponse
from app.workers.job_manager import job_manager
from app.config.settings import settings
from loguru import logger
import os

router = APIRouter()

@router.get("/health", response_model=HealthResponse)
def health_check():
    """ Determines if the AI Engine is ready """
    return HealthResponse(status="ok", version="1.0.0")

@router.get("/status", response_model=StatusResponse)
def get_engine_status():
    """ Returns the progress of the background worker """
    status = job_manager.get_status()
    return StatusResponse(**status)

@router.post("/index")
def start_indexing(folder_path: str):
    """ Rotear chamada de indexação para a Thread daemon e gerir DB State """
    from app.db.database import SessionLocal
    from app.services.folder_service import resolve_index_target

    if job_manager.state not in ("IDLE", "FAILED"):
        return JSONResponse(status_code=409, content={"message": "Já há uma indexação a decorrer."})

    # Um catálogo .lrcat (importação nova ou nova sincronização a partir de "Gerir Pastas")
    if folder_path.lower().endswith(".lrcat"):
        return import_lightroom(folder_path)

    with SessionLocal() as db:
        # Trata pastas dentro de outras já indexadas (e vice-versa)
        lib, scan_path = resolve_index_target(db, folder_path)
        lib_id, lib_root = lib.id, lib.folder_path

    started = job_manager.trigger_library_indexing(lib_id, scan_path, library_root=lib_root)

    if started:
        logger.info(f"Index job accepted for {scan_path} (biblioteca ID {lib_id}: {lib_root})")
        return {"message": "Job Accepted", "library_id": lib_id, "library_root": lib_root}
    return JSONResponse(status_code=409, content={"message": "A job is already running"})

@router.post("/lightroom/import")
def import_lightroom(catalog_path: str):
    """ Importa (ou volta a sincronizar) um catálogo do Lightroom Classic, só em leitura """
    from app.db.database import SessionLocal
    from app.services.folder_service import resolve_lightroom_library
    from app.services.lightroom_service import validate_catalog, LightroomError

    if job_manager.state not in ("IDLE", "FAILED"):
        return JSONResponse(status_code=409, content={"message": "Já há uma indexação a decorrer."})
    try:
        validate_catalog(catalog_path)
    except LightroomError as e:
        return JSONResponse(status_code=400, content={"message": str(e)})

    with SessionLocal() as db:
        lib = resolve_lightroom_library(db, catalog_path)
        lib_id, lib_path = lib.id, lib.folder_path

    if job_manager.trigger_lightroom_indexing(lib_id, lib_path):
        logger.info(f"Importação do Lightroom aceite: {lib_path} (biblioteca ID {lib_id})")
        return {"message": "Job Accepted", "library_id": lib_id, "library_root": lib_path}
    return JSONResponse(status_code=409, content={"message": "Já há uma indexação a decorrer."})

@router.get("/photos/{guid_id}/thumbnail")
def get_thumbnail(guid_id: str):
    """ Serve a miniatura ultraleve em WebP """
    thumb_path = settings.THUMBNAIL_DIR / f"{guid_id}.webp"
    if thumb_path.exists():
        return FileResponse(thumb_path, media_type="image/webp")
    # 10. Fallback caso não exista (um ícone estático genérico poderia ser servido aqui em alternativa à falha 404)
    return JSONResponse(status_code=404, content={"message": "Thumbnail não existe"})

@router.get("/photos/{guid_id}/preview")
def get_preview(guid_id: str):
    """ Serve o preview HD em WebP, gerando-o na primeira vez que é pedido """
    from app.imaging.thumbnailer import ensure_preview
    from app.db.database import SessionLocal
    from app.models.domain import PhotoRecord

    preview_path = settings.PREVIEW_DIR / f"{guid_id}.webp"
    if not preview_path.exists():
        with SessionLocal() as db:
            rec = db.query(PhotoRecord).filter(PhotoRecord.guid_id == guid_id).first()
        if not rec:
            return JSONResponse(status_code=404, content={"message": "Foto não encontrada"})
        # Fotos do Lightroom: a pré-visualização grande já tem as edições e evita abrir o RAW
        source = rec.hd_path if rec.hd_path and os.path.exists(rec.hd_path) else rec.file_path
        if not os.path.exists(source):
            return JSONResponse(status_code=404, content={"message": "Foto original inacessível"})
        preview_path = ensure_preview(source, guid_id)
    if preview_path and preview_path.exists():
        return FileResponse(preview_path, media_type="image/webp")
    return JSONResponse(status_code=404, content={"message": "Preview não existe"})


@router.post("/index/cancel")
def cancel_indexing():
    """ Pede ao worker para parar no fim do lote atual (o progresso fica guardado) """
    job_manager.cancel()
    return {"message": "Cancel requested"}

from app.schemas.api_models import FolderListResponse, FolderResponseItem
from app.db.database import get_db
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException

@router.get("/folders", response_model=FolderListResponse)
def get_folders(db: Session = Depends(get_db)):
    from app.models.domain import IndexedFolder, PhotoRecord
    folders = db.query(IndexedFolder).all()
    res = []
    for f in folders:
        count = db.query(PhotoRecord).filter(PhotoRecord.library_id == f.id).count()
        res.append(FolderResponseItem(
            id=f.id,
            folder_path=f.folder_path,
            last_scanned=f.last_scanned.isoformat() if f.last_scanned else "",
            scan_status=f.scan_status,
            image_count=count,
            source_type=f.source_type or "FOLDER"
        ))
    return FolderListResponse(folders=res)

@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int, db: Session = Depends(get_db)):
    from app.models.domain import IndexedFolder, PhotoRecord
    from app.vector.qdrant_client import vector_store
    
    # 1. Verifica se a pasta existe
    folder = db.query(IndexedFolder).filter(IndexedFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Pasta não encontrada")
        
    # 2. Pede à base de dados todas as fotos associadas
    photos = db.query(PhotoRecord).filter(PhotoRecord.library_id == folder_id).all()
    guids_to_del = [p.guid_id for p in photos]
    
    # 3. Elimina fisicamente os Tensores MMap na Base Qdrant O(1)
    if guids_to_del:
        vector_store.delete_embeddings(guids_to_del)
        
    # 4. Elimina thumbnails físicas do WebP Purgatório (Cache)
    for g_id in guids_to_del:
        t_path = settings.THUMBNAIL_DIR / f"{g_id}.webp"
        p_path = settings.PREVIEW_DIR / f"{g_id}.webp"
        if t_path.exists(): os.remove(t_path)
        if p_path.exists(): os.remove(p_path)
        
    # 5. Cascata Relacional no SQLite
    db.query(PhotoRecord).filter(PhotoRecord.library_id == folder_id).delete(synchronize_session=False)
    db.delete(folder)
    db.commit()
    
    logger.info(f"[DELETE] Galeria ID {folder_id} expurgada com Sucesso. Removidos {len(guids_to_del)} registos.")
    return {"message": "Success", "deleted_count": len(guids_to_del)}

from app.schemas.api_models import SearchRequest, SearchResponse, SearchResultItem, YearsResponse, YearCount
from app.imaging.ml_pipeline import ml_pipeline
from app.vector.qdrant_client import vector_store
from app.db.database import get_db
from sqlalchemy.orm import Session
from fastapi import Depends
import time

def _date_filter(year_from: int | None, year_to: int | None):
    """ Filtro Qdrant pelo ano de captura. As fotos sem data ficam de fora quando há filtro. """
    from datetime import datetime, timezone
    from qdrant_client.models import Filter, FieldCondition, Range
    if year_from is None and year_to is None:
        return None
    if year_from is not None and year_to is not None and year_from > year_to:
        year_from, year_to = year_to, year_from
    gte = int(datetime(year_from, 1, 1, tzinfo=timezone.utc).timestamp()) if year_from else None
    lt = int(datetime(year_to + 1, 1, 1, tzinfo=timezone.utc).timestamp()) if year_to else None
    return Filter(must=[FieldCondition(key="capture_ts", range=Range(gte=gte, lt=lt))])

@router.get("/years", response_model=YearsResponse)
def list_years(db: Session = Depends(get_db)):
    """ Anos com fotos (para os filtros da UI) """
    from sqlalchemy import func
    from app.models.domain import PhotoRecord
    year = func.strftime("%Y", PhotoRecord.capture_time)
    rows = (db.query(year, func.count()).filter(PhotoRecord.capture_time.isnot(None),
                                                 PhotoRecord.processing_status == "INDEXED")
            .group_by(year).order_by(year).all())
    without = db.query(PhotoRecord).filter(PhotoRecord.capture_time.is_(None),
                                           PhotoRecord.processing_status == "INDEXED").count()
    return YearsResponse(years=[YearCount(year=int(y), count=n) for y, n in rows if y],
                         without_date=without)

def _format_search_results(search_result, db: Session, start_time: float) -> SearchResponse:
    """ Helper para converter hits do Qdrant em objetos SearchResponse do SQLite """
    from app.models.domain import PhotoRecord
    results_dto = []

    ids = [hit.payload.get("photo_id") for hit in search_result.points]
    recs = {r.id: r for r in db.query(PhotoRecord).filter(PhotoRecord.id.in_(ids)).all()} if ids else {}

    for hit in search_result.points:
        rec = recs.get(hit.payload.get("photo_id"))
        if rec:
            results_dto.append(SearchResultItem(
                id=rec.id,
                file_name=rec.file_name,
                file_path=rec.file_path,
                score=hit.score,
                guid=rec.guid_id,
                capture_date=rec.capture_time.strftime("%Y-%m-%d") if rec.capture_time else None
            ))
            
    processing_time = int((time.time() - start_time) * 1000)
    return SearchResponse(results=results_dto, processing_time_ms=processing_time)

@router.post("/search", response_model=SearchResponse)
def search_photos(request: SearchRequest, db: Session = Depends(get_db)):
    """ Realiza pesquisa semântica convertendo texto para vetor e buscando no Qdrant """
    start_time = time.time()
    query_vector = ml_pipeline.encode_text(request.query)
    
    search_result = vector_store.client.query_points(
        collection_name=vector_store.COLLECTION_NAME,
        query=query_vector,
        limit=request.top_k,
        score_threshold=request.min_score,
        query_filter=_date_filter(request.year_from, request.year_to)
    )
    
    return _format_search_results(search_result, db, start_time)

@router.post("/search/image", response_model=SearchResponse)
async def search_by_image(file: UploadFile = File(...), top_k: int = 50,
                          year_from: int | None = None, year_to: int | None = None,
                          db: Session = Depends(get_db)):
    """ Recebe uma imagem externa, gera o embedding e procura fotos semelhantes na base local """
    start_time = time.time()
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))
        # Extrair vetor da imagem via Vision Model (CLIP)
        query_vector = ml_pipeline.encode_pil_image(image)
    except Exception as e:
        logger.error(f"Erro ao processar imagem de pesquisa: {e}")
        raise HTTPException(status_code=400, detail="Ficheiro de imagem inválido ou corrompido")

    search_result = vector_store.client.query_points(
        collection_name=vector_store.COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        query_filter=_date_filter(year_from, year_to)
    )
    
    return _format_search_results(search_result, db, start_time)

@router.get("/search/similar/{photo_id}", response_model=SearchResponse)
def search_similar(photo_id: int, top_k: int = 50, year_from: int | None = None,
                   year_to: int | None = None, db: Session = Depends(get_db)):
    """ Encontra fotos semelhantes a uma já indexada, reutilizando o vetor guardado no Qdrant """
    start_time = time.time()
    from app.models.domain import PhotoRecord
    
    # 1. Localizar o registo para obter o GUID (ID no Qdrant)
    photo = db.query(PhotoRecord).filter(PhotoRecord.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Foto não encontrada na base de dados")

    # 2. Recuperar o vetor diretamente do Qdrant (sem re-inferência)
    points = vector_store.client.retrieve(
        collection_name=vector_store.COLLECTION_NAME,
        ids=[photo.guid_id],
        with_vectors=True
    )
    
    if not points or not points[0].vector:
        logger.warning(f"Vetor não encontrado para GUID {photo.guid_id}. A forçar re-indexação local para pesquisa.")
        # Fallback: Se o vetor sumiu do Qdrant mas o ficheiro existe, re-gera o vetor
        source = photo.load_path if photo.load_path and os.path.exists(photo.load_path) else photo.file_path
        if os.path.exists(source):
            query_vector = ml_pipeline.encode_image(source)
        else:
            raise HTTPException(status_code=404, detail="Vetor e ficheiro original inacessíveis")
    else:
        query_vector = points[0].vector

    # 3. Pesquisa por similaridade
    search_result = vector_store.client.query_points(
        collection_name=vector_store.COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
        query_filter=_date_filter(year_from, year_to)
    )
    
    return _format_search_results(search_result, db, start_time)
