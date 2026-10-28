import os
from sqlalchemy.orm import Session
from app.models.domain import PhotoRecord
import uuid
from loguru import logger

class DiffResult:
    def __init__(self):
        self.to_add = []      # List of tuples (path, size, mtime)
        self.to_update = []   # List of tuples (ExistingRecord, new_size, new_mtime)
        self.to_delete = []   # List of ExistingRecord

def _in_scope(path: str, scope_prefix: str | None) -> bool:
    return scope_prefix is None or os.path.normcase(path).startswith(scope_prefix)


def _scope_prefix(scope: str | None) -> str | None:
    if not scope:
        return None
    return os.path.normcase(os.path.normpath(scope)).rstrip("\\/") + os.sep


def count_library_records(db: Session, library_id: int, scope: str | None = None) -> int:
    q = db.query(PhotoRecord.file_path).filter(PhotoRecord.library_id == library_id)
    if not scope:
        return q.count()
    prefix = _scope_prefix(scope)
    return sum(1 for (p,) in q if _in_scope(p, prefix))


def calculate_library_diff(db: Session, library_id: int, fs_state: dict, scope: str | None = None) -> DiffResult:
    """
    Álgebra de conjuntos entre o disco e o SQLite.
    scope: se indicado, só compara os registos dentro dessa subpasta (sync parcial),
    para não apagar o resto da biblioteca.
    """
    logger.info(f"[DiffService] Calculando diferenças para Biblioteca ID={library_id}"
                + (f" (só em {scope})" if scope else ""))
    prefix = _scope_prefix(scope)
    db_records = [r for r in db.query(PhotoRecord).filter(PhotoRecord.library_id == library_id).all()
                  if _in_scope(r.file_path, prefix)]

    db_map = {rec.file_path: rec for rec in db_records}
    fs_paths = set(fs_state.keys())
    db_paths = set(db_map.keys())

    diff = DiffResult()

    # 1. ADD (No FS, Não na DB)
    # Ordenado por caminho: os ficheiros são lidos pasta a pasta (essencial em discos mecânicos/NAS)
    new_paths = sorted(fs_paths - db_paths)

    # Proteção: ficheiros que já pertencem a outra biblioteca (file_path é único) não são inseridos
    taken = set()
    for i in range(0, len(new_paths), 500):
        chunk = new_paths[i:i + 500]
        taken.update(p for (p,) in db.query(PhotoRecord.file_path).filter(
            PhotoRecord.file_path.in_(chunk), PhotoRecord.library_id != library_id))
    if taken:
        logger.warning(f"[DiffService] {len(taken)} ficheiros já pertencem a outra pasta indexada; ignorados.")

    for p in new_paths:
        if p in taken:
            continue
        size, mtime = fs_state[p]
        diff.to_add.append((p, size, mtime))
        
    # 2. DELETE (Na DB, Ausente no FS - ex: utilizador moveu foto via Windows Explorer)
    for p in (db_paths - fs_paths):
        diff.to_delete.append(db_map[p])
        
    # 3. UPDATE (Interseção - verificar corrompimento / alterações)
    for p in (fs_paths & db_paths):
        fs_size, fs_mtime = fs_state[p]
        rec = db_map[p]
        
        # Windows Modified Time tolerance (preventive sync jitter bypass via abs diff > 1.0)
        if abs(rec.mtime - fs_mtime) > 1.0 or rec.size_bytes != fs_size:
            diff.to_update.append((rec, fs_size, fs_mtime))
            
    logger.info(f"[DiffService] Diff Concluído -> +{len(diff.to_add)} | ~{len(diff.to_update)} | -{len(diff.to_delete)}")
    return diff

def apply_diff_to_db(db: Session, library_id: int, diff: DiffResult) -> list[int]:
    """
    Modifica SQLite e Devolve IDs dos PhotoRecords que carecem de ingestão na Pipeline de IA (Machine Learning).
    """
    for rec in diff.to_delete:
        db.delete(rec)
        
    for (path, size, mtime) in diff.to_add:
        import os
        new_rec = PhotoRecord(
            library_id=library_id,
            file_path=path,
            file_name=os.path.basename(path),
            guid_id=str(uuid.uuid4()),
            size_bytes=size,
            mtime=mtime,
            processing_status="PENDING"
        )
        db.add(new_rec)
        
    for (rec, new_size, new_mtime) in diff.to_update:
        rec.size_bytes = new_size
        rec.mtime = new_mtime
        rec.processing_status = "PENDING"
        rec.error_message = None
        
    db.commit()
    
    # Retorna IDs sujos para inserir na pipeline
    peding_ids = db.query(PhotoRecord.id).filter(
        PhotoRecord.library_id == library_id, 
        PhotoRecord.processing_status == "PENDING"
    ).all()
    
    return [p[0] for p in peding_ids]
